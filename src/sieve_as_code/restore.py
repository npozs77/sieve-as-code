"""Restore a snapshot, then prove live state equals it (FR-BAK.4)."""

from dataclasses import dataclass, replace
from pathlib import Path

from sieve_as_code.apply import (
    Action,
    ApplyReport,
    FailedAction,
    build_steps,
    check_client,
    run_actions,
)
from sieve_as_code.audit import record_check
from sieve_as_code.backup import Snapshot, read_backup
from sieve_as_code.client import ProtonClient
from sieve_as_code.live import discover
from sieve_as_code.model import ClientError, FilterSet, SieveAsCodeError
from sieve_as_code.plan import PlanEntry, PlanResult, diff
from sieve_as_code.settings import AccountPaths


def _is_clean(remaining: PlanResult) -> bool:
    """BR-21: nothing differs from the backup, not even a disabled extra filter."""
    return remaining.outcome == "clean" and not remaining.informational


@dataclass(frozen=True)
class RestoreReport(ApplyReport):
    """An `ApplyReport` plus the diff against the backup after the run. BR-21."""

    remaining: PlanResult | None = None

    @property
    def ok(self) -> bool:
        """True when nothing failed and live state equals the backup."""
        return super().ok and (self.remaining is None or _is_clean(self.remaining))


def _with_deletes(
    result: PlanResult, snapshot: FilterSet, live: FilterSet
) -> PlanResult:
    """BR-16, BR-17: every live filter the backup lacks is deleted, in live order."""
    kept = tuple(e for e in result.entries if e.kind != "live-only")
    wanted = set(snapshot.order.sequence)
    extra = tuple(
        PlanEntry("live-only", item.name, item.live_id, False)
        for item in live.filters
        if item.name not in wanted
    )
    return replace(result, entries=kept + extra)


def _verify(
    report: RestoreReport, paths: AccountPaths, client: ProtonClient, snapshot: Snapshot
) -> RestoreReport:
    """BR-21, BR-22: re-read live state and audit the outcome."""
    try:
        live = discover(client)
    except ClientError as error:
        return replace(
            report, failed=FailedAction(Action("verify", "live"), str(error))
        )
    remaining = diff(snapshot.state, live, None)
    report = replace(report, remaining=remaining)
    detail = {
        "entries": len(remaining.entries),
        "informational": len(remaining.informational),
        "reordered": int(remaining.reorder is not None),
    }
    try:
        record_check(
            paths.audit_log, "verified" if _is_clean(remaining) else "drift", detail
        )
    except SieveAsCodeError as error:
        return replace(report, audit_error=str(error))
    return report


def restore(
    ref: str | Path | None,
    paths: AccountPaths,
    client: ProtonClient,
    confirmed: bool,
) -> RestoreReport:
    """Return live filters to a snapshot, deleting later ones. BR-15 to BR-22."""
    check_client(paths, client)
    snapshot = read_backup(ref, paths, client.fingerprint)
    live = discover(client)
    plan = diff(snapshot.state, live, None)
    steps = build_steps(
        client, _with_deletes(plan, snapshot.state, live), snapshot.state, live, True
    )
    report = RestoreReport(plan)
    if not steps:
        return report
    done = run_actions(report, paths, client, "restore", steps, confirmed)
    if done.refused or done.failed or done.audit_error:
        return done
    return _verify(done, paths, client, snapshot)
