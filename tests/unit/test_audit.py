"""BR-9 to BR-12: the append-only audit log."""

import json
import re
import stat
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sieve_as_code.audit import Scalar, record_check, record_write
from sieve_as_code.model import SieveAsCodeError

Recorder = Callable[[Path, str, Mapping[str, Scalar]], None]

scalars = st.one_of(st.text(), st.integers(), st.booleans(), st.none())
details = st.dictionaries(st.text(), scalars)
non_scalars = st.one_of(
    st.lists(st.integers()),
    st.dictionaries(st.text(), st.integers()),
    st.floats(),
    st.binary(),
)


def read_lines(path: Path) -> list[bytes]:
    return path.read_bytes().split(b"\n")[:-1]


# BR-9
@pytest.mark.parametrize(
    ("recorder", "kind"), [(record_write, "write"), (record_check, "check")]
)
def test_record_has_exactly_four_keys_and_matching_kind(
    tmp_path: Path, recorder: Recorder, kind: str
) -> None:
    log = tmp_path / "audit.log"
    recorder(log, "ok", {"filter": "a", "count": 2})
    record = json.loads(log.read_text())
    assert set(record) == {"ts", "kind", "outcome", "detail"}
    assert record["kind"] == kind
    assert record["outcome"] == "ok"
    assert record["detail"] == {"filter": "a", "count": 2}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", record["ts"])


def test_empty_detail_is_accepted(tmp_path: Path) -> None:
    record_check(tmp_path / "audit.log", "clean", {})
    assert json.loads((tmp_path / "audit.log").read_text())["detail"] == {}


# BR-10
@given(details)
def test_scalar_detail_round_trips(detail: dict[str, Scalar]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        log = Path(directory) / "audit.log"
        record_write(log, "ok", detail)
        assert json.loads(log.read_text())["detail"] == detail


@given(non_scalars)
def test_non_scalar_detail_is_rejected_and_nothing_written(value: object) -> None:
    with tempfile.TemporaryDirectory() as directory:
        log = Path(directory) / "audit.log"
        with pytest.raises(ValueError):
            record_write(log, "ok", {"k": value})  # type: ignore[dict-item]
        assert not log.exists()


@pytest.mark.parametrize("outcome", ["", "  "])
def test_blank_outcome_is_rejected(tmp_path: Path, outcome: str) -> None:
    with pytest.raises(ValueError):
        record_check(tmp_path / "audit.log", outcome, {})
    assert not (tmp_path / "audit.log").exists()


# BR-11
@given(st.lists(details, min_size=1, max_size=5))
def test_appends_keep_earlier_lines_unchanged(entries: list[dict[str, Scalar]]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        log = Path(directory) / "audit.log"
        previous: list[bytes] = []
        for entry in entries:
            record_write(log, "ok", entry)
            lines = read_lines(log)
            assert lines[: len(previous)] == previous
            assert len(lines) == len(previous) + 1
            previous = lines


def test_missing_directory_and_file_are_created_owner_only(tmp_path: Path) -> None:
    log = tmp_path / "state" / "audit.log"
    record_check(log, "ok", {})
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700


# BR-12
def test_unwritable_log_raises_error_naming_the_path(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log = blocker / "audit.log"
    with pytest.raises(SieveAsCodeError, match="audit.log"):
        record_write(log, "ok", {})


def test_append_works_after_a_failed_append(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    record_write(log, "ok", {"n": 1})
    with pytest.raises(ValueError):
        record_write(log, "ok", {"n": [1]})  # type: ignore[dict-item]
    record_write(log, "ok", {"n": 2})
    assert len(read_lines(log)) == 2
