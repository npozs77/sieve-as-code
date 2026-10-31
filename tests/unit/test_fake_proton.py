"""The fake is shared by later units: pin the behaviour they rely on."""

import pytest

from sieve_as_code.client import ProtonClient
from sieve_as_code.model import ClientError
from tests.fake_proton import FakeProton


def test_reorder_puts_named_filters_first_and_keeps_the_rest_in_order(
    fake_proton: FakeProton,
) -> None:
    for name in "abcd":
        fake_proton.add_filter(name)
    ProtonClient("proton", "work").reorder_filters(["f3"])
    assert fake_proton.names() == ["c", "a", "b", "d"]


def test_changes_are_visible_to_the_next_list(fake_proton: FakeProton) -> None:
    client = ProtonClient("proton", "work")
    live_id = client.create_filter("n", "keep;")
    client.disable_filter(live_id)
    assert [(r.name, r.enabled) for r in client.list_filters()] == [("n", False)]
    client.delete_filter(live_id)
    assert client.list_filters() == []


def test_unknown_filter_is_exit_3(fake_proton: FakeProton) -> None:
    with pytest.raises(ClientError) as raised:
        ProtonClient("proton", "work").get_filter("nope")
    assert raised.value.exit_code == 3


def test_filters_are_found_by_name_or_id(fake_proton: FakeProton) -> None:
    live_id = fake_proton.add_filter("Receipts", "stop;")
    client = ProtonClient("proton", "work")
    assert client.get_filter("Receipts") == client.get_filter(live_id)
