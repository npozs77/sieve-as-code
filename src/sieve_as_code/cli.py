"""The `sieve-as-code` command: argparse dispatch over the public API (FR-CLI.1)."""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import sieve_as_code as api
from sieve_as_code._apply import ApplyReport
from sieve_as_code._declared import render
from sieve_as_code._model import SieveAsCodeError, ValidationError
from sieve_as_code._plan import PlanResult
from sieve_as_code._restore import RestoreReport
from sieve_as_code._retroactive import RetroPreview, RetroReport
from sieve_as_code._settings import account_paths, resolve_account

Handler = Callable[[argparse.Namespace], int]


def _identity(account: str | None) -> str:
    """BR-10: the account name, with the fingerprint `connect` recorded, if any."""
    paths = account_paths(resolve_account(account))
    try:
        fingerprint = paths.account_marker.read_text().strip()
    except OSError:
        fingerprint = ""
    suffix = f" (fingerprint {fingerprint})" if fingerprint else ""
    return f"{paths.account}{suffix}"


def _show(args: argparse.Namespace, lines: Sequence[str]) -> None:
    """BR-10: print the account line, then the result lines."""
    print(f"account: {_identity(args.account)}")
    for line in lines:
        print(line)


def _plan_lines(result: PlanResult) -> list[str]:
    """BR-7, BR-11: plan entries in apply order; names only, never scripts."""
    lines = [
        f"missing {item.kind}: {item.name} (used by {', '.join(item.used_by)})"
        for item in result.missing_targets
    ]
    for entry in result.entries:
        state = "" if entry.enabled is None else f" -> enabled={entry.enabled}"
        lines.append(f"{entry.kind}: {entry.name}{state}")
    if result.reorder:
        lines.append(f"reorder: {result.reorder.old} -> {result.reorder.new}")
    lines += [f"warning: {f.name} uses {f.extension}" for f in result.flags]
    lines += [
        f"info: {name} is live-only and disabled" for name in result.informational
    ]
    lines += [f"renamed: {r.original} -> {r.name}" for r in result.renamed]
    return [*lines, f"outcome: {result.outcome}"]


def _apply_lines(report: ApplyReport) -> list[str]:
    """BR-8: the plan, then what was written, failed and not attempted."""
    lines = _plan_lines(report.plan)
    if report.refused:
        lines.append("nothing written; re-run with --yes")
    if report.snapshot:
        lines.append(f"snapshot: {report.snapshot.path}")
    lines += [f"done: {a.kind} {a.name}" for a in report.succeeded]
    if report.failed:
        failed = report.failed
        lines.append(
            f"failed: {failed.action.kind} {failed.action.name}: {failed.reason}"
        )
    lines += [f"not attempted: {a.kind} {a.name}" for a in report.not_attempted]
    if report.audit_error:
        lines.append(f"error: audit log not written: {report.audit_error}")
    return lines


def _restore_lines(report: RestoreReport) -> list[str]:
    """BR-7: the apply lines plus a remaining diff when restore did not converge."""
    lines = _apply_lines(report)
    if report.remaining is not None and report.failed is None and not report.ok:
        lines += [
            "remaining differences from the backup:",
            *_plan_lines(report.remaining),
        ]
    return lines


def _preview_lines(preview: RetroPreview) -> list[str]:
    """BR-9, BR-11: what the run would change; entries as FR-RETRO.1 requires."""
    if not preview.previewable:
        return [f"{preview.filter}: not previewable: {preview.reason}"]
    lines = [f"{preview.filter}: {len(preview.entries)} messages would change"]
    if preview.approximate:
        lines.append("note: recipient matches rely on Proton's search (approximate)")
    if preview.declared_differs:
        lines.append("warning: the declared file differs from live; the run uses live")
    if preview.spam_excluded:
        lines.append(f"spam excluded: {preview.spam_excluded}")
    lines += [
        f"  {e.date}  {e.sender}  {e.subject}  [{e.location}]  {', '.join(e.actions)}"
        for e in preview.entries
    ]
    return lines


def _retro_lines(report: RetroReport) -> list[str]:
    """BR-9: outcome of a confirmed or refused run."""
    if report.refused:
        return ["not confirmed; nothing changed"]
    lines = []
    if report.failed:
        lines.append(f"failed: {report.failed}")
    elif report.started:
        lines.append("started: Proton is running the filter on existing mail")
    lines.append(f"snapshot: {report.snapshot or 'none (filter not previewable)'}")
    if report.audit_error:
        lines.append(f"error: audit log not written: {report.audit_error}")
    if report.prune_error:
        lines.append(f"warning: old snapshots not removed: {report.prune_error}")
    return lines


def _discover(args: argparse.Namespace) -> int:
    """BR-12: print the live filters in the declared format; write nothing."""
    live = api.discover(account=args.account)
    paths = account_paths(resolve_account(args.account))
    lines: list[str] = []
    for path, text in render(live.filters, live.order, paths).items():
        lines += [f"# {path.name}", text.rstrip("\n")]
    lines += [f"renamed: {r.original} -> {r.name}" for r in live.renames]
    _show(args, lines)
    return 0


def _plan(args: argparse.Namespace) -> int:
    """BR-7: drift is output."""
    _show(args, _plan_lines(api.plan(account=args.account)))
    return 0


def _apply(args: argparse.Namespace) -> int:
    """BR-8: write only with `--yes`."""
    report = api.apply(
        account=args.account, confirmed=args.yes, allow_delete=args.allow_delete
    )
    _show(args, _apply_lines(report))
    return 0 if report.ok else 1


def _import(args: argparse.Namespace) -> int:
    """BR-13: import live filters or `.sieve` files."""
    if args.sieve and args.name:
        raise ValidationError("NAME and --sieve cannot be combined")
    if args.sieve:
        sources = [Path(item) for item in args.sieve]
        report = api.import_sieve_files(sources, account=args.account, force=args.force)
    else:
        report = api.import_live(args.name, account=args.account, force=args.force)
    lines = [f"new: {name}" for name in report.new]
    lines += [f"changed: {name}" for name in report.changed]
    lines += [f"preserved (local only): {name}" for name in report.preserved]
    lines += [f"renamed: {r.original} -> {r.name}" for r in report.renamed]
    lines += [f"wrote: {path}" for path in report.written]
    if report.refused:
        lines.append("nothing written; re-run with --force")
    _show(args, lines)
    return 0 if report.ok else 1


def _backup(args: argparse.Namespace) -> int:
    """BR-5: snapshot, then prune."""
    snapshot = api.backup(
        account=args.account, keep_days=args.keep_days, keep_last=args.keep_last
    )
    lines = [f"snapshot: {snapshot.path}"]
    if snapshot.unchanged:
        lines.append("no change since this snapshot")
    if snapshot.pruned:
        lines.append(f"pruned: {len(snapshot.pruned)} old snapshots")
    _show(args, lines)
    if snapshot.prune_error:
        print(f"warning: prune failed: {snapshot.prune_error}", file=sys.stderr)
    return 0


def _backup_diff(args: argparse.Namespace) -> int:
    """BR-7: differences between two snapshots are output."""
    _show(args, _plan_lines(api.backup_diff(args.a, args.b, account=args.account)))
    return 0


def _restore(args: argparse.Namespace) -> int:
    """BR-8: roll back only with `--yes`."""
    report = api.restore(args.backup, account=args.account, confirmed=args.yes)
    _show(args, _restore_lines(report))
    return 0 if report.ok else 1


def _ask(prompt: str) -> str:
    """BR-9: one typed answer; end of input is an empty answer."""
    try:
        return input(prompt)
    except EOFError:
        return ""


def _apply_retroactive(args: argparse.Namespace) -> int:
    """BR-9: preview, typed confirmation, run."""
    preview = api.retroactive_preview(args.name, account=args.account)
    _show(args, _preview_lines(preview))
    if preview.previewable and not preview.entries:
        print("nothing to do")
        return 0
    who = _identity(args.account)
    print(f"This cannot be cancelled once started (account {who}).")
    typed = _ask(f"Type the filter name {args.name!r} to run it: ")
    reason = _ask("Reason: ")
    report = api.apply_retroactive(
        args.name, confirmed_name=typed, reason=reason, account=args.account
    )
    for line in _retro_lines(report):
        print(line)
    return 0 if report.ok else 1


def _retroactive_status(args: argparse.Namespace) -> int:
    """BR-7: pending and unexpected messages are output."""
    status = api.retroactive_status(args.snapshot, account=args.account)
    lines = [
        f"{status.filter}: done {status.done}, pending {len(status.pending)}, "
        f"unexpected {len(status.unexpected)}"
    ]
    if status.script_changed:
        lines.append("note: the filter script changed since the run")
    lines += [
        f"  pending {e.message_id}  {e.date}  {e.sender}  {e.subject}"
        for e in status.pending
    ]
    lines += [f"  unexpected {u.message_id}: {u.reason}" for u in status.unexpected]
    _show(args, lines)
    return 0


def _retroactive_audit(args: argparse.Namespace) -> int:
    """BR-7: per enabled filter, how many messages a run would change."""
    lines = []
    for row in api.retroactive_audit(account=args.account).rows:
        count = "not previewable" if row.changes is None else str(row.changes)
        lines.append(f"{row.name}: {count}" + (f" ({row.note})" if row.note else ""))
    _show(args, lines)
    return 0


def _whole_number(text: str) -> int:
    """BR-14: argparse type for `--keep-days` and `--keep-last`."""
    if not (text.isascii() and text.isdigit() and int(text) >= 1):
        raise argparse.ArgumentTypeError("must be a whole number of 1 or more")
    return int(text)


def _add_commands(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """BR-14: one subparser per command, each with `--account`."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--account", help="proton-cli profile (default: env, else 'default')"
    )

    def add(name: str, handler: Handler, text: str) -> argparse.ArgumentParser:
        parser = sub.add_parser(name, parents=[common], help=text, description=text)
        parser.set_defaults(handler=handler)
        return parser

    add("discover", _discover, "print live filters in the declared format")
    add("plan", _plan, "diff declared against live; changes nothing")
    add("apply", _apply, "write the plan to Proton after a snapshot")
    p = add("import", _import, "write live filters or .sieve files to declared files")
    p.add_argument("name", nargs="?", help="import only this live filter")
    p.add_argument("--sieve", nargs="+", metavar="FILE", help="import .sieve files")
    p.add_argument("--force", action="store_true", help="overwrite differing files")
    p = add("backup", _backup, "snapshot live filters")
    p.add_argument("--keep-days", type=_whole_number, help="keep snapshots this young")
    p.add_argument("--keep-last", type=_whole_number, help="keep the newest N")
    p = add("backup-diff", _backup_diff, "compare two snapshots")
    p.add_argument("a")
    p.add_argument("b")
    p = add("restore", _restore, "return live filters to a snapshot")
    p.add_argument("backup", nargs="?", help="path or name; default: latest")
    p = add("apply-retroactive", _apply_retroactive, "run a filter on existing mail")
    p.add_argument("name")
    p = add("retroactive-status", _retroactive_status, "compare with a run's snapshot")
    p.add_argument("snapshot", nargs="?", help="path or name; default: latest")
    add("retroactive-audit", _retroactive_audit, "count messages each filter changes")
    for name in ("apply", "restore"):
        sub.choices[name].add_argument(
            "--yes", action="store_true", help="confirm writes"
        )
    sub.choices["apply"].add_argument(
        "--allow-delete", action="store_true", help="delete live-only filters"
    )


def _parser() -> argparse.ArgumentParser:
    """The top-level parser with `--version` and every command."""
    parser = argparse.ArgumentParser(
        prog="sieve-as-code", description="Proton Mail Sieve filters as code."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {api.__version__}"
    )
    _add_commands(parser.add_subparsers(dest="command", metavar="COMMAND"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code (BR-6, BR-15)."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return int(args.handler(args))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SieveAsCodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
