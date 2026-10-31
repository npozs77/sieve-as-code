"""Unit 4 BR-1, BR-2, BR-10, BR-16: reading live state."""

import pytest

from sieve_as_code.client import ProtonClient, connect
from sieve_as_code.live import discover, discover_targets
from sieve_as_code.model import ClientError
from sieve_as_code.settings import AccountPaths
from tests.fake_proton import FakeProton

READ_ONLY = {
    ("account", "get"),
    ("mail", "settings", "filters", "list"),
    ("mail", "settings", "filters", "get"),
    ("mail", "settings", "folders", "list"),
    ("mail", "settings", "labels", "list"),
    ("--version",),
}


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def test_discover_returns_filters_in_live_order_with_ids(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    first = fake_proton.add_filter("b", "stop;")
    second = fake_proton.add_filter("a", "keep;", status=0)
    state = discover(client)
    assert [(f.name, f.raw_sieve, f.enabled, f.live_id) for f in state.filters] == [
        ("b", "stop;", True, first),
        ("a", "keep;", False, second),
    ]
    assert state.order.sequence == ("b", "a")


def test_discover_of_an_empty_account_is_empty(client: ProtonClient) -> None:
    state = discover(client)
    assert state.filters == () and state.order.sequence == ()


def test_discover_and_targets_make_read_only_calls_only(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.add_filter("a")
    discover(client)
    discover_targets(client)
    assert {call.path for call in fake_proton.calls} <= READ_ONLY


def test_duplicate_live_names_are_an_error_not_collapsed(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.add_filter("dup")
    fake_proton.add_filter("other")
    fake_proton.add_filter("dup")
    with pytest.raises(ClientError, match="'dup'"):
        discover(client)


def test_targets_hold_name_and_path_of_folders_and_labels(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.folders.append({"id": "t1", "name": "Child", "path": "Parent/Child"})
    fake_proton.labels.append({"id": "t2", "name": "Receipts", "path": "Receipts"})
    assert discover_targets(client) == {"Child", "Parent/Child", "Receipts"}
