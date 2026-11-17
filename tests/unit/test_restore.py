"""Unit 6 BR-15 to BR-22: restore."""

import dataclasses
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sieve_as_code import _restore as restore_module
from sieve_as_code._apply import ApplyReport
from sieve_as_code._backup import write_backup
from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._model import BackupError, SieveAsCodeError, ValidationError
from sieve_as_code._restore import RestoreReport, restore
from sieve_as_code._settings import AccountPaths
from tests.fake_proton import FakeProton

FRESH = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
WRITE_VERBS = {"create", "update", "delete", "enable", "disable", "reorder"}
_counter = itertools.count()


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def state(fake: FakeProton) -> list[tuple[str, str, int]]:
    return [(e["name"], e["sieve"], e["status"]) for e in fake.filters]


def write_calls(fake: FakeProton) -> list[str]:
    return [" ".join(c.path[2:]) for c in fake.calls if c.verb in WRITE_VERBS]


def audit_lines(paths: AccountPaths) -> list[dict[str, Any]]:
    if not paths.audit_log.exists():
        return []
    return [json.loads(line) for line in paths.audit_log.read_text().splitlines()]


def snapshot_files(paths: AccountPaths) -> list[Path]:
    return sorted(paths.backups_dir.glob("*.json"))


def backed_up(fake: FakeProton, paths: AccountPaths, client: ProtonClient) -> Path:
    """Seed a, b, c, snapshot them, then change live state in every way."""
    fake.add_filter("a", "keep;")
    fake.add_filter("b", "keep;")
    fake.add_filter("c", "keep;")
    path = write_backup(paths, client).path
    fake.filters.remove(fake.filters[2])  # c deleted
    fake.filters[0]["sieve"] = "stop;"  # a edited
    fake.filters[1]["status"] = 0  # b disabled
    fake.add_filter("d")  # created after the backup, enabled
    fake.add_filter("e", status=0)  # created after the backup, disabled
    fake.filters.reverse()
    return path


def test_other_account_or_unconnected_client_is_rejected(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-15, BR-1
    calls = len(fake_proton.calls)
    for bad in (
        dataclasses.replace(client, account="other"),
        dataclasses.replace(client, fingerprint=""),
    ):
        with pytest.raises(ValidationError):
            restore(None, work_account, bad, True)
    assert len(fake_proton.calls) == calls


def test_missing_backup_fails_before_live_state_is_read(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-15
    calls = len(fake_proton.calls)
    with pytest.raises(BackupError):
        restore(None, work_account, client, True)
    with pytest.raises(BackupError):
        restore("nope.json", work_account, client, True)
    assert len(fake_proton.calls) == calls


def test_restore_returns_live_state_to_the_backup(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-16, BR-17, BR-20, BR-21
    path = backed_up(fake_proton, work_account, client)
    report = restore(path, work_account, client, True)
    assert report.ok and report.remaining is not None
    assert state(fake_proton) == [
        ("a", "keep;", 1),
        ("b", "keep;", 1),
        ("c", "keep;", 1),
    ]
    kinds = [a.kind for a in report.succeeded]
    assert sorted(kinds[:-3]) == ["content", "create", "enabled"]
    assert kinds[-3:] == ["delete", "delete", "reorder"]
    assert report.snapshot is not None and report.snapshot.path != path
    assert len(snapshot_files(work_account)) == 2


def test_default_ref_restores_the_latest_backup(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-15
    backed_up(fake_proton, work_account, client)
    assert restore(None, work_account, client, True).ok
    assert [n for n, _, _ in state(fake_proton)] == ["a", "b", "c"]


def test_disabled_filter_created_after_the_backup_is_deleted(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-16
    fake_proton.add_filter("a")
    write_backup(work_account, client)
    fake_proton.add_filter("late", status=0)
    report = restore(None, work_account, client, True)
    assert report.ok and [a.kind for a in report.succeeded] == ["delete"]
    assert fake_proton.names() == ["a"]


def test_nothing_to_restore_writes_nothing(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-18
    fake_proton.add_filter("a")
    write_backup(work_account, client)
    lines = len(audit_lines(work_account))
    report = restore(None, work_account, client, True)
    assert report.ok and report.remaining is None and report.succeeded == ()
    assert write_calls(fake_proton) == []
    assert len(snapshot_files(work_account)) == 1
    assert len(audit_lines(work_account)) == lines


def test_unconfirmed_restore_is_refused_with_the_plan(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-19
    backed_up(fake_proton, work_account, client)
    before = state(fake_proton)
    report = restore(None, work_account, client, False)
    assert report.refused and not report.ok and report.snapshot is None
    assert {e.kind for e in report.plan.entries} == {
        "create",
        "content",
        "enabled",
        "live-only",
    }
    assert report.plan.informational == ("e",)
    assert state(fake_proton) == before and write_calls(fake_proton) == []
    assert len(snapshot_files(work_account)) == 1
    last = audit_lines(work_account)[-1]
    assert last["outcome"] == "refused"
    assert last["detail"] == {"command": "restore", "actions": 6}


def test_unwritable_pre_restore_snapshot_stops_before_any_write(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    tmp_path: Path,
) -> None:  # BR-20
    path = backed_up(fake_proton, work_account, client)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    paths = dataclasses.replace(work_account, backups_dir=blocked)
    with pytest.raises(BackupError):
        restore(path, paths, client, True)
    assert write_calls(fake_proton) == []


def test_pre_restore_snapshot_holds_the_state_before_the_restore(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-20
    path = backed_up(fake_proton, work_account, client)
    report = restore(path, work_account, client, True)
    assert report.snapshot is not None
    names = [f.name for f in report.snapshot.state.filters]
    assert names == ["e", "d", "b", "a"]


def test_failed_write_stops_restore_and_skips_verification(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-21, BR-17
    path = backed_up(fake_proton, work_account, client)
    fake_proton.failures["mail settings filters create"] = (1, "rejected")
    report = restore(path, work_account, client, True)
    assert not report.ok and report.failed is not None
    assert report.failed.action.kind == "create" and report.remaining is None
    assert any(a.kind == "reorder" for a in report.not_attempted)
    assert not any(
        line["outcome"] in {"verified", "drift"} for line in audit_lines(work_account)
    )


def hook_after(
    fake: FakeProton, monkeypatch: pytest.MonkeyPatch, verb: str, then: Any
) -> None:
    """Run `then()` once the fake has handled its first `verb` command."""
    original = fake.run

    def run(
        argv: list[str], input: str | None = None, **options: Any
    ) -> Any:  # noqa: A002
        result = original(argv, input, **options)
        if verb in argv:
            then()
        return result

    monkeypatch.setattr(subprocess, "run", run)


def test_verify_read_failure_is_a_failed_action(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-21
    path = backed_up(fake_proton, work_account, client)
    hook_after(
        fake_proton,
        monkeypatch,
        "reorder",
        lambda: fake_proton.failures.update(
            {"mail settings filters list": (1, "gone")}
        ),
    )
    report = restore(path, work_account, client, True)
    assert report.failed is not None
    assert (report.failed.action.kind, report.failed.action.name) == ("verify", "live")
    assert report.remaining is None and not report.ok


@pytest.mark.parametrize("status", [1, 0])
def test_remaining_difference_is_reported_and_not_ok(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:  # BR-21, BR-22
    path = backed_up(fake_proton, work_account, client)
    hook_after(
        fake_proton,
        monkeypatch,
        "reorder",
        lambda: fake_proton.add_filter("late", status=status),
    )
    report = restore(path, work_account, client, True)
    assert report.failed is None and report.remaining is not None and not report.ok
    last = audit_lines(work_account)[-1]
    assert (last["kind"], last["outcome"]) == ("check", "drift")
    count = len(report.remaining.entries)
    assert last["detail"] == {
        "entries": count,
        "informational": 1 - count,
        "reordered": 0,
    }


def test_verified_restore_is_audited_with_counts_only(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-11, BR-22
    path = backed_up(fake_proton, work_account, client)
    restore(path, work_account, client, True)
    lines = audit_lines(work_account)
    writes = [x for x in lines if x["detail"].get("command") == "restore"]
    assert len(writes) == 6 and {x["outcome"] for x in writes} == {"ok"}
    assert lines[-1]["outcome"] == "verified"
    assert lines[-1]["detail"] == {"entries": 0, "informational": 0, "reordered": 0}
    assert "keep;" not in work_account.audit_log.read_text()


def test_audit_failure_after_verification_is_reported(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-22
    def broken(*_args: object) -> None:
        raise SieveAsCodeError("cannot write audit log")

    path = backed_up(fake_proton, work_account, client)
    monkeypatch.setattr(restore_module, "record_check", broken)
    report = restore(path, work_account, client, True)
    assert report.audit_error == "cannot write audit log" and not report.ok
    assert report.remaining is not None


def test_duplicate_name_is_recreated_under_its_numbered_name(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-17, Unit 5
    fake_proton.add_filter("a", "keep;")
    fake_proton.add_filter("a", "stop;")
    write_backup(work_account, client)
    fake_proton.filters.pop()
    report = restore(None, work_account, client, True)
    assert report.ok
    assert state(fake_proton) == [("a", "keep;", 1), ("a (1)", "stop;", 1)]


def test_restore_report_extends_the_apply_report() -> None:  # public types
    assert issubclass(RestoreReport, ApplyReport)


def test_restore_report_is_not_ok_when_a_difference_remains(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-21
    fake_proton.add_filter("a")
    write_backup(work_account, client)
    report = restore(None, work_account, client, False)
    drifting = dataclasses.replace(report, refused=False, remaining=report.plan)
    assert drifting.ok  # an empty remaining diff is fine
    fake_proton.add_filter("late", status=0)
    other = restore(None, work_account, client, False)
    assert not dataclasses.replace(other, refused=False, remaining=other.plan).ok


@st.composite
def worlds(
    draw: st.DrawFn,
) -> tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]]:
    scripts = st.sampled_from(["keep;", "stop;", "discard;"])

    def rows() -> list[tuple[str, str, bool]]:
        names = draw(st.lists(st.sampled_from("abcdef"), unique=True, max_size=6))
        return [(n, draw(scripts), draw(st.booleans())) for n in names]

    return rows(), rows()


def seed(fake: FakeProton, rows: list[tuple[str, str, bool]]) -> None:
    fake.filters.clear()
    for name, script, enabled in rows:
        fake.add_filter(name, script, 1 if enabled else 0)


@FRESH
@given(worlds())
def test_restore_returns_any_state_to_any_backup(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    world: tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]],
) -> None:  # BR-16, BR-21
    backup, later = world
    paths = dataclasses.replace(
        work_account, backups_dir=work_account.backups_dir / f"r{next(_counter)}"
    )
    seed(fake_proton, backup)
    wanted = state(fake_proton)
    snapshot = write_backup(paths, client)
    seed(fake_proton, later)
    report = restore(snapshot.path, paths, client, True)
    assert report.ok
    assert state(fake_proton) == wanted
