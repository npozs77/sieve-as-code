"""Preview, gated run, snapshots, status and audit of retroactive runs (FR-RETRO)."""

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sieve_as_code._apply import check_client
from sieve_as_code._audit import record_check, record_write
from sieve_as_code._backup import (
    SNAPSHOT_TIME,
    checksum,
    create_exclusive,
    snapshot_candidates,
)
from sieve_as_code._client import MailTarget, ProtonClient
from sieve_as_code._declared import load_local, normalize_whitespace
from sieve_as_code._live import discover
from sieve_as_code._model import (
    BackupError,
    ClientError,
    Filter,
    SieveAsCodeError,
    UnsupportedSieve,
    ValidationError,
)
from sieve_as_code._settings import AccountPaths
from sieve_as_code._sieve_eval import (
    CompiledScript,
    MailMessage,
    Outcome,
    compile_script,
    evaluate,
)

_SPAM = "4"
_STARRED = "10"
_SYSTEM_FOLDERS = {
    "3": "Trash",
    "6": "Archive",
    "0": "Inbox",
    "7": "Sent",
    "8": "Drafts",
}
_SYSTEM_TARGETS = {"inbox": "0", "archive": "6", "trash": "3", "spam": "4"}
_RETENTION = timedelta(days=10)
_COMMAND = "apply-retroactive"
_FORMAT = 1
_KEYS = {
    "format",
    "created",
    "account",
    "fingerprint",
    "filter",
    "script_sha256",
    "messages",
    "checksum",
}


@dataclass(frozen=True)
class Entry:
    """One message the filter would change. BR-14."""

    message_id: str
    date: str
    sender: str
    subject: str
    location: str
    actions: tuple[str, ...]


@dataclass(frozen=True)
class RetroPreview:
    """What `filters apply` would change for one filter. BR-11, BR-14, BR-15."""

    filter: str
    previewable: bool
    reason: str | None
    approximate: bool
    entries: tuple[Entry, ...]
    spam_excluded: int
    declared_differs: bool


@dataclass(frozen=True)
class RetroReport:
    """Outcome of `run`; `started` means Proton accepted the command. BR-17 to BR-25."""

    preview: RetroPreview
    refused: bool = False
    started: bool = False
    snapshot: Path | None = None
    failed: str | None = None
    audit_error: str | None = None
    prune_error: str | None = None

    @property
    def ok(self) -> bool:
        """BR-25: not refused, not failed, audit written."""
        return not self.refused and self.failed is None and self.audit_error is None


@dataclass(frozen=True)
class Unexpected:
    """A message the snapshot does not explain. BR-27."""

    message_id: str
    reason: Literal["new", "gone"]


@dataclass(frozen=True)
class RetroStatus:
    """A snapshot compared with the current preview. BR-27."""

    filter: str
    snapshot: Path
    done: int
    pending: tuple[Entry, ...]
    unexpected: tuple[Unexpected, ...]
    script_changed: bool


@dataclass(frozen=True)
class AuditRow:
    """One enabled filter in `audit_all`; `changes` is None when not previewable."""

    name: str
    changes: int | None
    note: str | None


@dataclass(frozen=True)
class RetroAudit:
    """Per-filter retroactive effect. BR-28."""

    rows: tuple[AuditRow, ...]


@dataclass(frozen=True)
class _Target:
    kind: Literal["folder", "label"]
    id: str
    name: str


def _message(row: dict[str, Any]) -> MailMessage:
    """BR-3: one `messages list` row, or a ClientError for any other shape."""
    try:
        text = [row[key] for key in ("id", "subject", "from_name", "from_address")]
        number = [row["time"], row["unread"]]
        labels = row["labels"]
        valid = (
            all(isinstance(value, str) for value in text)
            and all(isinstance(value, int) for value in number)
            and isinstance(labels, list)
            and all(isinstance(label, str) for label in labels)
        )
    except KeyError:
        valid = False
    if not valid:
        raise ClientError("unexpected proton output for `mail messages list`")
    return MailMessage(
        text[0],
        text[1],
        text[2],
        text[3],
        number[0],
        bool(number[1]),
        frozenset(labels),
    )


@dataclass
class _Mail:
    """One read of the mailbox, shared by every filter evaluated against it."""

    client: ProtonClient
    messages: tuple[MailMessage, ...]
    folders: dict[str, MailTarget]
    labels: dict[str, MailTarget]
    searched: dict[str, frozenset[str]] = field(default_factory=dict)

    def recipients(self, key: str) -> frozenset[str]:
        """BR-10: ids of the messages Proton matches to recipient `key`."""
        if key not in self.searched:
            rows = self.client.list_messages(to=key)
            self.searched[key] = frozenset(_message(row).id for row in rows)
        return self.searched[key]


def _read_mail(client: ProtonClient) -> _Mail:
    """BR-3: folders, labels and the whole listing, read-only."""
    folders = {t.path.casefold(): t for t in client.list_folders()}
    labels = {t.name.casefold(): t for t in client.list_labels()}
    messages = tuple(_message(row) for row in client.list_messages())
    return _Mail(client, messages, folders, labels)


def _location(message: MailMessage, mail: _Mail) -> tuple[str, str]:
    """BR-5: the message's folder id and display name."""
    for folder_id, name in _SYSTEM_FOLDERS.items():
        if folder_id in message.labels:
            return folder_id, name
    for folder in mail.folders.values():
        if folder.id in message.labels:
            return folder.id, folder.path
    return "", "unknown"


def _resolve(name: str, mail: _Mail) -> _Target | None:
    """BR-9: a `fileinto` target as a system folder, custom folder or label."""
    key = name.casefold()
    if key in _SYSTEM_TARGETS:
        folder_id = _SYSTEM_TARGETS[key]
        return _Target("folder", folder_id, _SYSTEM_FOLDERS.get(folder_id, "Spam"))
    if key in mail.folders:
        return _Target("folder", mail.folders[key].id, mail.folders[key].path)
    if key in mail.labels:
        return _Target("label", mail.labels[key].id, mail.labels[key].name)
    return None


def _prepare(
    script: str, mail: _Mail
) -> tuple[CompiledScript, dict[str, _Target]] | str:
    """BR-6, BR-9, BR-11: the compiled script and its targets, or the reason."""
    try:
        compiled = compile_script(script)
    except UnsupportedSieve as exc:
        return f"{exc.construct} at line {exc.line}"
    targets: dict[str, _Target] = {}
    for name in compiled.mailboxes:
        target = _resolve(name, mail)
        if target is None:
            return f"target '{name}' does not exist"
        targets[name.casefold()] = target
    return compiled, targets


def _date(seconds: int) -> str:
    try:
        return datetime.fromtimestamp(seconds, UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _entry(
    message: MailMessage, outcome: Outcome, targets: dict[str, _Target], mail: _Mail
) -> Entry | None:
    """BR-12 to BR-14: the entry when an action would change the message."""
    folder_id, location = _location(message, mail)
    actions: list[str] = []
    changes = False
    for name in outcome.files:
        target = targets[name.casefold()]
        actions.append(
            f"{'move' if target.kind == 'folder' else 'label'}: {target.name}"
        )
        if target.kind == "folder":
            changes |= target.id != folder_id
        else:
            changes |= target.id not in message.labels
    if "\\seen" in outcome.flags:
        actions.append("read")
        changes |= message.unread
    if "\\flagged" in outcome.flags:
        actions.append("star")
        changes |= _STARRED not in message.labels
    if outcome.expire_days is not None:
        actions.append(f"expire {outcome.expire_days} day")
    if not changes:
        return None
    sender, when = message.from_address, _date(message.time)
    return Entry(message.id, when, sender, message.subject, location, tuple(actions))


def _build(mail: _Mail, live: Filter, differs: bool) -> RetroPreview:
    """BR-4 to BR-15 for one filter over one mailbox read."""
    prepared = _prepare(live.raw_sieve, mail)
    if isinstance(prepared, str):
        return RetroPreview(live.name, False, prepared, False, (), 0, differs)
    compiled, targets = prepared
    found = {key: mail.recipients(key) for key in compiled.recipient_keys}
    spam = 0
    listed: list[tuple[int, str, Entry]] = []
    for message in mail.messages:
        if _SPAM in message.labels:
            spam += 1
            continue
        keys = frozenset(key for key, ids in found.items() if message.id in ids)
        keyed = replace(message, to_keys=keys)
        entry = _entry(keyed, evaluate(compiled, keyed), targets, mail)
        if entry is not None:
            listed.append((message.time, message.id, entry))
    listed.sort(key=lambda item: (-item[0], item[1]))
    entries = tuple(item[2] for item in listed)
    return RetroPreview(live.name, True, None, bool(found), entries, spam, differs)


def _live_filter(client: ProtonClient, name: str) -> Filter:
    """BR-2: the enabled live filter called `name`."""
    found = next((f for f in discover(client).filters if f.name == name), None)
    if found is None:
        raise ValidationError(f"no live filter named {name!r}")
    if not found.enabled:
        raise ValidationError(f"filter {name!r} is disabled; enable it first")
    return found


def _declared_differs(paths: AccountPaths, live: Filter) -> bool:
    """BR-15: the declared filter of that name differs from live."""
    loaded, _ = load_local(paths)
    want = next((f for f in loaded.values() if f.name == live.name), None)
    return want is not None and (
        normalize_whitespace(want.raw_sieve) != normalize_whitespace(live.raw_sieve)
        or want.enabled != live.enabled
    )


def _preview(
    paths: AccountPaths, client: ProtonClient, name: str
) -> tuple[RetroPreview, Filter]:
    check_client(paths, client)
    live = _live_filter(client, name)
    differs = _declared_differs(paths, live)
    return _build(_read_mail(client), live, differs), live


def preview(paths: AccountPaths, client: ProtonClient, name: str) -> RetroPreview:
    """Read-only preview of what `filters apply` would change. BR-1 to BR-16."""
    return _preview(paths, client, name)[0]


def _save_snapshot(
    paths: AccountPaths, client: ProtonClient, live: Filter, shown: RetroPreview
) -> Path:
    """BR-20, BR-21: the preview's message ids, owner-only, before the run."""
    now = datetime.now(UTC)
    script = normalize_whitespace(live.raw_sieve).encode()
    document: dict[str, Any] = {
        "format": _FORMAT,
        "created": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "account": paths.account,
        "fingerprint": client.fingerprint,
        "filter": live.name,
        "script_sha256": hashlib.sha256(script).hexdigest(),
        "messages": sorted(entry.message_id for entry in shown.entries),
    }
    document["checksum"] = checksum(document)
    path = paths.retroactive_dir / now.strftime(SNAPSHOT_TIME)
    create_exclusive(path, json.dumps(document, indent=2) + "\n")
    return path


def _prune(paths: AccountPaths, newest: Path) -> str | None:
    """BR-24: delete snapshots over 10 days old; the error text, if any."""
    files = snapshot_candidates(paths.retroactive_dir)
    now = datetime.now(UTC)
    doomed = [n for n, t in files if now - t > _RETENTION and n != newest.name]
    removed, error = 0, None
    for name in doomed:
        target = paths.retroactive_dir / name
        try:
            target.unlink()
        except OSError as exc:
            error = f"cannot remove {target}: {exc.strerror or exc}"
            break
        removed += 1
    if removed:
        counts = {"removed": removed, "kept": len(files) - removed}
        try:
            record_write(paths.audit_log, "prune", counts)
        except SieveAsCodeError as exc:
            error = error or str(exc)
    return error


def _audit_run(
    paths: AccountPaths, report: RetroReport, reason: str, error: ClientError | None
) -> RetroReport:
    """BR-23: one `write` line; a failing write is kept with the report."""
    detail: dict[str, str | int | None] = {
        "command": _COMMAND,
        "name": report.preview.filter,
        "reason": reason,
        "messages": len(report.preview.entries) if report.preview.previewable else None,
    }
    if error is not None:
        detail["exit_code"] = error.exit_code
    outcome = "started" if report.started else "failed"
    try:
        record_write(paths.audit_log, outcome, detail)
    except SieveAsCodeError as exc:
        return replace(report, audit_error=str(exc))
    return report


def run(
    paths: AccountPaths,
    client: ProtonClient,
    name: str,
    confirmed_name: str,
    reason: str,
) -> RetroReport:
    """Start `filters apply` behind a typed confirmation. BR-17 to BR-25."""
    shown, live = _preview(paths, client, name)
    if shown.previewable and not shown.entries:
        return RetroReport(shown)
    if confirmed_name != name or not reason.strip():
        record_check(paths.audit_log, "refused", {"command": _COMMAND, "name": name})
        return RetroReport(shown, refused=True)
    snapshot = _save_snapshot(paths, client, live, shown) if shown.previewable else None
    error: ClientError | None = None
    try:
        client.apply_retroactively(live.live_id or "")
    except ClientError as exc:
        error = exc
    report = RetroReport(
        shown,
        started=error is None,
        snapshot=snapshot,
        failed=str(error) if error else None,
    )
    report = _audit_run(paths, report, reason, error)
    if snapshot is not None:
        report = replace(report, prune_error=_prune(paths, snapshot))
    return report


@dataclass(frozen=True)
class _Stored:
    path: Path
    filter: str
    script_sha256: str
    messages: frozenset[str]


def _snapshot_path(ref: str | Path | None, directory: Path) -> Path:
    """BR-26: latest, an existing file, or a name in the retroactive directory."""
    if ref is None:
        found = sorted(directory.glob("*.json")) if directory.is_dir() else []
        if not found:
            raise BackupError(f"no retroactive snapshots in {directory}")
        return found[-1]
    if Path(ref).is_file():
        return Path(ref)
    name = str(ref) if str(ref).endswith(".json") else f"{ref}.json"
    if not (directory / name).is_file():
        raise BackupError(f"no retroactive snapshot {ref} in {directory}")
    return directory / name


def _read_snapshot(
    ref: str | Path | None, paths: AccountPaths, fingerprint: str
) -> _Stored:
    """BR-26: resolve and verify a snapshot as Unit 5 BR-10 does."""
    path = _snapshot_path(ref, paths.retroactive_dir)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else "not valid JSON"
        raise BackupError(f"cannot read {path}: {reason or exc}") from None
    if not isinstance(document, dict):
        raise BackupError(f"{path}: not a snapshot")
    if document.get("format") != _FORMAT:
        raise BackupError(f"{path}: unsupported snapshot format")
    if set(document) != _KEYS:
        raise BackupError(f"{path}: unexpected or missing fields")
    if document["checksum"] != checksum(document):
        raise BackupError(f"{path}: checksum mismatch; the file was altered or damaged")
    ids = document["messages"]
    texts = [document["filter"], document["script_sha256"], document["fingerprint"]]
    if not (
        all(isinstance(text, str) for text in texts)
        and isinstance(ids, list)
        and all(isinstance(item, str) for item in ids)
    ):
        raise BackupError(f"{path}: fields have the wrong type")
    if document["fingerprint"] != fingerprint:
        raise BackupError(f"{path}: belongs to a different Proton account")
    return _Stored(path, texts[0], texts[1], frozenset(ids))


def status(
    paths: AccountPaths, client: ProtonClient, ref: str | Path | None = None
) -> RetroStatus:
    """Compare the current preview with a snapshot. BR-26, BR-27."""
    check_client(paths, client)
    stored = _read_snapshot(ref, paths, client.fingerprint)
    live = _live_filter(client, stored.filter)
    mail = _read_mail(client)
    current = _build(mail, live, False)
    if not current.previewable:
        raise ValidationError(
            f"filter {stored.filter!r} is not previewable: {current.reason}"
        )
    listed = {message.id for message in mail.messages}
    pending = tuple(e for e in current.entries if e.message_id in stored.messages)
    fresh = {e.message_id for e in current.entries} - stored.messages
    gone = stored.messages - listed
    done = len(stored.messages & listed) - len(pending)
    unexpected = tuple(Unexpected(item, "gone") for item in sorted(gone)) + tuple(
        Unexpected(item, "new") for item in sorted(fresh)
    )
    changed = hashlib.sha256(normalize_whitespace(live.raw_sieve).encode()).hexdigest()
    return RetroStatus(
        stored.filter,
        stored.path,
        done,
        pending,
        unexpected,
        changed != stored.script_sha256,
    )


def _row(shown: RetroPreview) -> AuditRow:
    if not shown.previewable:
        return AuditRow(shown.filter, None, f"not previewable: {shown.reason}")
    note = "approximate: recipient search" if shown.approximate else None
    return AuditRow(shown.filter, len(shown.entries), note)


def audit_all(paths: AccountPaths, client: ProtonClient) -> RetroAudit:
    """How many existing messages a run of each enabled filter would change. BR-28."""
    check_client(paths, client)
    enabled = [f for f in discover(client).filters if f.enabled]
    mail = _read_mail(client) if enabled else None
    rows = tuple(_row(_build(mail, f, False)) for f in enabled) if mail else ()
    detail = {
        "filters": len(rows),
        "not_previewable": sum(row.changes is None for row in rows),
        "approximate": sum(row.note == "approximate: recipient search" for row in rows),
    }
    record_check(paths.audit_log, "audited", detail)
    return RetroAudit(rows)
