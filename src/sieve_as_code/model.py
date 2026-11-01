"""Filter data types and the package's base errors."""

from dataclasses import dataclass


class SieveAsCodeError(Exception):
    """Base class for every error this package raises on purpose."""


class ValidationError(SieveAsCodeError):
    """Bad declared input, account name or configuration (CLI exit code 2)."""


class ClientError(SieveAsCodeError):
    """`proton` could not be run, refused a command, or answered unexpectedly.

    `exit_code` is the process exit code, or None when no process answered.
    """

    def __init__(self, message: str, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


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


@dataclass(frozen=True)
class Rename:
    """A live filter shown under a numbered name because another shares its name."""

    original: str
    name: str


@dataclass(frozen=True)
class Targets:
    """Existing mailboxes: folder paths and label names. Unit 4 BR-10."""

    folders: frozenset[str] = frozenset()
    labels: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FilterSet:
    """Filters in execution order with their order: declared, live or snapshot state.

    `renames` is non-empty only for live state with duplicate names.
    """

    filters: tuple[Filter, ...]
    order: FilterOrder
    renames: tuple[Rename, ...] = ()
