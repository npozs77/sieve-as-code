"""Opt-in live smoke suite: one real account, throwaway filters only (NFR-TEST.2)."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._model import ClientError
from sieve_as_code._settings import AccountPaths, account_paths

ENABLE_VARIABLE = "SIEVE_AS_CODE_LIVE_TEST"
PREFIX = "sieve-as-code-test-"


@dataclass(frozen=True)
class Live:
    """The account under test, with its paths rooted in a temp directory."""

    paths: AccountPaths
    client: ProtonClient


def scratch(suffix: str) -> str:
    """A throwaway filter name; the reserved prefix is what makes cleanup safe."""
    return PREFIX + suffix


def remove_scratch(client: ProtonClient) -> None:
    """BR-18: delete leftover throwaway filters, never one without the prefix."""
    for ref in client.list_filters():
        if ref.name.startswith(PREFIX):
            client.delete_filter(ref.live_id)


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """BR-18: skip unless enabled; refuse to start when filters cannot be listed."""
    if os.environ.get(ENABLE_VARIABLE) != "1":
        pytest.skip(f"set {ENABLE_VARIABLE}=1 to run against a real account")
    account = os.environ.get("SIEVE_AS_CODE_ACCOUNT", "").strip()
    if not account:
        pytest.fail("set SIEVE_AS_CODE_ACCOUNT to the profile to test", pytrace=False)
    monkeypatch.setenv("SIEVE_AS_CODE_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setenv("SIEVE_AS_CODE_STATE_DIR", str(tmp_path / "state"))
    paths = account_paths(account)
    client = connect(paths)
    try:
        client.list_filters()
    except ClientError as exc:
        pytest.fail(f"cannot list filters, refusing to start: {exc}", pytrace=False)
    try:
        yield Live(paths, client)
    finally:
        remove_scratch(client)


@pytest.fixture
def clean_account(live: Live) -> Live:
    """For tests whose command acts on the whole account (apply, reorder, restore)."""
    foreign = [
        r.name for r in live.client.list_filters() if not r.name.startswith(PREFIX)
    ]
    if foreign:
        pytest.skip("account has filters outside the test prefix; use an empty account")
    return live
