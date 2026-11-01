"""Environment variables and account name to per-account paths."""

import os
from dataclasses import dataclass
from pathlib import Path

from sieve_as_code.model import ValidationError

_APP_DIR = "sieve-as-code"
_DEFAULT_ACCOUNT = "default"
_DEFAULT_PROTON_CLI = "proton"


@dataclass(frozen=True)
class AccountPaths:
    """Every file location of one account. BR-5."""

    account: str
    filters_dir: Path
    order_file: Path
    account_marker: Path
    backups_dir: Path
    retroactive_dir: Path
    audit_log: Path


def _env(name: str) -> str | None:
    """BR-2: unset, empty and whitespace-only are all None."""
    value = os.environ.get(name, "").strip()
    return value or None


def _validate_account(name: str) -> str:
    """BR-3: reject names that could escape or hide the account directory."""
    bad = (
        not name
        or any(char in name for char in ("/", "\\", "\0"))
        or ".." in name
        or name.startswith(".")
    )
    if bad:
        raise ValidationError(
            f"invalid account name {name!r}: it must be non-empty, contain no "
            "'/', '\\', NUL or '..', and not start with '.'"
        )
    return name


def resolve_account(name: str | None = None) -> str:
    """Return the validated account: argument, else env, else `default`. BR-1."""
    if name is None:
        name = _env("SIEVE_AS_CODE_ACCOUNT") or _DEFAULT_ACCOUNT
    return _validate_account(name)


def _root(variable: str, xdg_variable: str, home_subdir: str) -> Path:
    """BR-4: the variable, else an absolute XDG value, else the home default."""
    try:
        explicit = _env(variable)
        if explicit:
            return Path(explicit).expanduser()
        xdg = _env(xdg_variable)
        if xdg and Path(xdg).is_absolute():
            return Path(xdg) / _APP_DIR
        return Path.home() / home_subdir / _APP_DIR
    except RuntimeError as exc:
        raise ValidationError(
            f"cannot determine the home directory; set {variable}"
        ) from exc


def account_paths(account: str) -> AccountPaths:
    """Build one account's paths from the roots and the validated name. BR-5, BR-6."""
    name = _validate_account(account)
    filters_root = (
        _root("SIEVE_AS_CODE_FILTERS_DIR", "XDG_CONFIG_HOME", ".config") / name
    )
    state_root = (
        _root("SIEVE_AS_CODE_STATE_DIR", "XDG_STATE_HOME", ".local/state") / name
    )
    return AccountPaths(
        account=name,
        filters_dir=filters_root / "filters",
        order_file=filters_root / "order.yaml",
        account_marker=filters_root / "account.id",
        backups_dir=state_root / "backups",
        retroactive_dir=state_root / "retroactive",
        audit_log=state_root / "audit.log",
    )


def proton_cli() -> str:
    """Return the `proton-cli` binary name or path. BR-7."""
    return _env("SIEVE_AS_CODE_PROTON_CLI") or _DEFAULT_PROTON_CLI
