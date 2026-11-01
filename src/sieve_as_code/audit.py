"""Append-only JSONL audit log; names and counts only (NFR-SAFE.2)."""

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from sieve_as_code.model import SieveAsCodeError

Scalar = str | int | bool | None


def _append(
    audit_log: Path, kind: str, outcome: str, detail: Mapping[str, Scalar]
) -> None:
    """BR-9 to BR-12: validate, then append exactly one line."""
    if not isinstance(outcome, str) or not outcome.strip():
        raise ValueError("audit outcome must be a non-blank string")
    for key, value in detail.items():
        if not isinstance(key, str) or not isinstance(value, str | int | None):
            raise ValueError(f"audit detail {key!r} must be a str, int, bool or None")
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    record = {
        "ts": timestamp.replace("+00:00", "Z"),
        "kind": kind,
        "outcome": outcome,
        "detail": dict(detail),
    }
    line = (json.dumps(record) + "\n").encode()
    try:
        audit_log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(audit_log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError as exc:
        raise SieveAsCodeError(
            f"cannot write audit log {audit_log}: {exc.strerror or exc}"
        ) from exc


def record_write(audit_log: Path, outcome: str, detail: Mapping[str, Scalar]) -> None:
    """Append a `write` record (a change made to Proton). FR-APPLY.6."""
    _append(audit_log, "write", outcome, detail)


def record_check(audit_log: Path, outcome: str, detail: Mapping[str, Scalar]) -> None:
    """Append a `check` record (a read-only run or refusal). FR-PLAN.4."""
    _append(audit_log, "check", outcome, detail)
