"""Fixtures for the opt-in two-account integration tests against real Proton."""

import os
from pathlib import Path

import pytest

from sieve_as_code.settings import AccountPaths, account_paths

ACCOUNTS_VARIABLE = "SIEVE_AS_CODE_IT_ACCOUNTS"
WRITE_VARIABLE = "SIEVE_AS_CODE_IT_WRITE"


@pytest.fixture(scope="session")
def profiles() -> tuple[str, str]:
    """The two `proton` profile names from `SIEVE_AS_CODE_IT_ACCOUNTS=first,second`."""
    names = [n.strip() for n in os.environ.get(ACCOUNTS_VARIABLE, "").split(",")]
    if len(names) != 2 or not all(names) or names[0] == names[1]:
        pytest.skip(f"set {ACCOUNTS_VARIABLE}=<profile>,<other profile> to run")
    return names[0], names[1]


@pytest.fixture
def two_accounts(
    profiles: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AccountPaths, AccountPaths]:
    """Both accounts' paths, rooted in tmp_path so no real file is touched."""
    monkeypatch.setenv("SIEVE_AS_CODE_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setenv("SIEVE_AS_CODE_STATE_DIR", str(tmp_path / "state"))
    return account_paths(profiles[0]), account_paths(profiles[1])
