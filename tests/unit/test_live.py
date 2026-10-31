"""Unit 4 BR-1, BR-2, BR-10, BR-16: reading live state."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sieve_as_code.client import ProtonClient, connect
from sieve_as_code.live import _number_duplicates, discover, discover_targets
from sieve_as_code.model import Filter
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


def test_duplicate_live_names_are_numbered_and_reported(
    client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-2
    ids = [fake_proton.add_filter(n, f"stop; # {n}") for n in ("dup", "x", "dup")]
    state = discover(client)
    assert state.order.sequence == ("dup", "x", "dup (1)")
    assert [f.live_id for f in state.filters] == ids
    assert [(r.original, r.name) for r in state.renames] == [("dup", "dup (1)")]


def test_numbering_skips_a_number_a_real_filter_already_uses(
    client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-2
    for name in ("a", "a", "a (1)", "a"):
        fake_proton.add_filter(name)
    state = discover(client)
    assert state.order.sequence == ("a", "a (2)", "a (1)", "a (3)")
    assert [r.name for r in state.renames] == ["a (2)", "a (3)"]


def test_distinct_names_are_left_alone(
    client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-2
    fake_proton.add_filter("a")
    fake_proton.add_filter("b")
    assert discover(client).renames == ()


@given(st.lists(st.sampled_from(["a", "b", "a (1)", "b (2)", "c"]), max_size=8))
def test_numbered_names_are_unique_and_first_occurrences_keep_theirs(
    names: list[str],
) -> None:  # BR-2
    filters = tuple(Filter(n, "keep;", True, f"id{i}") for i, n in enumerate(names))
    numbered, renames = _number_duplicates(filters)
    result = [f.name for f in numbered]
    assert len(set(result)) == len(result)
    assert [f.live_id for f in numbered] == [f.live_id for f in filters]
    firsts = {n: i for i, n in reversed(list(enumerate(names)))}
    assert all(result[i] == n for n, i in firsts.items())
    assert len(renames) == sum(a != b for a, b in zip(names, result, strict=True))


def test_targets_hold_name_and_path_of_folders_and_labels(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.folders.append({"id": "t1", "name": "Child", "path": "Parent/Child"})
    fake_proton.labels.append({"id": "t2", "name": "Receipts", "path": "Receipts"})
    assert discover_targets(client) == {"Child", "Parent/Child", "Receipts"}
