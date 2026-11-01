"""Unit 5 BR-1 to BR-13: snapshots, verification and snapshot diff."""

import dataclasses
import hashlib
import itertools
import json
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from sieve_as_code.backup import diff_backups, prune_backups, read_backup, write_backup
from sieve_as_code.client import ProtonClient, connect
from sieve_as_code.model import (
    BackupError,
    ClientError,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code.settings import AccountPaths, Retention
from tests.fake_proton import FakeProton

FINGERPRINT = "abcabcabcabc"
FRESH = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
_counter = itertools.count()


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def sign(document: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in document.items() if k != "checksum"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {**body, "checksum": hashlib.sha256(canonical.encode()).hexdigest()}


def make_document(
    filters: list[tuple[str, str, bool]], fingerprint: str = FINGERPRINT
) -> dict[str, Any]:
    return sign(
        {
            "format": 1,
            "created": "2026-11-01T12:00:00.000Z",
            "account": "work",
            "fingerprint": fingerprint,
            "filters": [
                {"name": n, "raw_sieve": s, "enabled": e} for n, s, e in filters
            ],
            "renames": [],
        }
    )


def fresh(paths: AccountPaths) -> AccountPaths:
    """Paths with an unused backups directory (one per property example)."""
    return dataclasses.replace(
        paths, backups_dir=paths.backups_dir / f"run{next(_counter)}"
    )


def save(paths: AccountPaths, name: str, document: Any) -> Path:
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    path = paths.backups_dir / name
    path.write_text(json.dumps(document))
    return path


def audit_lines(paths: AccountPaths) -> list[dict[str, Any]]:
    if not paths.audit_log.exists():
        return []
    return [json.loads(line) for line in paths.audit_log.read_text().splitlines()]


def test_wrong_account_or_unconnected_client_is_refused(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-1
    calls = len(fake_proton.calls)
    other = dataclasses.replace(work_account, account="home")
    with pytest.raises(ValidationError, match="home"):
        write_backup(other, client)
    with pytest.raises(ValidationError):
        write_backup(work_account, ProtonClient("proton", "work"))
    assert len(fake_proton.calls) == calls
    assert not work_account.backups_dir.exists()


def test_snapshot_holds_live_filters_in_order_with_numbered_duplicates(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-2, BR-3
    fake_proton.add_filter("a", "keep;")
    fake_proton.add_filter("a", "stop;", status=0)
    snapshot = write_backup(work_account, client)
    document = json.loads(snapshot.path.read_text())
    assert set(document) == {
        "format",
        "created",
        "account",
        "fingerprint",
        "filters",
        "renames",
        "checksum",
    }
    assert document["format"] == 1 and document["account"] == "work"
    assert document["fingerprint"] == client.fingerprint
    assert document["filters"] == [
        {"name": "a", "raw_sieve": "keep;", "enabled": True},
        {"name": "a (1)", "raw_sieve": "stop;", "enabled": False},
    ]
    assert document["renames"] == [{"original": "a", "name": "a (1)"}]
    assert snapshot.state.order.sequence == ("a", "a (1)")
    assert all(f.live_id is None for f in snapshot.state.filters)


def test_an_empty_account_gives_a_valid_snapshot(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-2 boundary
    snapshot = write_backup(work_account, client)
    again = read_backup(snapshot.path, work_account, client.fingerprint)
    assert again.state.filters == () and again.state.order.sequence == ()


@FRESH
@given(
    st.lists(
        st.tuples(st.text(min_size=1), st.text(), st.booleans()),
        unique_by=lambda row: row[0],
        max_size=5,
    )
)
def test_a_written_snapshot_reads_back_equal(
    work_account: AccountPaths, rows: list[tuple[str, str, bool]]
) -> None:  # roundtrip
    paths = fresh(work_account)
    save(paths, "x.json", make_document(rows))
    state = read_backup("x.json", paths, FINGERPRINT).state
    assert [(f.name, f.raw_sieve, f.enabled) for f in state.filters] == rows
    assert state.order.sequence == tuple(name for name, _, _ in rows)


@FRESH
@given(st.text(), st.text())
def test_changing_a_script_without_resigning_is_rejected(
    work_account: AccountPaths, old: str, new: str
) -> None:  # BR-4
    assume(old != new)
    paths = fresh(work_account)
    document = make_document([("a", old, True)])
    document["filters"][0]["raw_sieve"] = new
    save(paths, "x.json", document)
    with pytest.raises(BackupError, match="checksum"):
        read_backup("x.json", paths, FINGERPRINT)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda d: d["filters"][0].update(enabled=False),
        lambda d: d["filters"][0].update(name="z"),
        lambda d: d["filters"].reverse(),
        lambda d: d.update(account="other"),
        lambda d: d.update(created="2020-01-01T00:00:00.000Z"),
        lambda d: d["renames"].append({"original": "a", "name": "b"}),
    ],
)
def test_changing_any_value_without_resigning_is_rejected(
    tamper: Any, work_account: AccountPaths
) -> None:  # BR-4
    document = make_document([("a", "keep;", True), ("b", "stop;", True)])
    tamper(document)
    save(work_account, "x.json", document)
    with pytest.raises(BackupError, match="checksum"):
        read_backup("x.json", work_account, FINGERPRINT)


def test_whitespace_only_edits_keep_the_checksum_valid(
    work_account: AccountPaths,
) -> None:  # BR-4
    path = save(work_account, "x.json", make_document([("a", "keep;", True)]))
    path.write_text(json.dumps(json.loads(path.read_text()), indent=4))
    assert read_backup("x.json", work_account, FINGERPRINT).state.filters


def test_file_and_directory_are_owner_only_and_named_by_time(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-5
    snapshot = write_backup(work_account, client)
    assert re.fullmatch(r"\d{8}T\d{12}Z\.json", snapshot.path.name)
    assert stat.S_IMODE(snapshot.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(work_account.backups_dir.stat().st_mode) == 0o700


def test_an_existing_file_is_never_overwritten(
    client: ProtonClient,
    work_account: AccountPaths,
    fake_proton: FakeProton,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-5
    class Fixed(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "Fixed":
            return cls(2026, 11, 1, 12, 0, 0, 123456, tzinfo=tz or UTC)

    monkeypatch.setattr("sieve_as_code.backup.datetime", Fixed)
    first = write_backup(work_account, client)
    before = first.path.read_bytes()
    fake_proton.add_filter("late")
    with pytest.raises(BackupError, match="already exists"):
        write_backup(work_account, client)
    assert first.path.read_bytes() == before
    assert len(audit_lines(work_account)) == 1


def test_a_backups_path_that_is_a_file_is_a_backup_error(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-5
    work_account.backups_dir.parent.mkdir(parents=True)
    work_account.backups_dir.write_text("not a directory")
    with pytest.raises(BackupError, match="cannot create"):
        write_backup(work_account, client)


def test_a_directory_that_cannot_be_written_is_a_backup_error(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-5
    work_account.backups_dir.mkdir(parents=True)
    work_account.backups_dir.chmod(0o500)
    try:
        with pytest.raises(BackupError, match="cannot create"):
            write_backup(work_account, client)
    finally:
        work_account.backups_dir.chmod(0o700)


def test_a_failed_write_leaves_no_file(
    client: ProtonClient,
    work_account: AccountPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-6
    def full(descriptor: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", full)
    with pytest.raises(BackupError, match="No space left"):
        write_backup(work_account, client)
    assert list(work_account.backups_dir.iterdir()) == []
    assert audit_lines(work_account) == []


def test_a_partial_file_that_cannot_be_removed_is_named(
    client: ProtonClient,
    work_account: AccountPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-6
    def fail(*args: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", fail)
    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(BackupError, match="could not be removed"):
        write_backup(work_account, client)


def test_a_proton_failure_writes_nothing(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-7
    fake_proton.failures["mail settings filters list"] = (1, "boom")
    with pytest.raises(ClientError):
        write_backup(work_account, client)
    assert not work_account.backups_dir.exists()
    assert audit_lines(work_account) == []


def test_a_backup_appends_one_audit_line_without_names_or_content(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-8
    fake_proton.add_filter("secret-name", "SECRET;")
    fake_proton.add_filter("secret-name", "SECRET;")
    snapshot = write_backup(work_account, client)
    (line,) = audit_lines(work_account)
    assert line["kind"] == "write" and line["outcome"] == "backup"
    assert line["detail"] == {"file": snapshot.path.name, "filters": 2, "renamed": 1}
    raw = work_account.audit_log.read_text()
    assert "secret-name" not in raw and "SECRET" not in raw


def test_an_audit_failure_raises_and_keeps_the_snapshot(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-8
    work_account.audit_log.mkdir(parents=True)
    with pytest.raises(SieveAsCodeError, match="audit log"):
        write_backup(work_account, client)
    assert len(list(work_account.backups_dir.iterdir())) == 1


def test_refs_resolve_to_latest_file_or_name(
    client: ProtonClient,
    work_account: AccountPaths,
    fake_proton: FakeProton,
    tmp_path: Path,
) -> None:  # BR-9
    first = write_backup(work_account, client)
    fake_proton.add_filter("later")
    last = write_backup(work_account, client)
    stem = last.path.name.removesuffix(".json")
    fingerprint = client.fingerprint
    assert read_backup(None, work_account, fingerprint).path == last.path
    assert read_backup(first.path, work_account, fingerprint).path == first.path
    assert read_backup(str(first.path), work_account, fingerprint).path == first.path
    assert read_backup(stem, work_account, fingerprint).path == last.path
    assert read_backup(stem + ".json", work_account, fingerprint).path == last.path
    elsewhere = tmp_path / "copy.json"
    elsewhere.write_bytes(first.path.read_bytes())
    assert read_backup(elsewhere, work_account, fingerprint).path == elsewhere


def test_a_missing_backup_is_an_error(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-9
    with pytest.raises(BackupError, match="no backups"):
        read_backup(None, work_account, client.fingerprint)
    write_backup(work_account, client)
    for ref in ("nope", "../nope", "sub/nope.json"):
        with pytest.raises(BackupError, match="no backup"):
            read_backup(ref, work_account, client.fingerprint)


def test_an_unreadable_file_is_an_error(work_account: AccountPaths) -> None:  # BR-10
    path = save(work_account, "x.json", make_document([]))
    path.chmod(0)
    try:
        with pytest.raises(BackupError, match="cannot read"):
            read_backup("x.json", work_account, FINGERPRINT)
    finally:
        path.chmod(0o600)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("nope", "not valid JSON"),
        ("[]", "not a snapshot"),
        ("{}", "unsupported snapshot format None"),
    ],
)
def test_a_file_that_is_not_a_snapshot_is_rejected(
    text: str, message: str, work_account: AccountPaths
) -> None:  # BR-10
    work_account.backups_dir.mkdir(parents=True)
    (work_account.backups_dir / "x.json").write_text(text)
    with pytest.raises(BackupError, match=message):
        read_backup("x.json", work_account, FINGERPRINT)


def _bad_rows(document: dict[str, Any]) -> None:
    document["filters"].append({"name": "b"})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(format=2), "unsupported snapshot format 2"),
        (lambda d: d.pop("renames"), "unexpected or missing"),
        (lambda d: d.update(extra=1), "unexpected or missing"),
        (lambda d: d.update(filters="x"), "'filters' is malformed"),
        (lambda d: d.update(filters=["x"]), "'filters' is malformed"),
        (_bad_rows, "'filters' is malformed"),
        (lambda d: d["filters"][0].update(name=""), "filter entry"),
        (lambda d: d["filters"][0].update(name=1), "filter entry"),
        (lambda d: d["filters"][0].update(raw_sieve=1), "filter entry"),
        (lambda d: d["filters"][0].update(enabled="yes"), "filter entry"),
        (lambda d: d["filters"].append(dict(d["filters"][0])), "not unique"),
        (lambda d: d.update(renames=[{"original": "a"}]), "'renames' is malformed"),
        (
            lambda d: d.update(renames=[{"original": "a", "name": 1}]),
            "rename entry",
        ),
        (lambda d: d.update(created=1), "'created' is not text"),
        (lambda d: d.update(account=1), "'account' is not text"),
        (lambda d: d.update(fingerprint=1), "'fingerprint' is not text"),
        (lambda d: d.update(fingerprint="ffffffffffff"), "different Proton account"),
    ],
)
def test_each_failed_check_is_a_backup_error_without_filter_content(
    mutate: Any, message: str, work_account: AccountPaths
) -> None:  # BR-10, BR-13
    document = make_document([("a", "SECRET;", True)])
    mutate(document)
    save(work_account, "x.json", sign(document))
    with pytest.raises(BackupError, match=message) as caught:
        read_backup("x.json", work_account, FINGERPRINT)
    assert "SECRET" not in str(caught.value)
    assert "x.json" in str(caught.value)


def test_the_account_name_in_a_snapshot_is_informational(
    work_account: AccountPaths,
) -> None:  # BR-13
    document = make_document([])
    document["account"] = "renamed"
    save(work_account, "x.json", sign(document))
    assert read_backup("x.json", work_account, FINGERPRINT).account == "renamed"


def test_a_snapshot_diffed_with_itself_is_clean(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-11, BR-12
    fake_proton.add_filter("a")
    snapshot = write_backup(work_account, client)
    result = diff_backups(snapshot.path, snapshot.path, work_account)
    assert result.outcome == "clean"


def test_diff_backups_reports_what_changed_from_a_to_b(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-12
    fake_proton.add_filter("kept", "keep;")
    fake_proton.add_filter("gone", "keep;")
    fake_proton.add_filter("edited", "keep;")
    older = write_backup(work_account, client)
    fake_proton.filters[:] = [
        fake_proton.filters[2] | {"sieve": "stop;"},
        fake_proton.filters[0],
    ]
    fake_proton.add_filter("added")
    newer = write_backup(work_account, client)
    calls = len(fake_proton.calls)
    result = diff_backups(older.path.name, newer.path.name, work_account)
    assert len(fake_proton.calls) == calls
    assert {(e.kind, e.name) for e in result.entries} == {
        ("create", "added"),
        ("content", "edited"),
        ("live-only", "gone"),
    }
    assert result.reorder is not None
    assert result.missing_targets == () and result.flags == ()


@FRESH
@given(
    st.lists(st.sampled_from("abcd"), unique=True, max_size=4),
    st.lists(st.sampled_from("abcd"), unique=True, max_size=4),
)
def test_added_in_one_direction_is_removed_in_the_other(
    work_account: AccountPaths, first: list[str], second: list[str]
) -> None:  # BR-12 mirror
    paths = fresh(work_account)
    paths.account_marker.parent.mkdir(parents=True, exist_ok=True)
    paths.account_marker.write_text(FINGERPRINT + "\n")
    save(paths, "a.json", make_document([(n, "keep;", True) for n in first]))
    save(paths, "b.json", make_document([(n, "keep;", True) for n in second]))
    forward = diff_backups("a.json", "b.json", paths)
    backward = diff_backups("b.json", "a.json", paths)

    def names(result: Any, kind: str) -> set[str]:
        return {e.name for e in result.entries if e.kind == kind}

    assert names(forward, "create") == names(backward, "live-only")
    assert names(forward, "live-only") == names(backward, "create")


def test_diff_backups_needs_a_recorded_fingerprint(
    work_account: AccountPaths,
) -> None:  # BR-12
    save(work_account, "a.json", make_document([]))
    with pytest.raises(BackupError, match="cannot read"):
        diff_backups("a.json", "a.json", work_account)
    work_account.account_marker.parent.mkdir(parents=True)
    work_account.account_marker.write_text("\n")
    with pytest.raises(BackupError, match="is empty"):
        diff_backups("a.json", "a.json", work_account)


def test_diff_backups_refuses_a_snapshot_of_another_account(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-12, BR-13
    mine = write_backup(work_account, client)
    foreign = save(work_account, "foreign.json", make_document([], "ffffffffffff"))
    with pytest.raises(BackupError, match="different Proton account"):
        diff_backups(mine.path, foreign, work_account)


def test_an_unchanged_state_returns_the_latest_snapshot_and_audits_it(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-14, BR-15
    fake_proton.add_filter("a")
    first = write_backup(work_account, client)
    second = write_backup(work_account, client)
    assert second.path == first.path and second.unchanged and not first.unchanged
    assert len(list(work_account.backups_dir.iterdir())) == 1
    lines = audit_lines(work_account)
    assert [(x["kind"], x["outcome"]) for x in lines] == [
        ("write", "backup"),
        ("check", "unchanged"),
    ]
    assert lines[1]["detail"] == {"file": first.path.name, "filters": 1, "renamed": 0}


@pytest.mark.parametrize(
    "change",
    [
        lambda f: f.filters[0].update(sieve="stop;"),
        lambda f: f.filters[0].update(status=0),
        lambda f: f.filters.reverse(),
        lambda f: f.add_filter("a"),
        lambda f: f.add_filter("new"),
        lambda f: f.filters.pop(),
    ],
)
def test_any_change_of_state_writes_a_new_backup(
    change: Any,
    client: ProtonClient,
    work_account: AccountPaths,
    fake_proton: FakeProton,
) -> None:  # BR-14
    fake_proton.add_filter("a")
    fake_proton.add_filter("b")
    first = write_backup(work_account, client)
    change(fake_proton)
    second = write_backup(work_account, client)
    assert second.path != first.path and not second.unchanged
    assert len(list(work_account.backups_dir.iterdir())) == 2


def test_only_the_latest_snapshot_is_compared(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-14
    fake_proton.add_filter("a", "keep;")
    write_backup(work_account, client)
    fake_proton.filters[0]["sieve"] = "stop;"
    write_backup(work_account, client)
    fake_proton.filters[0]["sieve"] = "keep;"
    third = write_backup(work_account, client)
    assert not third.unchanged
    assert len(list(work_account.backups_dir.iterdir())) == 3


def test_unchanged_duplicate_names_still_match_their_snapshot(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-14
    fake_proton.add_filter("a")
    fake_proton.add_filter("a")
    write_backup(work_account, client)
    assert write_backup(work_account, client).unchanged


def test_an_unreadable_or_foreign_latest_is_not_a_skip(
    client: ProtonClient, work_account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-14
    fake_proton.add_filter("a")
    good = write_backup(work_account, client)
    foreign = save(work_account, "99990101T000000000000Z.json", make_document([]))
    taken = write_backup(work_account, client)
    assert not taken.unchanged and taken.path != good.path
    foreign.write_text("garbage")
    again = write_backup(work_account, client)
    assert not again.unchanged
    assert foreign.read_text() == "garbage"


def test_an_audit_failure_on_a_skip_raises(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-15
    write_backup(work_account, client)
    work_account.audit_log.unlink()
    work_account.audit_log.mkdir()
    with pytest.raises(SieveAsCodeError, match="audit log"):
        write_backup(work_account, client)


def snapshot_names(paths: AccountPaths, *ages: timedelta) -> list[str]:
    """Create empty snapshot-named files this long ago; return names, oldest first."""
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    names = sorted((now - age).strftime("%Y%m%dT%H%M%S%fZ.json") for age in ages)
    for name in names:
        (paths.backups_dir / name).write_text("{}")
    return names


def remaining(paths: AccountPaths) -> list[str]:
    return sorted(p.name for p in paths.backups_dir.iterdir())


HOUR = timedelta(hours=1)


def test_nothing_is_pruned_without_limits_or_a_directory(
    work_account: AccountPaths,
) -> None:  # BR-16
    assert prune_backups(work_account, Retention(1, 1)) == ()
    names = snapshot_names(work_account, HOUR * 1, HOUR * 500)
    assert prune_backups(work_account, Retention()) == ()
    assert remaining(work_account) == names
    assert audit_lines(work_account) == []


def test_other_files_directories_and_invalid_dates_are_left_alone(
    work_account: AccountPaths,
) -> None:  # BR-16
    names = snapshot_names(work_account, HOUR * 1, HOUR * 500)
    others = ["notes.txt", "backup.json", "99999999T999999999999Z.json"]
    for other in others:
        (work_account.backups_dir / other).write_text("x")
    (work_account.backups_dir / "20200101T000000000000Z.json").mkdir()
    removed = prune_backups(work_account, Retention(keep_last=1))
    assert removed == (names[0],)
    assert sorted(others + ["20200101T000000000000Z.json", names[1]]) == remaining(
        work_account
    )


def test_keep_last_keeps_the_newest_n(work_account: AccountPaths) -> None:  # BR-17
    names = snapshot_names(work_account, *(HOUR * n for n in (5, 4, 3, 2, 1)))
    assert prune_backups(work_account, Retention(keep_last=2)) == tuple(names[:3])
    assert remaining(work_account) == names[3:]


def test_keep_days_keeps_what_is_newer_than_the_window(
    work_account: AccountPaths,
) -> None:  # BR-17
    names = snapshot_names(work_account, HOUR * 25, HOUR * 23, HOUR * 1)
    assert prune_backups(work_account, Retention(keep_days=1)) == (names[0],)
    assert remaining(work_account) == names[1:]


def test_either_limit_keeps_a_snapshot(work_account: AccountPaths) -> None:  # BR-17
    names = snapshot_names(work_account, HOUR * 100, HOUR * 50, HOUR * 2, HOUR * 1)
    prune_backups(work_account, Retention(keep_days=1, keep_last=2))
    assert remaining(work_account) == names[2:]
    prune_backups(work_account, Retention(keep_days=1, keep_last=1))
    assert remaining(work_account) == names[2:]


def test_the_newest_snapshot_is_never_removed(work_account: AccountPaths) -> None:
    names = snapshot_names(work_account, HOUR * 500, HOUR * 600)  # BR-17
    prune_backups(work_account, Retention(keep_days=1))
    assert remaining(work_account) == names[-1:]


def test_pruning_audits_counts_and_stays_silent_when_nothing_goes(
    work_account: AccountPaths,
) -> None:  # BR-18
    snapshot_names(work_account, HOUR * 3, HOUR * 2, HOUR * 1)
    prune_backups(work_account, Retention(keep_last=3))
    assert audit_lines(work_account) == []
    prune_backups(work_account, Retention(keep_last=1))
    (line,) = audit_lines(work_account)
    assert (line["kind"], line["outcome"]) == ("write", "prune")
    assert line["detail"] == {"removed": 2, "kept": 1}


def test_a_removal_failure_audits_the_earlier_removals_then_raises(
    work_account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-18
    names = snapshot_names(work_account, *(HOUR * n for n in (4, 3, 2, 1)))
    real = Path.unlink

    def flaky(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == names[1]:
            raise OSError(13, "Permission denied")
        real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky)
    with pytest.raises(BackupError, match=f"cannot remove .*{names[1]}"):
        prune_backups(work_account, Retention(keep_last=1))
    assert remaining(work_account) == names[1:]
    (line,) = audit_lines(work_account)
    assert line["detail"] == {"removed": 1, "kept": 3}


@FRESH
@given(
    st.lists(st.integers(1, 2000), unique=True, min_size=1, max_size=8),
    st.none() | st.integers(1, 5),
    st.none() | st.integers(1, 50),
)
def test_pruning_keeps_exactly_the_union_and_never_the_empty_set(
    work_account: AccountPaths,
    hours: list[int],
    last: int | None,
    days: int | None,
) -> None:  # BR-17
    paths = fresh(work_account)
    names = snapshot_names(paths, *(HOUR * n for n in hours))
    prune_backups(paths, Retention(keep_days=days, keep_last=last))
    if last is None and days is None:
        expected = set(names)
    else:
        by_age = sorted(hours)  # smallest = newest
        expected = {names[-1]}
        if last:
            expected |= set(names[-last:])
        if days:
            expected |= {
                n for n, h in zip(reversed(names), by_age, strict=True) if h < days * 24
            }
    assert set(remaining(paths)) == expected
    assert names[-1] in remaining(paths)
