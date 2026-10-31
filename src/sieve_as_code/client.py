"""The only module that runs `proton`: checks, one method per operation."""

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sieve_as_code.model import ClientError, Filter
from sieve_as_code.settings import AccountPaths, proton_cli

TESTED_MINIMUM = (4, 3, 0)  # NFR-REL.3
_TIMEOUT_SECONDS = 30
_MESSAGES_TIMEOUT_SECONDS = 120
_STDERR_LIMIT = 200
_SETTINGS = ("mail", "settings")
_FILTERS = _SETTINGS + ("filters",)

_HINTS = {
    1: "the command line was wrong; see `proton --help`",
    3: "no such thing",
    4: "the reference matched several things; use the id a listing printed",
    5: "Proton or the network is having trouble; check with a list before "
    "repeating a change",
    6: "a confirmation policy refuses this command",
    7: "a bug in proton; `proton report` collects what an issue needs",
}


@dataclass(frozen=True)
class FilterRef:
    """A filter as `list` reports it: no Sieve content."""

    live_id: str
    name: str
    enabled: bool


@dataclass(frozen=True)
class MailTarget:
    """A folder or label; `path` is its full path, `name` if the listing has none."""

    id: str
    name: str
    path: str


def _text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


def _enabled(entry: Mapping[str, Any]) -> bool:
    """BR-14: status 0 is disabled."""
    status = entry.get("status", 1)
    if not isinstance(status, int):
        raise ValueError("status")
    return status != 0


def _rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    """BR-13: a listing must be complete."""
    rows = payload.get(key)
    if (
        not isinstance(rows, list)
        or not all(isinstance(row, dict) for row in rows)
        or payload.get("has_more")
    ):
        raise ValueError(key)
    return rows


def _filter_ref(row: Mapping[str, Any]) -> FilterRef:
    return FilterRef(_text(row, "id"), _text(row, "name"), _enabled(row))


def _filter(payload: Mapping[str, Any]) -> Filter:
    sieve = payload.get("sieve")
    if not isinstance(sieve, str):
        raise ValueError("sieve")
    return Filter(
        name=_text(payload, "name"),
        raw_sieve=sieve,
        enabled=_enabled(payload),
        live_id=_text(payload, "id"),
    )


def _target(row: Mapping[str, Any]) -> MailTarget:
    name = _text(row, "name")
    path = row.get("path")
    return MailTarget(
        _text(row, "id"), name, path if isinstance(path, str) and path else name
    )


def _created_id(payload: Mapping[str, Any]) -> str:
    ids = payload.get("ids")
    if (
        not isinstance(ids, list)
        or not ids
        or not isinstance(ids[0], str)
        or not ids[0]
    ):
        raise ValueError("ids")
    return ids[0]


def _spawn(
    argv: Sequence[str], stdin: str | None, timeout: int
) -> subprocess.CompletedProcess[str]:
    """BR-12: run one process; a missing binary or a timeout is a ClientError."""
    try:
        return subprocess.run(
            list(argv),
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise ClientError(
            f"cannot find `{argv[0]}`; set SIEVE_AS_CODE_PROTON_CLI to the "
            "proton binary"
        ) from None
    except subprocess.TimeoutExpired:
        raise ClientError(f"`{argv[0]}` gave no answer within {timeout}s") from None
    except OSError as exc:
        raise ClientError(f"cannot run `{argv[0]}`: {exc.strerror or exc}") from None


def _check_version(binary: str) -> None:
    """BR-8: warn, never fail, on an old or unreadable version."""
    result = _spawn([binary, "--version"], None, _TIMEOUT_SECONDS)
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
    tested = ".".join(map(str, TESTED_MINIMUM))
    if result.returncode != 0 or found is None:
        print(
            f"warning: cannot read the proton version; tested with {tested}+",
            file=sys.stderr,
        )
        return
    detected = tuple(int(part) for part in found.groups())
    if detected < TESTED_MINIMUM:
        print(
            f"warning: proton {'.'.join(found.groups())} is older than the tested "
            f"{tested}; continuing",
            file=sys.stderr,
        )


def fingerprint_of(account_id: str) -> str:
    """First 12 hex characters of the SHA-256 of the Proton account id. BR-9."""
    return hashlib.sha256(account_id.encode()).hexdigest()[:12]


def _check_marker(marker: Path, account: str, fingerprint: str) -> None:
    """BR-9: create the marker on first use, refuse a different fingerprint."""
    try:
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            stored = marker.read_text().strip()
        else:
            with os.fdopen(descriptor, "w") as handle:
                handle.write(fingerprint + "\n")
            return
    except OSError as exc:
        raise ClientError(f"cannot use {marker}: {exc.strerror or exc}") from None
    if stored != fingerprint:
        raise ClientError(
            f"profile '{account}' now belongs to a different Proton account "
            f"(fingerprint {fingerprint}, recorded {stored or 'none'} in {marker}); "
            "delete that file only if you mean to adopt the new account"
        )


@dataclass(frozen=True)
class ProtonClient:
    """One account's `proton` operations. Obtain one with `connect`."""

    binary: str
    account: str
    fingerprint: str = ""

    def _run(
        self,
        path: tuple[str, ...],
        *args: str,
        stdin: str | None = None,
        timeout: int = _TIMEOUT_SECONDS,
    ) -> str:
        """BR-1, BR-5, BR-10: one process; a failure becomes a ClientError."""
        argv = [
            self.binary,
            "--profile",
            self.account,
            "--no-input",
            "--output",
            "json",
        ]
        result = _spawn([*argv, *path, *args], stdin, timeout)
        if result.returncode == 0:
            return result.stdout
        command = " ".join(path)
        if result.returncode == 2:
            hint = (
                f"not signed in or refused; sign in with "
                f"`{self.binary} --profile {self.account} account login`"
            )
        else:
            hint = _HINTS.get(result.returncode, "unexpected failure")
        lines = result.stderr.strip().splitlines()
        reason = f": {lines[0][:_STDERR_LIMIT]}" if lines else ""
        raise ClientError(
            f"`proton {command}` failed (exit {result.returncode}): {hint}{reason}",
            result.returncode,
        )

    def _read[T](
        self, path: tuple[str, ...], build: Callable[[Mapping[str, Any]], T], *args: str
    ) -> T:
        """Run a command and build its result from the JSON object it prints. BR-11."""
        stdout = self._run(path, *args, timeout=self._timeout(path))
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                raise ValueError("not an object")
            return build(payload)
        except ValueError:
            raise ClientError(
                f"unexpected proton output for `{' '.join(path)}`"
            ) from None

    @staticmethod
    def _timeout(path: tuple[str, ...]) -> int:
        return (
            _MESSAGES_TIMEOUT_SECONDS
            if path[-2:] == ("messages", "list")
            else _TIMEOUT_SECONDS
        )

    def list_filters(self) -> list[FilterRef]:
        """All filters in execution order, without Sieve content. BR-13, BR-14."""
        return self._read(
            _FILTERS + ("list",),
            lambda p: [_filter_ref(row) for row in _rows(p, "filters")],
            "--limit",
            "0",
        )

    def get_filter(self, live_id: str) -> Filter:
        """One filter with its Sieve script. BR-15."""
        return self._read(_FILTERS + ("get",), _filter, live_id)

    def create_filter(self, name: str, raw_sieve: str, enabled: bool = True) -> str:
        """Create a filter and return its id; the script goes via stdin. BR-2, BR-16."""
        path = _FILTERS + ("create",)
        args = ["--name", name, "--sieve", "-", *([] if enabled else ["--disabled"])]
        stdout = self._run(path, *args, stdin=raw_sieve)
        try:
            return _created_id(json.loads(stdout))
        except (ValueError, AttributeError):
            raise ClientError(
                "unexpected proton output for `mail settings filters create`"
            ) from None

    def update_filter(self, live_id: str, raw_sieve: str) -> None:
        """Replace a filter's script; it goes via stdin. BR-2."""
        self._run(_FILTERS + ("update",), live_id, "--sieve", "-", stdin=raw_sieve)

    def delete_filter(self, live_id: str) -> None:
        """Delete a filter; the caller owns the confirmation. BR-17."""
        self._run(_FILTERS + ("delete",), live_id, "--yes")

    def enable_filter(self, live_id: str) -> None:
        """Enable a filter."""
        self._run(_FILTERS + ("enable",), live_id)

    def disable_filter(self, live_id: str) -> None:
        """Disable a filter."""
        self._run(_FILTERS + ("disable",), live_id)

    def reorder_filters(self, live_ids: Sequence[str]) -> None:
        """Run the named filters first, in this order, in one call. BR-18."""
        if not live_ids:
            raise ValueError("reorder_filters needs at least one filter id")
        self._run(_FILTERS + ("reorder",), *live_ids)

    def list_folders(self) -> list[MailTarget]:
        """All folders. BR-19."""
        return self._read(
            _SETTINGS + ("folders", "list"),
            lambda p: [_target(row) for row in _rows(p, "folders")],
            "--limit",
            "0",
        )

    def list_labels(self) -> list[MailTarget]:
        """All labels. BR-19."""
        return self._read(
            _SETTINGS + ("labels", "list"),
            lambda p: [_target(row) for row in _rows(p, "labels")],
            "--limit",
            "0",
        )

    def create_label(self, name: str) -> None:
        """Create a label. BR-19."""
        self._run(_SETTINGS + ("labels", "create"), "--name", name)

    def create_folder(self, name: str, parent_id: str | None = None) -> None:
        """Create a folder, inside `parent_id` when given. BR-19."""
        parent = [] if parent_id is None else ["--parent", parent_id]
        self._run(_SETTINGS + ("folders", "create"), "--name", name, *parent)

    def list_messages(self, to: str | None = None) -> list[dict[str, Any]]:
        """Messages in every folder, optionally only those to an address. BR-20."""
        recipient = [] if to is None else ["--to", to]
        return self._read(
            ("mail", "messages", "list"),
            lambda p: [dict(row) for row in _rows(p, "messages")],
            "--folder",
            "all",
            "--limit",
            "0",
            *recipient,
        )

    def apply_retroactively(self, live_id: str) -> None:
        """Start `filters apply` for one filter and return; nothing is polled. BR-21."""
        self._run(_FILTERS + ("apply",), live_id)


def connect(paths: AccountPaths) -> ProtonClient:
    """Check version, session and account, then return the client. BR-6 to BR-9."""
    binary = proton_cli()
    _check_version(binary)
    client = ProtonClient(binary, paths.account)
    account_id = client._read(("account", "get"), lambda p: _text(p, "id"))
    fingerprint = fingerprint_of(account_id)
    _check_marker(paths.account_marker, paths.account, fingerprint)
    return replace(client, fingerprint=fingerprint)
