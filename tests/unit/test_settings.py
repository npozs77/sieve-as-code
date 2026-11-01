"""BR-1 to BR-7, BR-14: account resolution and per-account paths."""

import os
import re
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sieve_as_code.model import ValidationError
from sieve_as_code.settings import (
    AccountPaths,
    account_paths,
    proton_cli,
    resolve_account,
)


@pytest.fixture(autouse=True)
def clean_env(tmp_path: Path) -> Iterator[None]:
    """Empty environment with HOME inside tmp_path."""
    with mock.patch.dict(os.environ, {"HOME": str(tmp_path)}, clear=True):
        yield


def is_invalid(name: str) -> bool:
    return (
        name == ""
        or any(c in name for c in ("/", "\\", "\0"))
        or ".." in name
        or name.startswith(".")
    )


def all_paths(paths: AccountPaths) -> list[Path]:
    return [
        paths.filters_dir,
        paths.order_file,
        paths.account_marker,
        paths.backups_dir,
        paths.retroactive_dir,
        paths.audit_log,
    ]


# BR-1
def test_account_defaults_to_default() -> None:
    assert resolve_account() == "default"


def test_account_env_beats_default() -> None:
    os.environ["SIEVE_AS_CODE_ACCOUNT"] = "home"
    assert resolve_account() == "home"


def test_account_argument_beats_env() -> None:
    os.environ["SIEVE_AS_CODE_ACCOUNT"] = "home"
    assert resolve_account("work") == "work"


# BR-2
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_env_counts_as_unset(blank: str) -> None:
    os.environ["SIEVE_AS_CODE_ACCOUNT"] = blank
    os.environ["SIEVE_AS_CODE_PROTON_CLI"] = blank
    assert resolve_account() == "default"
    assert proton_cli() == "proton"


def test_env_value_is_stripped() -> None:
    os.environ["SIEVE_AS_CODE_ACCOUNT"] = "  work \n"
    assert resolve_account() == "work"


# BR-3
@pytest.mark.parametrize("name", ["", ".", "..", ".a", "a..b", "a/b", "a\\b", "a\0b"])
def test_invalid_account_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        resolve_account(name)
    with pytest.raises(ValidationError):
        account_paths(name)


@pytest.mark.parametrize("name", ["a", "a.", "a.b", "work-2", "Ünï", "a b"])
def test_valid_account_names_are_accepted(name: str) -> None:
    assert resolve_account(name) == name
    assert account_paths(name).account == name


@given(st.text())
def test_account_name_validity_matches_rule(name: str) -> None:
    if is_invalid(name):
        with pytest.raises(ValidationError):
            resolve_account(name)
    else:
        assert resolve_account(name) == name


def test_invalid_env_account_is_rejected() -> None:
    os.environ["SIEVE_AS_CODE_ACCOUNT"] = "../x"
    with pytest.raises(ValidationError):
        resolve_account()


# BR-4, BR-5
def test_roots_default_to_home_xdg_locations(tmp_path: Path) -> None:
    paths = account_paths("work")
    config = tmp_path / ".config" / "sieve-as-code" / "work"
    state = tmp_path / ".local" / "state" / "sieve-as-code" / "work"
    assert paths.filters_dir == config / "filters"
    assert paths.order_file == config / "order.yaml"
    assert paths.account_marker == config / "account.id"
    assert paths.backups_dir == state / "backups"
    assert paths.retroactive_dir == state / "retroactive"
    assert paths.audit_log == state / "audit.log"


def test_absolute_xdg_values_beat_home_default(tmp_path: Path) -> None:
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    os.environ["XDG_STATE_HOME"] = str(tmp_path / "st")
    paths = account_paths("work")
    assert paths.order_file == tmp_path / "cfg" / "sieve-as-code" / "work/order.yaml"
    assert paths.audit_log == tmp_path / "st" / "sieve-as-code" / "work/audit.log"


def test_variables_beat_xdg(tmp_path: Path) -> None:
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    os.environ["XDG_STATE_HOME"] = str(tmp_path / "st")
    os.environ["SIEVE_AS_CODE_FILTERS_DIR"] = str(tmp_path / "f")
    os.environ["SIEVE_AS_CODE_STATE_DIR"] = str(tmp_path / "s")
    paths = account_paths("work")
    assert paths.order_file == tmp_path / "f" / "work" / "order.yaml"
    assert paths.audit_log == tmp_path / "s" / "work" / "audit.log"


def test_relative_xdg_values_are_ignored(tmp_path: Path) -> None:
    os.environ["XDG_CONFIG_HOME"] = "rel/path"
    os.environ["XDG_STATE_HOME"] = "rel/state"
    paths = account_paths("work")
    assert paths.order_file.is_relative_to(tmp_path / ".config" / "sieve-as-code")
    assert paths.audit_log.is_relative_to(tmp_path / ".local" / "state")


def test_tilde_in_variable_is_expanded(tmp_path: Path) -> None:
    os.environ["SIEVE_AS_CODE_FILTERS_DIR"] = "~/sieve"
    assert account_paths("work").order_file == tmp_path / "sieve/work/order.yaml"


@pytest.mark.parametrize(
    ("variable", "other"),
    [
        ("SIEVE_AS_CODE_FILTERS_DIR", "SIEVE_AS_CODE_STATE_DIR"),
        ("SIEVE_AS_CODE_STATE_DIR", "SIEVE_AS_CODE_FILTERS_DIR"),
    ],
)
def test_missing_home_names_the_variable(variable: str, other: str) -> None:
    os.environ[other] = "/set/explicitly"
    with (
        mock.patch("pathlib.Path.home", side_effect=RuntimeError("no home")),
        pytest.raises(ValidationError, match=variable),
    ):
        account_paths("work")


def test_resolving_paths_creates_nothing(tmp_path: Path) -> None:
    account_paths("work")
    assert list(tmp_path.iterdir()) == []


# BR-6
@given(st.text(min_size=1), st.text(min_size=1))
def test_distinct_accounts_never_share_or_nest_paths(a: str, b: str) -> None:
    if a == b or is_invalid(a) or is_invalid(b):
        return
    with mock.patch.dict(
        os.environ,
        {
            "SIEVE_AS_CODE_FILTERS_DIR": "/r/f",
            "SIEVE_AS_CODE_STATE_DIR": "/r/s",
        },
        clear=True,
    ):
        paths_a = all_paths(account_paths(a))
        paths_b = all_paths(account_paths(b))
    for x in paths_a:
        for y in paths_b:
            assert x != y
            assert not x.is_relative_to(y)
            assert not y.is_relative_to(x)


# BR-7
def test_proton_cli_default_and_override() -> None:
    assert proton_cli() == "proton"
    os.environ["SIEVE_AS_CODE_PROTON_CLI"] = "/opt/proton"
    assert proton_cli() == "/opt/proton"


# BR-14
def test_env_example_lists_exactly_the_four_variables() -> None:
    text = (Path(__file__).parents[2] / ".env.example").read_text()
    keys = set(re.findall(r"^(SIEVE_AS_CODE_[A-Z_]+)=", text, re.MULTILINE))
    assert keys == {
        "SIEVE_AS_CODE_FILTERS_DIR",
        "SIEVE_AS_CODE_STATE_DIR",
        "SIEVE_AS_CODE_ACCOUNT",
        "SIEVE_AS_CODE_PROTON_CLI",
    }
