"""Diff declared against live state without writing (FR-PLAN.1-6)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from sieve_as_code.audit import record_check
from sieve_as_code.client import ProtonClient
from sieve_as_code.declared import (
    ScriptFacts,
    load_declared,
    normalize_whitespace,
    script_facts,
)
from sieve_as_code.live import discover, discover_targets
from sieve_as_code.model import (
    Filter,
    FilterSet,
    Rename,
    SieveAsCodeError,
    Targets,
    ValidationError,
)
from sieve_as_code.settings import AccountPaths

# BR-10: a superset of Proton's built-in mailboxes, so a built-in is never reported
# missing; confirm the exact names with the live smoke suite (NFR-TEST.2).
_BUILTIN_MAILBOXES = frozenset(
    {"inbox", "archive", "spam", "trash", "drafts", "draft", "sent", "starred"}
    | {"all mail"}
)
_DESTRUCTIVE_EXTENSIONS = ("vnd.proton.expire",)  # BR-12

EntryKind = Literal["create", "content", "enabled", "live-only"]


@dataclass(frozen=True)
class PlanEntry:
    """One filter-level change; `enabled` is the value to set (None for content)."""

    kind: EntryKind
    name: str
    live_id: str | None = None
    enabled: bool | None = None


@dataclass(frozen=True)
class Reorder:
    """The single order change: old sequence vs new sequence. BR-8, BR-9."""

    old: tuple[str, ...]
    new: tuple[str, ...]


@dataclass(frozen=True)
class MissingTarget:
    """A folder or label the account lacks, with the filters using it. BR-10."""

    name: str
    used_by: tuple[str, ...]
    kind: Literal["folder", "label"]


@dataclass(frozen=True)
class Flag:
    """A filter that will be written and uses a destructive extension. BR-12."""

    name: str
    extension: str


@dataclass(frozen=True)
class PlanResult:
    """Everything `plan` reports, in apply order (BR-14)."""

    missing_targets: tuple[MissingTarget, ...]
    entries: tuple[PlanEntry, ...]
    reorder: Reorder | None
    flags: tuple[Flag, ...]
    informational: tuple[str, ...]
    renamed: tuple[Rename, ...] = ()

    @property
    def outcome(self) -> Literal["clean", "drift"]:
        """BR-13: flags, informational names and renames are not drift."""
        drift = self.missing_targets or self.entries or self.reorder
        return "drift" if drift else "clean"


def _facts(declared: FilterSet) -> dict[str, ScriptFacts]:
    """BR-11, BR-17: facts of each enabled declared filter; unreadable targets fail."""
    facts: dict[str, ScriptFacts] = {}
    for item in declared.filters:
        if not item.enabled:
            continue
        facts[item.name] = script_facts(item.raw_sieve)
        for mailbox in facts[item.name].mailboxes:
            if mailbox.name is None:
                raise ValidationError(
                    f"filter {item.name!r} line {mailbox.line}: "
                    "fileinto target is not a plain quoted string"
                )
    return facts


def _missing_pieces(
    target: str, folders: set[str], labels: set[str]
) -> list[tuple[str, Literal["folder", "label"]]]:
    """BR-10: the missing folders or label behind `target`, parents first."""
    if "/" not in target:
        return [] if target.casefold() in folders | labels else [(target, "label")]
    parts = target.split("/")
    paths = ("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    missing = [path for path in paths if path and path.casefold() not in folders]
    return [(path, "folder") for path in missing]


def _missing_targets(
    order: tuple[str, ...], facts: Mapping[str, ScriptFacts], known: Targets
) -> tuple[MissingTarget, ...]:
    """BR-10: missing, non-built-in targets in order of first use, parents first."""
    folders = {
        "/".join(parts[:depth]).casefold()
        for parts in (path.split("/") for path in known.folders)
        for depth in range(1, len(parts) + 1)
    }
    labels = {name.casefold() for name in known.labels}
    found: dict[str, tuple[str, Literal["folder", "label"], list[str]]] = {}
    for name in order:
        for mailbox in facts[name].mailboxes if name in facts else ():
            target = mailbox.name
            if target is None or target.casefold() in _BUILTIN_MAILBOXES:
                continue
            for piece, kind in _missing_pieces(target, folders, labels):
                spelling, current, users = found.setdefault(
                    piece.casefold(), (piece, kind, [])
                )
                if name not in users:
                    users.append(name)
                if kind == "folder" and current == "label":
                    found[piece.casefold()] = (spelling, kind, users)
    return tuple(MissingTarget(s, tuple(u), k) for s, k, u in found.values())


def _entries(declared: FilterSet, live: Mapping[str, Filter]) -> tuple[PlanEntry, ...]:
    """BR-5, BR-6, BR-14: creates, then content, then enabled changes."""
    by_name = {item.name: item for item in declared.filters}
    creates, contents, toggles = [], [], []
    for name in declared.order.sequence:
        want = by_name[name]
        have = live.get(name)
        if have is None:
            creates.append(PlanEntry("create", name, None, want.enabled))
            continue
        if normalize_whitespace(want.raw_sieve) != normalize_whitespace(have.raw_sieve):
            contents.append(PlanEntry("content", name, have.live_id))
        if want.enabled != have.enabled:
            toggles.append(PlanEntry("enabled", name, have.live_id, want.enabled))
    return tuple(creates + contents + toggles)


def _live_only(
    declared: FilterSet, live: FilterSet
) -> tuple[tuple[PlanEntry, ...], tuple[str, ...]]:
    """BR-7: enabled live-only filters are entries, disabled ones informational."""
    known = set(declared.order.sequence)
    entries, quiet = [], []
    for item in live.filters:
        if item.name in known:
            continue
        if item.enabled:
            entries.append(PlanEntry("live-only", item.name, item.live_id, True))
        else:
            quiet.append(item.name)
    return tuple(entries), tuple(quiet)


def _reorder(declared: FilterSet, live: FilterSet) -> Reorder | None:
    """BR-8, BR-9: one entry; created filters are expected last in live order."""
    wanted = declared.order.sequence
    present = set(wanted)
    created = [name for name in wanted if name not in set(live.order.sequence)]
    old = tuple(name for name in live.order.sequence if name in present) + tuple(
        created
    )
    return None if old == wanted else Reorder(old, wanted)


def _flags(
    entries: tuple[PlanEntry, ...], facts: Mapping[str, ScriptFacts]
) -> tuple[Flag, ...]:
    """BR-12: destructive extensions in enabled filters that will be written."""
    written = [item.name for item in entries if item.kind != "live-only"]
    return tuple(
        Flag(name, extension)
        for name in dict.fromkeys(written)
        if name in facts
        for extension in _DESTRUCTIVE_EXTENSIONS
        if extension in facts[name].required
    )


def diff(declared: FilterSet, live: FilterSet, targets: Targets | None) -> PlanResult:
    """Pure diff of declared against live state. BR-3 to BR-15.

    `targets=None` is snapshot mode: no target check, missing targets or flags. BR-19.
    """
    facts = _facts(declared) if targets is not None else {}
    live_by_name = {item.name: item for item in live.filters}
    changes = _entries(declared, live_by_name)
    extra, quiet = _live_only(declared, live)
    known = targets or Targets()
    return PlanResult(
        missing_targets=_missing_targets(declared.order.sequence, facts, known),
        entries=changes + extra,
        reorder=_reorder(declared, live),
        flags=_flags(changes, facts),
        informational=quiet,
        renamed=live.renames,
    )


def plan(paths: AccountPaths, client: ProtonClient) -> PlanResult:
    """Diff the account's declared files against Proton and audit the outcome. BR-13."""
    if paths.account != client.account:
        raise ValidationError(
            f"paths are for account {paths.account!r} but the client is connected "
            f"to {client.account!r}"
        )
    try:
        filters, order = load_declared(paths)
        declared = FilterSet(tuple(filters), order)
        live = discover(client)
        result = diff(declared, live, discover_targets(client))
    except ValidationError as invalid:
        try:
            record_check(paths.audit_log, "invalid", {})
        except SieveAsCodeError as audit_failure:
            raise invalid from audit_failure
        raise
    record_check(
        paths.audit_log,
        result.outcome,
        {
            "entries": len(result.entries) + (result.reorder is not None),
            "missing_targets": len(result.missing_targets),
            "flags": len(result.flags),
            "renamed": len(result.renamed),
        },
    )
    return result
