"""BR-8: Filter and FilterOrder defaults and immutability."""

import dataclasses

import pytest

from sieve_as_code.model import Filter, FilterOrder, SieveAsCodeError, ValidationError


def test_filter_defaults_to_enabled_without_live_id() -> None:  # BR-8
    result = Filter(name="a", raw_sieve="keep;")
    assert result.raw_sieve == "keep;"
    assert result.enabled is True
    assert result.live_id is None


def test_filter_is_immutable() -> None:  # BR-8
    result = Filter(name="a", raw_sieve="keep;")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.name = "b"  # type: ignore[misc]


def test_filter_order_keeps_sequence_and_is_immutable() -> None:  # BR-8
    order = FilterOrder(sequence=("b", "a"))
    assert order.sequence == ("b", "a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.sequence = ()  # type: ignore[misc]


def test_validation_error_is_a_package_error() -> None:
    assert issubclass(ValidationError, SieveAsCodeError)
