"""Shared fixtures."""

import subprocess
from pathlib import Path

import pytest

from sieve_as_code.settings import AccountPaths, account_paths
from tests.fake_proton import FakeProton


@pytest.fixture
def fake_proton(monkeypatch: pytest.MonkeyPatch) -> FakeProton:
    """Replace the subprocess boundary with an in-memory `proton`."""
    fake = FakeProton()
    monkeypatch.setattr(subprocess, "run", fake.run)
    return fake


@pytest.fixture
def work_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AccountPaths:
    """Paths of account `work`, rooted in tmp_path."""
    monkeypatch.setenv("SIEVE_AS_CODE_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setenv("SIEVE_AS_CODE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SIEVE_AS_CODE_PROTON_CLI", raising=False)
    return account_paths("work")
