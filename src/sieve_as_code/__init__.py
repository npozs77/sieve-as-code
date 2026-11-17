"""Proton Mail Sieve filters as code. `__all__` is the whole public API.

Every function takes its subject positionally and everything else by keyword;
`account` is the `proton-cli` profile name (default: `SIEVE_AS_CODE_ACCOUNT`,
else `default`). Semver; provisional until 1.0.
"""

from collections.abc import Sequence
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

from sieve_as_code import (
    _apply,
    _backup,
    _declared,
    _importer,
    _live,
    _plan,
    _restore,
    _retroactive,
)
from sieve_as_code._apply import Action, ApplyReport, FailedAction
from sieve_as_code._backup import Snapshot
from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._importer import ImportReport
from sieve_as_code._model import (
    BackupError,
    ClientError,
    Filter,
    FilterOrder,
    FilterSet,
    Rename,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code._plan import Flag, MissingTarget, PlanEntry, PlanResult, Reorder
from sieve_as_code._restore import RestoreReport
from sieve_as_code._retroactive import (
    AuditRow,
    Entry,
    RetroAudit,
    RetroPreview,
    RetroReport,
    RetroStatus,
    Unexpected,
)
from sieve_as_code._settings import (
    AccountPaths,
    Retention,
    account_paths,
    resolve_account,
    retention,
)

__version__ = version("sieve-as-code")

__all__ = [
    "Action",
    "ApplyReport",
    "AuditRow",
    "BackupError",
    "ClientError",
    "Entry",
    "FailedAction",
    "Filter",
    "FilterOrder",
    "FilterSet",
    "Flag",
    "ImportReport",
    "MissingTarget",
    "PlanEntry",
    "PlanResult",
    "Rename",
    "Reorder",
    "RestoreReport",
    "RetroAudit",
    "RetroPreview",
    "RetroReport",
    "RetroStatus",
    "SieveAsCodeError",
    "Snapshot",
    "Unexpected",
    "ValidationError",
    "__version__",
    "apply",
    "apply_retroactive",
    "backup",
    "backup_diff",
    "discover",
    "import_live",
    "import_sieve_files",
    "load_declared",
    "plan",
    "restore",
    "retroactive_audit",
    "retroactive_preview",
    "retroactive_status",
    "validate_declared",
]


def _paths(account: str | None) -> AccountPaths:
    """BR-2: resolve the account name to its paths."""
    return account_paths(resolve_account(account))


def _session(account: str | None) -> tuple[AccountPaths, ProtonClient]:
    """BR-2: paths and a connected, account-checked client."""
    paths = _paths(account)
    return paths, connect(paths)


def discover(*, account: str | None = None) -> FilterSet:
    """Read all live filters in order; duplicate names are numbered (`renames`)."""
    return _live.discover(_session(account)[1])


def plan(*, account: str | None = None) -> PlanResult:
    """Diff declared against live state; changes nothing in Proton."""
    return _plan.plan(*_session(account))


def apply(
    *,
    account: str | None = None,
    confirmed: bool = False,
    allow_delete: bool = False,
) -> ApplyReport:
    """Write the declared filters to Proton after a snapshot; needs `confirmed`."""
    paths, client = _session(account)
    return _apply.apply_plan(paths, client, confirmed, allow_delete)


def import_live(
    name: str | None = None, *, account: str | None = None, force: bool = False
) -> ImportReport:
    """Write live filters (all, or `name`) into the declared files."""
    paths, client = _session(account)
    return _importer.import_live(paths, client, name, force)


def import_sieve_files(
    sources: Sequence[Path], *, account: str | None = None, force: bool = False
) -> ImportReport:
    """Write plain `.sieve` files into the declared files, named by file name."""
    return _importer.import_sieve_files(_paths(account), sources, force)


def _limit(name: str, value: int | None) -> int | None:
    """BR-5: a retention argument is None or a whole number of 1 or more."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{name} must be a whole number of 1 or more")
    return value


def backup(
    *,
    account: str | None = None,
    keep_days: int | None = None,
    keep_last: int | None = None,
) -> Snapshot:
    """Snapshot live filters, then prune per the limits (arguments, else env)."""
    days, last = _limit("keep_days", keep_days), _limit("keep_last", keep_last)
    env = retention()
    limits = Retention(days or env.keep_days, last or env.keep_last)
    paths, client = _session(account)
    snapshot = _backup.write_backup(paths, client)
    try:
        return replace(snapshot, pruned=_backup.prune_backups(paths, limits))
    except BackupError as exc:
        return replace(snapshot, prune_error=str(exc))


def backup_diff(
    a: str | Path, b: str | Path, *, account: str | None = None
) -> PlanResult:
    """What changed from snapshot `a` to snapshot `b`; offline."""
    return _backup.diff_backups(a, b, _paths(account))


def restore(
    ref: str | Path | None = None,
    *,
    account: str | None = None,
    confirmed: bool = False,
) -> RestoreReport:
    """Return live filters to a snapshot (default: latest); needs `confirmed`."""
    paths, client = _session(account)
    return _restore.restore(ref, paths, client, confirmed)


def retroactive_preview(name: str, *, account: str | None = None) -> RetroPreview:
    """List the existing messages `filters apply` would change; read-only."""
    return _retroactive.preview(*_session(account), name)


def apply_retroactive(
    name: str, *, confirmed_name: str, reason: str, account: str | None = None
) -> RetroReport:
    """Run one filter on existing mail; `confirmed_name` must equal `name`."""
    paths, client = _session(account)
    return _retroactive.run(paths, client, name, confirmed_name, reason)


def retroactive_status(
    ref: str | Path | None = None, *, account: str | None = None
) -> RetroStatus:
    """Compare the current preview with a retroactive snapshot (default: latest)."""
    paths, client = _session(account)
    return _retroactive.status(paths, client, ref)


def retroactive_audit(*, account: str | None = None) -> RetroAudit:
    """Count the messages each enabled filter would change; read-only."""
    return _retroactive.audit_all(*_session(account))


def load_declared(*, account: str | None = None) -> FilterSet:
    """Load and validate the declared files of an account."""
    filters, order = _declared.load_declared(_paths(account))
    return FilterSet(tuple(filters), order)


def validate_declared(declared: FilterSet) -> None:
    """Raise `ValidationError` when `declared` is not a valid declared set."""
    _declared.validate_declared(declared.filters, declared.order)
