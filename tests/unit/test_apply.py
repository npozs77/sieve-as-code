"""Unit 6 BR-1 to BR-14: apply."""

import dataclasses
import itertools
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sieve_as_code import _apply as apply_module
from sieve_as_code._apply import Action, ApplyReport, apply_plan
from sieve_as_code._backup import write_backup
from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._declared import render
from sieve_as_code._model import (
    BackupError,
    Filter,
    FilterOrder,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code._plan import PlanResult
from sieve_as_code._settings import AccountPaths
from tests.fake_proton import FakeProton

FRESH = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
WRITE_VERBS = {"create", "update", "delete", "enable", "disable", "reorder"}
FOLDER_SCRIPT = 'require ["fileinto"];\nfileinto "X/Y";\nfileinto "Tag";'
EXPIRE = 'require ["vnd.proton.expire"];\nexpire "day" "7";'
_counter = itertools.count()


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def declare(paths: AccountPaths, *rows: tuple[str, str, bool]) -> None:
    """Replace the declared files with `(name, script, enabled)` rows in order."""
    shutil.rmtree(paths.filters_dir, ignore_errors=True)
    paths.filters_dir.mkdir(parents=True)
    filters = [Filter(n, s, e) for n, s, e in rows]
    order = FilterOrder(tuple(n for n, _, _ in rows))
    for path, text in render(filters, order, paths).items():
        path.write_text(text)


def write_calls(fake: FakeProton) -> list[str]:
    return [" ".join(c.path[2:]) for c in fake.calls if c.verb in WRITE_VERBS]


def audit_lines(paths: AccountPaths) -> list[dict[str, Any]]:
    if not paths.audit_log.exists():
        return []
    return [json.loads(line) for line in paths.audit_log.read_text().splitlines()]


def run_lines(paths: AccountPaths) -> list[dict[str, Any]]:
    return [x for x in audit_lines(paths) if x["detail"].get("command") == "apply"]


def kinds(report: ApplyReport) -> list[str]:
    return [a.kind for a in report.succeeded]


def test_other_account_or_unconnected_client_is_rejected(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-1
    declare(work_account, ("a", "keep;", True))
    calls = len(fake_proton.calls)
    for bad in (
        dataclasses.replace(client, account="other"),
        dataclasses.replace(client, fingerprint=""),
    ):
        with pytest.raises(ValidationError):
            apply_plan(work_account, bad, True, False)
    assert len(fake_proton.calls) == calls
    assert audit_lines(work_account) == []


def test_invalid_declared_files_fail_before_any_write(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-2
    with pytest.raises(ValidationError):
        apply_plan(work_account, client, True, False)
    declare(work_account, ("a", "if true {", True))
    with pytest.raises(ValidationError):
        apply_plan(work_account, client, True, False)
    assert write_calls(fake_proton) == []
    assert not work_account.backups_dir.exists()


def test_clean_plan_writes_nothing_and_takes_no_snapshot(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-3
    fake_proton.add_filter("a")
    fake_proton.add_filter("off", status=0)
    declare(work_account, ("a", "keep;", True))
    report = apply_plan(work_account, client, True, True)
    assert report.ok and report.plan.outcome == "clean"
    assert report.snapshot is None and report.succeeded == ()
    assert write_calls(fake_proton) == []
    assert not work_account.backups_dir.exists()
    assert audit_lines(work_account) == []


def test_unconfirmed_apply_is_refused_with_the_plan(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-4
    fake_proton.add_filter("a")
    declare(work_account, ("a", "stop;", True), ("b", "keep;", True))
    report = apply_plan(work_account, client, False, False)
    assert report.refused and not report.ok
    assert [e.kind for e in report.plan.entries] == ["create", "content"]
    assert report.snapshot is None and report.succeeded == ()
    assert write_calls(fake_proton) == []
    assert not work_account.backups_dir.exists()
    (line,) = audit_lines(work_account)
    assert line["kind"] == "check" and line["outcome"] == "refused"
    assert line["detail"] == {"command": "apply", "actions": 2}


def test_snapshot_is_taken_before_the_first_write(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-5
    fake_proton.add_filter("a")
    declare(work_account, ("a", "stop;", True))
    report = apply_plan(work_account, client, True, False)
    assert report.snapshot is not None and report.snapshot.path.is_file()
    assert report.snapshot.state.filters[0].raw_sieve == "keep;"
    assert audit_lines(work_account)[0]["outcome"] == "backup"


def test_an_equal_latest_snapshot_is_reused(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-5
    fake_proton.add_filter("a")
    earlier = write_backup(work_account, client)
    declare(work_account, ("a", "stop;", True))
    report = apply_plan(work_account, client, True, False)
    assert report.snapshot is not None and report.snapshot.unchanged
    assert report.snapshot.path == earlier.path
    assert len(list(work_account.backups_dir.glob("*.json"))) == 1


def test_unwritable_snapshot_stops_before_any_write(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    tmp_path: Path,
) -> None:  # BR-5
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    fake_proton.add_filter("a")
    declare(work_account, ("a", "stop;", True))
    paths = dataclasses.replace(work_account, backups_dir=blocked)
    with pytest.raises(BackupError):
        apply_plan(paths, client, True, False)
    assert write_calls(fake_proton) == []


def test_writes_follow_the_documented_order_with_scripts_on_stdin(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-6, BR-7, BR-13
    fake_proton.add_filter("a")
    fake_proton.add_filter("b")
    fake_proton.add_filter("c")
    fake_proton.add_filter("z")
    declare(
        work_account,
        ("n", FOLDER_SCRIPT, True),
        ("b", "stop;", True),
        ("a", "keep;", False),
        ("c", "keep;", True),
    )
    report = apply_plan(work_account, client, True, False)
    assert report.ok
    assert write_calls(fake_proton) == [
        "folders create",
        "folders create",
        "labels create",
        "filters create",
        "filters update",
        "filters disable",
        "filters disable",
        "filters reorder",
    ]
    assert kinds(report) == [
        "folder",
        "folder",
        "label",
        "create",
        "content",
        "enabled",
        "disable",
        "reorder",
    ]
    assert fake_proton.names() == ["n", "b", "a", "c", "z"]
    status = {e["name"]: e["status"] for e in fake_proton.filters}
    assert status == {"n": 1, "b": 1, "a": 0, "c": 1, "z": 0}
    assert [r["path"] for r in fake_proton.folders] == ["X", "X/Y"]
    assert fake_proton.folders[1]["name"] == "Y"
    assert [r["name"] for r in fake_proton.labels] == ["Tag"]
    for call in fake_proton.calls:
        assert "keep;" not in " ".join(call.argv) and "stop;" not in " ".join(call.argv)
    again = apply_plan(work_account, client, True, False)
    assert again.ok and again.succeeded == () and again.plan.outcome == "clean"


def test_nested_folder_is_created_under_an_existing_parent(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-8
    fake_proton.folders.append({"id": "t9", "name": "x", "path": "x"})
    declare(work_account, ("n", FOLDER_SCRIPT, True))
    assert apply_plan(work_account, client, True, False).ok
    create = next(
        c
        for c in fake_proton.calls
        if c.path[-2:] == ("folders", "create") and "--parent" in c.argv
    )
    assert create.argv[-4:] == ["--name", "Y", "--parent", "t9"]


def test_missing_parent_folder_fails_that_action(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-8, BR-10
    fake_proton.outputs["mail settings folders create"] = '{"action": "created"}'
    declare(work_account, ("n", FOLDER_SCRIPT, True))
    report = apply_plan(work_account, client, True, False)
    assert report.failed is not None
    assert report.failed.action == Action("folder", "X/Y")
    assert "parent folder 'X' not found" in report.failed.reason
    assert [a.kind for a in report.not_attempted] == ["label", "create"]


@pytest.mark.parametrize("allow_delete", [False, True])
def test_live_only_filter_is_disabled_unless_delete_is_allowed(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    allow_delete: bool,
) -> None:  # BR-9
    fake_proton.add_filter("a")
    fake_proton.add_filter("extra")
    fake_proton.add_filter("quiet", status=0)
    declare(work_account, ("a", "keep;", True))
    report = apply_plan(work_account, client, True, allow_delete)
    assert report.ok
    if allow_delete:
        assert kinds(report) == ["delete"]
        assert fake_proton.names() == ["a", "quiet"]
    else:
        assert kinds(report) == ["disable"]
        assert fake_proton.names() == ["a", "extra", "quiet"]
    assert report.snapshot is not None


@pytest.mark.parametrize(
    ("failing", "done", "failed", "left"),
    [
        ("filters create", [], "create", ["create", "content", "reorder"]),
        ("filters update", ["create", "create"], "content", ["reorder"]),
        ("filters reorder", ["create", "create", "content"], "reorder", []),
    ],
)
def test_first_failure_stops_the_run_without_rollback(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    failing: str,
    done: list[str],
    failed: str,
    left: list[str],
) -> None:  # BR-10, BR-11
    fake_proton.add_filter("a")
    declare(
        work_account,
        ("n", "keep;", True),
        ("m", "keep;", True),
        ("a", "stop;", True),
    )
    fake_proton.failures[f"mail settings {failing}"] = (3, "boom\nsecond line")
    report = apply_plan(work_account, client, True, False)
    assert not report.ok and report.failed is not None
    assert report.failed.reason.endswith("boom")
    assert "second line" not in report.failed.reason
    assert kinds(report) == done
    assert report.failed.action.kind == failed
    assert [a.kind for a in report.not_attempted] == left
    assert len(write_calls(fake_proton)) == len(done) + 1
    last = run_lines(work_account)[-1]
    assert last["outcome"] == "failed" and last["detail"]["exit_code"] == 3


def test_failure_lists_the_rest_as_not_attempted(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-10
    fake_proton.add_filter("a")
    declare(work_account, ("n", "keep;", True), ("a", "stop;", True))
    fake_proton.failures["mail settings filters create"] = (1, "rejected")
    report = apply_plan(work_account, client, True, False)
    assert report.failed is not None and report.failed.action == Action("create", "n")
    assert report.failed.reason.endswith("rejected")
    assert [(a.kind, a.name) for a in report.not_attempted] == [
        ("content", "a"),
        ("reorder", "order"),
    ]
    assert report.succeeded == () and report.snapshot is not None
    assert fake_proton.names() == ["a"]


def test_every_write_is_audited_without_content(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-11
    fake_proton.add_filter("a")
    declare(work_account, ("n", "keep;", True), ("a", "stop;", True))
    apply_plan(work_account, client, True, False)
    lines = run_lines(work_account)
    assert [(x["kind"], x["outcome"]) for x in lines] == [("write", "ok")] * 3
    assert [(x["detail"]["action"], x["detail"]["name"]) for x in lines] == [
        ("create", "n"),
        ("content", "a"),
        ("reorder", "order"),
    ]
    assert "stop;" not in work_account.audit_log.read_text()


def test_audit_failure_ends_the_run_but_returns_the_report(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-12
    def broken(*_args: object) -> None:
        raise SieveAsCodeError("cannot write audit log")

    fake_proton.add_filter("a")
    declare(work_account, ("n", "keep;", True), ("a", "stop;", True))
    monkeypatch.setattr(apply_module, "record_write", broken)
    report = apply_plan(work_account, client, True, False)
    assert report.audit_error == "cannot write audit log"
    assert report.failed is None and not report.ok
    assert [a.kind for a in report.succeeded] == ["create"]
    assert [a.kind for a in report.not_attempted] == ["content", "reorder"]


def test_flagged_filter_is_written_and_reported(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-14
    declare(work_account, ("n", EXPIRE, True))
    report = apply_plan(work_account, client, True, False)
    assert report.ok and kinds(report) == ["create"]
    assert [(f.name, f.extension) for f in report.plan.flags] == [
        ("n", "vnd.proton.expire")
    ]
    assert fake_proton.names() == ["n"]


def test_reports_are_frozen_values(
    work_account: AccountPaths, client: ProtonClient
) -> None:  # public types
    declare(work_account, ("n", "keep;", True))
    report = apply_plan(work_account, client, False, False)
    assert isinstance(report.plan, PlanResult)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.refused = False  # type: ignore[misc]


@st.composite
def worlds(
    draw: st.DrawFn,
) -> tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]]:
    scripts = st.sampled_from(["keep;", "stop;", "discard;"])

    def rows() -> list[tuple[str, str, bool]]:
        names = draw(st.lists(st.sampled_from("abcdef"), unique=True, max_size=6))
        return [(n, draw(scripts), draw(st.booleans())) for n in names]

    return rows(), rows()


@FRESH
@given(worlds(), st.booleans())
def test_applying_then_planning_again_is_clean(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    world: tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]],
    allow_delete: bool,
) -> None:  # BR-13, NFR-REL.1
    declared, live = world
    paths = dataclasses.replace(
        work_account, backups_dir=work_account.backups_dir / f"r{next(_counter)}"
    )
    fake_proton.filters.clear()
    for name, script, enabled in live:
        fake_proton.add_filter(name, script, 1 if enabled else 0)
    declare(paths, *declared)
    first = apply_plan(paths, client, True, allow_delete)
    assert first.ok
    again = apply_plan(paths, client, True, allow_delete)
    assert again.ok and again.succeeded == () and again.plan.outcome == "clean"
    wanted = [n for n, _, _ in declared]
    assert [n for n in fake_proton.names() if n in wanted] == wanted
