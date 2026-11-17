"""Verified, owner-only snapshots of the live filters (FR-BAK.1-3, 5, 6)."""

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sieve_as_code._audit import record_check, record_write
from sieve_as_code._client import ProtonClient
from sieve_as_code._live import discover
from sieve_as_code._model import (
    BackupError,
    Filter,
    FilterOrder,
    FilterSet,
    Rename,
    ValidationError,
)
from sieve_as_code._plan import PlanResult, diff
from sieve_as_code._settings import AccountPaths, Retention

_FORMAT = 1
_KEYS = {
    "format",
    "created",
    "account",
    "fingerprint",
    "filters",
    "renames",
    "checksum",
}
_FILTER_KEYS = {"name", "raw_sieve", "enabled"}
_RENAME_KEYS = {"original", "name"}
SNAPSHOT_NAME = re.compile(r"\d{8}T\d{12}Z\.json")
SNAPSHOT_TIME = "%Y%m%dT%H%M%S%fZ.json"


@dataclass(frozen=True)
class Snapshot:
    """A verified snapshot; `state` has `live_id` None and feeds `diff`. BR-11, BR-14.

    `unchanged` is True when `write_backup` returned the existing latest snapshot;
    `pruned` and `prune_error` are set by the public `backup` (Unit 9 BR-5).
    """

    path: Path
    created: str
    account: str
    fingerprint: str
    state: FilterSet
    unchanged: bool = False
    pruned: tuple[str, ...] = ()
    prune_error: str | None = None


def checksum(document: dict[str, Any]) -> str:
    """Unit 5 BR-4; Unit 8 BR-21: SHA-256 of the document without its checksum."""
    body = {key: value for key, value in document.items() if key != "checksum"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _document(
    state: FilterSet, created: str, paths: AccountPaths, fingerprint: str
) -> dict[str, Any]:
    """BR-3: the snapshot as a JSON-ready mapping, checksum included."""
    document: dict[str, Any] = {
        "format": _FORMAT,
        "created": created,
        "account": paths.account,
        "fingerprint": fingerprint,
        "filters": [
            {"name": f.name, "raw_sieve": f.raw_sieve, "enabled": f.enabled}
            for f in state.filters
        ],
        "renames": [{"original": r.original, "name": r.name} for r in state.renames],
    }
    document["checksum"] = checksum(document)
    return document


def create_exclusive(path: Path, text: str) -> None:
    """Unit 5 BR-5, BR-6; Unit 8 BR-21: exclusive owner-only create, no partial file."""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(
            f"cannot create {path.parent}: {exc.strerror or exc}"
        ) from None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BackupError(
            f"snapshot {path} already exists; run the command again"
        ) from None
    except OSError as exc:
        raise BackupError(f"cannot create {path}: {exc.strerror or exc}") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        reason = exc.strerror or str(exc)
        try:
            path.unlink()
        except OSError:
            raise BackupError(
                f"cannot write {path}: {reason}; the partial file could not be "
                "removed and will fail verification"
            ) from None
        raise BackupError(f"cannot write {path}: {reason}") from None


def _detail(path: Path, state: FilterSet) -> dict[str, str | int]:
    """BR-8, BR-15: names and counts only."""
    return {
        "file": path.name,
        "filters": len(state.filters),
        "renamed": len(state.renames),
    }


def _unchanged(
    paths: AccountPaths, fingerprint: str, state: FilterSet
) -> Snapshot | None:
    """BR-14: the latest snapshot if it verifies and equals `state`, else None."""
    try:
        latest = read_backup(None, paths, fingerprint)
    except BackupError:
        return None
    return replace(latest, unchanged=True) if latest.state == state else None


def write_backup(paths: AccountPaths, client: ProtonClient) -> Snapshot:
    """Snapshot the live filters unless the latest already holds them. BR-1 to BR-15."""
    if paths.account != client.account or not client.fingerprint:
        raise ValidationError(
            f"backup needs a client connected to account '{paths.account}'"
        )
    live = discover(client)
    state = FilterSet(
        tuple(replace(f, live_id=None) for f in live.filters), live.order, live.renames
    )
    same = _unchanged(paths, client.fingerprint, state)
    if same is not None:
        record_check(paths.audit_log, "unchanged", _detail(same.path, state))
        return same
    now = datetime.now(UTC)
    created = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    document = _document(state, created, paths, client.fingerprint)
    path = paths.backups_dir / now.strftime(SNAPSHOT_TIME)
    create_exclusive(path, json.dumps(document, indent=2) + "\n")
    record_write(paths.audit_log, "backup", _detail(path, state))
    return Snapshot(path, created, paths.account, client.fingerprint, state)


def _resolve(ref: str | Path | None, backups_dir: Path) -> Path:
    """BR-9: latest, an existing file, or a name in the backups directory."""
    if ref is None:
        latest = sorted(backups_dir.glob("*.json"))
        if not latest:
            raise BackupError(f"no backups in {backups_dir}; run backup first")
        return latest[-1]
    if Path(ref).is_file():
        return Path(ref)
    name = str(ref) if str(ref).endswith(".json") else f"{ref}.json"
    named = backups_dir / name
    if Path(name).name != name or not named.is_file():
        raise BackupError(f"no backup '{ref}' (not a file, not in {backups_dir})")
    return named


def _text_field(document: dict[str, Any], key: str, path: Path) -> str:
    value = document[key]
    if not isinstance(value, str):
        raise BackupError(f"{path}: field '{key}' is not text")
    return value


def _rows(
    document: dict[str, Any], key: str, keys: set[str], path: Path
) -> list[dict[str, Any]]:
    rows = document[key]
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or set(row) != keys for row in rows
    ):
        raise BackupError(f"{path}: '{key}' is malformed")
    return rows


def _state(document: dict[str, Any], path: Path) -> FilterSet:
    """BR-10: type-check filters and renames; names are non-empty and unique."""
    rows = _rows(document, "filters", _FILTER_KEYS, path)
    for row in rows:
        valid = (
            isinstance(row["name"], str)
            and row["name"] != ""
            and isinstance(row["raw_sieve"], str)
            and isinstance(row["enabled"], bool)
        )
        if not valid:
            raise BackupError(f"{path}: a filter entry is malformed")
    names = tuple(row["name"] for row in rows)
    if len(set(names)) != len(names):
        raise BackupError(f"{path}: filter names are not unique")
    renames = _rows(document, "renames", _RENAME_KEYS, path)
    if any(not all(isinstance(v, str) for v in row.values()) for row in renames):
        raise BackupError(f"{path}: a rename entry is malformed")
    return FilterSet(
        tuple(Filter(r["name"], r["raw_sieve"], r["enabled"]) for r in rows),
        FilterOrder(names),
        tuple(Rename(r["original"], r["name"]) for r in renames),
    )


def read_backup(
    ref: str | Path | None, paths: AccountPaths, fingerprint: str
) -> Snapshot:
    """Resolve, verify and load a snapshot of account `fingerprint`. BR-9 to BR-13."""
    path = _resolve(ref, paths.backups_dir)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else "not valid JSON"
        raise BackupError(f"cannot read {path}: {reason or exc}") from None
    if not isinstance(document, dict):
        raise BackupError(f"{path}: not a snapshot")
    version = document.get("format")
    if version != _FORMAT:
        raise BackupError(f"{path}: unsupported snapshot format {version!r}")
    if set(document) != _KEYS:
        raise BackupError(f"{path}: unexpected or missing fields")
    if document["checksum"] != checksum(document):
        raise BackupError(f"{path}: checksum mismatch; the file was altered or damaged")
    state = _state(document, path)
    recorded = _text_field(document, "fingerprint", path)
    if recorded != fingerprint:
        raise BackupError(
            f"{path}: belongs to a different Proton account "
            f"(fingerprint {recorded}, expected {fingerprint})"
        )
    created = _text_field(document, "created", path)
    return Snapshot(
        path, created, _text_field(document, "account", path), recorded, state
    )


def diff_backups(a: str | Path, b: str | Path, paths: AccountPaths) -> PlanResult:
    """What changed from snapshot `a` to snapshot `b`, offline. BR-12."""
    try:
        fingerprint = paths.account_marker.read_text().strip()
    except OSError as exc:
        raise BackupError(
            f"cannot read {paths.account_marker}: {exc.strerror or exc}"
        ) from None
    if not fingerprint:
        raise BackupError(f"{paths.account_marker} is empty")
    first = read_backup(a, paths, fingerprint)
    second = read_backup(b, paths, fingerprint)
    return diff(second.state, first.state, None)


def snapshot_candidates(backups_dir: Path) -> list[tuple[str, datetime]]:
    """BR-16: snapshot-named regular files with their name's UTC time, oldest first."""
    found: list[tuple[str, datetime]] = []
    for item in backups_dir.glob("*.json") if backups_dir.is_dir() else ():
        if not (SNAPSHOT_NAME.fullmatch(item.name) and item.is_file()):
            continue
        try:
            when = datetime.strptime(item.name, SNAPSHOT_TIME)
            found.append((item.name, when.replace(tzinfo=UTC)))
        except ValueError:
            continue
    return sorted(found)


def prune_backups(paths: AccountPaths, keep: Retention) -> tuple[str, ...]:
    """Remove snapshots outside the retention limits; return their names. BR-16-18."""
    files = snapshot_candidates(paths.backups_dir)
    if not files or (keep.keep_days is None and keep.keep_last is None):
        return ()
    cutoff = datetime.now(UTC) - timedelta(days=keep.keep_days or 0)
    kept = {files[-1][0]}
    if keep.keep_last:
        kept |= {name for name, _ in files[-keep.keep_last :]}
    if keep.keep_days:
        kept |= {name for name, when in files if when >= cutoff}
    doomed = [name for name, _ in files if name not in kept]
    removed: list[str] = []
    failure: OSError | None = None
    for name in doomed:
        try:
            (paths.backups_dir / name).unlink()
        except OSError as exc:
            failure = exc
            break
        removed.append(name)
    if removed:
        counts = {"removed": len(removed), "kept": len(files) - len(removed)}
        record_write(paths.audit_log, "prune", counts)
    if failure is not None:
        raise BackupError(
            f"cannot remove {paths.backups_dir / doomed[len(removed)]}: "
            f"{failure.strerror or failure}"
        ) from None
    return tuple(removed)
