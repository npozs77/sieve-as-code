"""Filter data types and the package's base errors."""

from dataclasses import dataclass


class SieveAsCodeError(Exception):
    """Base class for every error this package raises on purpose."""


class ValidationError(SieveAsCodeError):
    """Bad declared input, account name or configuration (CLI exit code 2)."""


@dataclass(frozen=True)
class Filter:
    """One Proton filter; `live_id` is None for declared-only filters. BR-8."""

    name: str
    raw_sieve: str
    enabled: bool = True
    live_id: str | None = None


@dataclass(frozen=True)
class FilterOrder:
    """Filter names in execution order. BR-8."""

    sequence: tuple[str, ...]
