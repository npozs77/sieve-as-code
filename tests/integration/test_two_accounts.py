"""Two real Proton accounts: isolation (read-only) and a write round trip.

Run with `make integration`. The write test needs SIEVE_AS_CODE_IT_WRITE=1 and
changes only the second account, which must have no filters.
"""

import os
import shutil
import uuid

import pytest

from sieve_as_code._apply import apply_plan
from sieve_as_code._backup import write_backup
from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._model import ClientError
from sieve_as_code._plan import plan
from sieve_as_code._restore import restore
from sieve_as_code._settings import AccountPaths
from tests.integration.conftest import WRITE_VARIABLE

Pair = tuple[AccountPaths, AccountPaths]


def _names(client: ProtonClient) -> list[tuple[str, str, bool]]:
    return [(f.live_id, f.name, f.enabled) for f in client.list_filters()]


def test_accounts_have_distinct_identities(two_accounts: Pair) -> None:
    first, second = (connect(paths) for paths in two_accounts)

    assert first.fingerprint and second.fingerprint
    assert first.fingerprint != second.fingerprint


def test_account_files_are_separate(two_accounts: Pair) -> None:
    first, second = two_accounts
    for paths in two_accounts:
        connect(paths)

    assert first.account_marker.read_text() != second.account_marker.read_text()
    directories = [
        (p.filters_dir, p.backups_dir, p.retroactive_dir, p.audit_log)
        for p in two_accounts
    ]
    assert set(directories[0]).isdisjoint(directories[1])


def test_marker_of_other_account_is_refused(two_accounts: Pair) -> None:
    first, second = two_accounts
    connect(first)
    connect(second)
    shutil.copy(second.account_marker, first.account_marker)

    with pytest.raises(ClientError, match="different Proton account"):
        connect(first)


@pytest.mark.skipif(
    os.environ.get(WRITE_VARIABLE) != "1",
    reason=f"set {WRITE_VARIABLE}=1 to write to the second account",
)
def test_apply_and_restore_touch_only_the_second_account(two_accounts: Pair) -> None:
    first_paths, second_paths = two_accounts
    first, second = connect(first_paths), connect(second_paths)
    if second.list_filters():
        pytest.skip("the second account must have no filters")
    first_before = _names(first)
    name = f"sac-it-{uuid.uuid4().hex[:8]}"
    second_paths.filters_dir.mkdir(parents=True)
    # Disabled and unmatchable: it can never act on real mail.
    (second_paths.filters_dir / f"{name}.yaml").write_text(
        f"name: {name}\nenabled: false\nraw_sieve: |-\n"
        f'  if header :is "subject" "{name}" {{ keep; }}\n'
    )
    second_paths.order_file.write_text(f"sequence:\n  - {name}\n")
    try:
        assert plan(second_paths, second).outcome == "drift"
        applied = apply_plan(second_paths, second, confirmed=True, allow_delete=False)
        assert applied.ok and applied.snapshot is not None
        assert plan(second_paths, second).outcome == "clean"
        assert write_backup(second_paths, second).state.filters

        restored = restore(applied.snapshot.path, second_paths, second, True)
        assert restored.ok
        assert second.list_filters() == []
        assert _names(first) == first_before
    finally:
        for live in second.list_filters():
            if live.name == name:
                second.delete_filter(live.live_id)
