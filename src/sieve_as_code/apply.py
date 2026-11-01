"""Write a plan to Proton in order, stopping at the first failure (FR-APPLY.1-6)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import partial
from typing import Literal

from sieve_as_code.audit import record_check, record_write
from sieve_as_code.backup import Snapshot, read_backup, write_backup
from sieve_as_code.client import ProtonClient
from sieve_as_code.declared import load_declared
from sieve_as_code.live import discover, discover_targets
from sieve_as_code.model import (
    ClientError,
    Filter,
    FilterOrder,
    FilterSet,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code.plan import MissingTarget, PlanEntry, PlanResult, diff
from sieve_as_code.settings import AccountPaths

ActionKind = (
    Literal[
        "folder",
        "label",
        "create",
        "content",
        "enabled",
        "disable",
        "delete",
        "reorder",
    ]
    | Literal["verify"]
)


@dataclass(frozen=True)
class Action:
    """One Proton write; `name` is `order` for the reorder and `live` for verify."""

    kind: ActionKind
    name: str


@dataclass(frozen=True)
class FailedAction:
    """The action that ended a run and the first line of `proton`'s reason."""

    action: Action
    reason: str


@dataclass(frozen=True)
class ApplyReport:
    """What a run planned, snapshotted, wrote and did not write. BR-13."""

    plan: PlanResult
    refused: bool = False
    snapshot: Snapshot | None = None
    succeeded: tuple[Action, ...] = ()
    failed: FailedAction | None = None
    not_attempted: tuple[Action, ...] = ()
    audit_error: str | None = None

    @property
    def ok(self) -> bool:
        """True when the run was not refused and nothing failed."""
        return not self.refused and self.failed is None and self.audit_error is None


Step = tuple[Action, Callable[[], None]]


def check_client(paths: AccountPaths, client: ProtonClient) -> None:
    """BR-1: the client must be connected to the paths' account."""
    if paths.account != client.account or not client.fingerprint:
        raise ValidationError(
            f"writing needs a client connected to account '{paths.account}'"
        )


def _create_target(client: ProtonClient, target: MissingTarget) -> None:
    """BR-6, BR-8: a label, or a folder under its parent found at run time."""
    if target.kind == "label":
        client.create_label(target.name)
        return
    parent, _, leaf = target.name.rpartition("/")
    parent_id = None
    if parent:
        found = next(
            (
                f
                for f in client.list_folders()
                if f.path.casefold() == parent.casefold()
            ),
            None,
        )
        if found is None:
            raise ClientError(f"parent folder {parent!r} not found")
        parent_id = found.id
    client.create_folder(leaf, parent_id)


def _create_filter(client: ProtonClient, ids: dict[str, str], item: Filter) -> None:
    """BR-6, BR-7: remember the new id for the reorder."""
    ids[item.name] = client.create_filter(item.name, item.raw_sieve, item.enabled)


def _reorder(
    client: ProtonClient, ids: Mapping[str, str], names: tuple[str, ...]
) -> None:
    """BR-7: name the desired sequence as ids."""
    client.reorder_filters([ids[name] for name in names])


def _entry_step(
    client: ProtonClient,
    entry: PlanEntry,
    wanted: Mapping[str, Filter],
    ids: dict[str, str],
    delete: bool,
) -> Step:
    """BR-6, BR-9: one entry becomes one client call."""
    name = entry.name
    if entry.kind == "create":
        return Action("create", name), partial(
            _create_filter, client, ids, wanted[name]
        )
    if entry.kind == "content":
        script = wanted[name].raw_sieve
        return Action("content", name), partial(client.update_filter, ids[name], script)
    if entry.kind == "enabled":
        write = client.enable_filter if entry.enabled else client.disable_filter
        return Action("enabled", name), partial(write, ids[name])
    if delete:
        return Action("delete", name), partial(client.delete_filter, ids[name])
    return Action("disable", name), partial(client.disable_filter, ids[name])


def build_steps(
    client: ProtonClient,
    result: PlanResult,
    desired: FilterSet,
    live: FilterSet,
    delete: bool,
) -> list[Step]:
    """BR-6: targets, entries in plan order, then the reorder."""
    ids = {item.name: item.live_id for item in live.filters if item.live_id}
    wanted = {item.name: item for item in desired.filters}
    steps: list[Step] = [
        (Action(target.kind, target.name), partial(_create_target, client, target))
        for target in result.missing_targets
    ]
    steps += [_entry_step(client, e, wanted, ids, delete) for e in result.entries]
    if result.reorder:
        reorder = partial(_reorder, client, ids, result.reorder.new)
        steps.append((Action("reorder", "order"), reorder))
    return steps


def _snapshot(paths: AccountPaths, client: ProtonClient) -> Snapshot:
    """BR-5, BR-20: snapshot live state and prove it reads back."""
    snapshot = write_backup(paths, client)
    read_backup(snapshot.path, paths, client.fingerprint)
    return snapshot


def _audit(
    paths: AccountPaths,
    command: str,
    action: Action,
    failure: FailedAction | None,
    exit_code: int | None,
) -> str | None:
    """BR-11, BR-12: one write line; an audit failure is returned, not raised."""
    detail: dict[str, str | int | None] = {
        "command": command,
        "action": action.kind,
        "name": action.name,
    }
    if failure is not None:
        detail["exit_code"] = exit_code
    try:
        record_write(paths.audit_log, "failed" if failure else "ok", detail)
    except SieveAsCodeError as error:
        return str(error)
    return None


def run_actions[R: ApplyReport](
    report: R,
    paths: AccountPaths,
    client: ProtonClient,
    command: str,
    steps: list[Step],
    confirmed: bool,
) -> R:
    """Refuse, or snapshot and run `steps` to the first failure. BR-4, BR-5, BR-10."""
    if not confirmed:
        record_check(
            paths.audit_log, "refused", {"command": command, "actions": len(steps)}
        )
        return replace(report, refused=True)
    report = replace(report, snapshot=_snapshot(paths, client))
    succeeded: list[Action] = []
    for index, (action, step) in enumerate(steps):
        failure, exit_code = None, None
        try:
            step()
        except ClientError as error:
            failure, exit_code = FailedAction(action, str(error)), error.exit_code
        audit_error = _audit(paths, command, action, failure, exit_code)
        if failure is None:
            succeeded.append(action)
        if failure or audit_error:
            rest = tuple(a for a, _ in steps[index + 1 :])
            return replace(
                report,
                succeeded=tuple(succeeded),
                failed=failure,
                not_attempted=rest,
                audit_error=audit_error,
            )
    return replace(report, succeeded=tuple(succeeded))


def apply_plan(
    paths: AccountPaths, client: ProtonClient, confirmed: bool, allow_delete: bool
) -> ApplyReport:
    """Write the declared filters to Proton after a verified snapshot. BR-1 to BR-14."""
    check_client(paths, client)
    filters, order = load_declared(paths)
    desired = FilterSet(tuple(filters), FilterOrder(order.sequence))
    live = discover(client)
    result = diff(desired, live, discover_targets(client))
    steps = build_steps(client, result, desired, live, allow_delete)
    report = ApplyReport(result)
    if not steps:
        return report
    return run_actions(report, paths, client, "apply", steps, confirmed)
