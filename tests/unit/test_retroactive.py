"""Unit 8 BR-1 to BR-29: preview, run, status and audit of retroactive runs."""

import dataclasses
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sieve_as_code._backup import SNAPSHOT_TIME, checksum
from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._model import (
    BackupError,
    ClientError,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code._retroactive import (
    RetroReport,
    audit_all,
    preview,
    run,
    status,
)
from sieve_as_code._settings import AccountPaths, account_paths
from tests.fake_proton import FakeProton

FRESH = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
NEWS = (
    'require ["fileinto"];\n'
    'if address :domain "from" "news.example" { fileinto "News"; }\n'
)
WRITE_VERBS = {"create", "update", "delete", "enable", "disable", "reorder"}
NOW = 1_700_000_000  # 2023-11-14 UTC


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    fake_proton.folders.append({"id": "F1", "name": "News", "path": "News"})
    fake_proton.folders.append({"id": "F2", "name": "Sub", "path": "News/Sub"})
    fake_proton.labels.append({"id": "L1", "name": "Receipts"})
    return connect(work_account)


def mail(fake: FakeProton, mid: str, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": mid,
        "conversation_id": f"c{mid}",
        "subject": f"Subject {mid}",
        "from_name": "Sender",
        "from_address": f"{mid}@news.example",
        "time": NOW,
        "unread": 1,
        "num_attachments": 0,
        "labels": ["5", "15", "0"],
    }
    row.update(fields)
    fake.messages.append(row)
    return row


def calls(fake: FakeProton, verb: str) -> list[Any]:
    return [c for c in fake.calls if c.verb == verb]


def audit_lines(paths: AccountPaths) -> list[dict[str, Any]]:
    if not paths.audit_log.exists():
        return []
    return [json.loads(line) for line in paths.audit_log.read_text().splitlines()]


def snapshots(paths: AccountPaths) -> list[Path]:
    return sorted(paths.retroactive_dir.glob("*.json"))


def declare(paths: AccountPaths, name: str, sieve: str, enabled: bool = True) -> None:
    paths.filters_dir.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "raw_sieve": sieve, "enabled": enabled}
    (paths.filters_dir / f"{name}.yaml").write_text(yaml.safe_dump(data))


def started(fake: FakeProton, paths: AccountPaths, client: ProtonClient) -> RetroReport:
    """Seed `News` with three matching inbox messages and run it."""
    fake.add_filter("News", NEWS)
    for mid in ("m1", "m2", "m3"):
        mail(fake, mid)
    return run(paths, client, "News", "News", "tidy up")


# BR-1


@pytest.mark.parametrize(
    "call",
    [
        lambda p, c: preview(p, c, "News"),
        lambda p, c: run(p, c, "News", "News", "r"),
        lambda p, c: status(p, c),
        lambda p, c: audit_all(p, c),
    ],
)
def test_other_account_or_unconnected_client_is_refused_untouched(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths, call: Any
) -> None:
    other = account_paths("other")
    before = len(fake_proton.calls)
    with pytest.raises(ValidationError):
        call(other, client)
    with pytest.raises(ValidationError):
        call(work_account, ProtonClient("proton", "work"))
    assert len(fake_proton.calls) == before
    assert audit_lines(other) == [] and not other.retroactive_dir.exists()


# BR-2


def test_unknown_and_disabled_filters_are_refused(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("Off", NEWS, status=0)
    with pytest.raises(ValidationError, match="no live filter named 'Nope'"):
        preview(work_account, client, "Nope")
    with pytest.raises(ValidationError, match="'Off' is disabled"):
        run(work_account, client, "Off", "Off", "r")
    assert not calls(fake_proton, "apply")


def test_duplicate_live_names_are_addressed_by_their_numbered_name(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("Rule", "stop;")
    fake_proton.add_filter("Rule", NEWS)
    mail(fake_proton, "m1")
    assert len(preview(work_account, client, "Rule (1)").entries) == 1
    assert preview(work_account, client, "Rule").entries == ()


# BR-3, BR-16


def test_preview_reads_only_and_leaves_no_trace(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "m1")
    preview(work_account, client, "News")
    audit_all(work_account, client)
    verbs = {c.verb for c in fake_proton.calls if c.path[0] == "mail"}
    assert verbs <= {"list", "get"}
    assert not work_account.retroactive_dir.exists()
    assert [line["outcome"] for line in audit_lines(work_account)] == ["audited"]


@pytest.mark.parametrize(
    "bad",
    [
        {"id": 5},
        {"subject": None},
        {"time": "now"},
        {"labels": "0"},
        {"labels": [0]},
    ],
)
def test_a_malformed_message_row_is_a_client_error(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    bad: dict[str, Any],
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "m1", **bad)
    with pytest.raises(ClientError, match="unexpected proton output"):
        preview(work_account, client, "News")


def test_a_row_missing_a_field_is_a_client_error(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    del mail(fake_proton, "m1")["subject"]
    with pytest.raises(ClientError, match="unexpected proton output"):
        preview(work_account, client, "News")


def test_an_absent_sender_name_counts_as_empty(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    del mail(fake_proton, "m1")["from_name"]
    shown = preview(work_account, client, "News")
    assert [e.message_id for e in shown.entries] == ["m1"]


def test_a_failing_listing_propagates(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    fake_proton.failures["mail messages list"] = (1, "boom")
    with pytest.raises(ClientError):
        preview(work_account, client, "News")


# BR-4, BR-5, BR-14


def test_spam_is_excluded_and_counted_trash_is_not(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "spam", labels=["5", "4"])
    mail(fake_proton, "trash", labels=["5", "3"])
    shown = preview(work_account, client, "News")
    assert [e.message_id for e in shown.entries] == ["trash"]
    assert shown.spam_excluded == 1


@pytest.mark.parametrize(
    ("labels", "location"),
    [
        (["5", "0"], "Inbox"),
        (["5", "3"], "Trash"),
        (["5", "6"], "Archive"),
        (["5", "7"], "Sent"),
        (["5", "8"], "Drafts"),
        (["5", "F2"], "News/Sub"),
        (["5", "0", "7"], "Inbox"),
        (["5"], "unknown"),
    ],
)
def test_location_comes_from_the_labels(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    labels: list[str],
    location: str,
) -> None:
    fake_proton.add_filter("L", 'if true { fileinto "Receipts"; }')
    mail(fake_proton, "m1", labels=labels)
    assert preview(work_account, client, "L").entries[0].location == location


def test_entries_carry_the_preview_fields_newest_first(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "b", time=NOW)
    mail(fake_proton, "a", time=NOW)
    mail(fake_proton, "c", time=NOW + 86400)
    shown = preview(work_account, client, "News")
    assert [e.message_id for e in shown.entries] == ["c", "a", "b"]
    first = shown.entries[0]
    assert (first.date, first.sender, first.subject) == (
        "2023-11-15",
        "c@news.example",
        "Subject c",
    )
    assert (first.location, first.actions) == ("Inbox", ("move: News",))
    assert shown.previewable and shown.reason is None and not shown.approximate


def test_an_impossible_timestamp_is_shown_as_unknown(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "m1", time=10**30)
    assert preview(work_account, client, "News").entries[0].date == "unknown"


def test_nothing_changes_for_a_message_already_in_place(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "there", labels=["5", "F1"])
    mail(fake_proton, "elsewhere", labels=["5", "6"])
    shown = preview(work_account, client, "News")
    assert [e.message_id for e in shown.entries] == ["elsewhere"]


# BR-9, BR-10, BR-11


def test_system_folders_custom_folders_and_labels_resolve_case_insensitively(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    script = (
        'if true { fileinto "ARCHIVE"; fileinto "news/sub"; '
        'fileinto "receipts"; fileinto "Spam"; }'
    )
    fake_proton.add_filter("All", script)
    mail(fake_proton, "m1")
    actions = preview(work_account, client, "All").entries[0].actions
    assert actions == (
        "move: Archive",
        "move: News/Sub",
        "label: Receipts",
        "move: Spam",
    )


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ('fileinto "Nowhere";', "target 'Nowhere' does not exist"),
        ("size :over 1M;", "size at line 1"),
        ('if header :matches "to" "a*" { stop; }', "to test at line 1"),
    ],
)
def test_unsupported_filters_are_not_previewable_never_guessed(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    script: str,
    reason: str,
) -> None:
    fake_proton.add_filter("X", script)
    mail(fake_proton, "m1")
    shown = preview(work_account, client, "X")
    assert (shown.previewable, shown.reason, shown.entries) == (False, reason, ())
    assert not [c for c in fake_proton.calls if "--to" in c.argv]


def test_recipient_tests_search_once_per_key_and_are_approximate(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter(
        "Team",
        'if anyof(address :is "to" "team@x.org", header :contains "to" "TEAM@x.org") '
        '{ fileinto "News"; }',
    )
    mail(fake_proton, "hit")
    mail(fake_proton, "miss")
    fake_proton.recipients = {"hit": ["Team@X.org"], "miss": ["me@x.org"]}
    shown = preview(work_account, client, "Team")
    assert [e.message_id for e in shown.entries] == ["hit"]
    assert shown.approximate
    searches = [c for c in fake_proton.calls if "--to" in c.argv]
    assert len(searches) == 1


def test_eleven_recipient_keys_are_not_previewable(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    keys = ", ".join(f'"k{n}"' for n in range(11))
    fake_proton.add_filter("Many", f'if header :is "to" [{keys}] {{ stop; }}')
    shown = preview(work_account, client, "Many")
    assert shown.reason == "recipient keys at line 1"


# BR-12, BR-13, BR-14


def test_flags_and_expire_actions(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    script = (
        'require ["imap4flags", "vnd.proton.expire"];\n'
        'addflag ["\\\\Seen", "\\\\Flagged"]; expire "day" "30";'
    )
    fake_proton.add_filter("F", script)
    mail(fake_proton, "fresh")
    mail(fake_proton, "read", unread=0)
    mail(fake_proton, "starred", unread=0, labels=["5", "10"])
    mail(fake_proton, "done", unread=0, labels=["5", "10"])
    fake_proton.messages[-1]["labels"] = ["5", "10"]
    entries = {e.message_id: e for e in preview(work_account, client, "F").entries}
    assert set(entries) == {"fresh", "read"}
    assert entries["fresh"].actions == ("read", "star", "expire 30 day")
    assert entries["read"].actions == ("read", "star", "expire 30 day")


def test_expire_alone_never_counts_a_message(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("E", 'expire "day" "30";')
    mail(fake_proton, "m1")
    assert preview(work_account, client, "E").entries == ()


def test_a_label_already_present_changes_nothing(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("L", 'if true { fileinto "Receipts"; }')
    mail(fake_proton, "has", labels=["5", "0", "L1"])
    mail(fake_proton, "lacks")
    shown = preview(work_account, client, "L")
    assert [e.message_id for e in shown.entries] == ["lacks"]
    assert shown.entries[0].actions == ("label: Receipts",)


MODEL_SCRIPT = (
    'require ["fileinto", "imap4flags"];\n'
    'if true { fileinto "News"; fileinto "Receipts"; '
    'addflag ["\\\\Seen", "\\\\Flagged"]; }'
)
FOLDERS = ["0", "3", "6", "F1", "F2"]


def applied(labels: list[str]) -> list[str]:
    """Apply MODEL_SCRIPT's actions to a message's labels."""
    kept = [label for label in labels if label not in {"0", "3", "6", "7", "8", "F2"}]
    return sorted({*kept, "F1", "L1", "10"})


@FRESH
@given(
    folder=st.sampled_from(FOLDERS),
    label=st.booleans(),
    starred=st.booleans(),
    unread=st.booleans(),
)
def test_an_entry_exists_exactly_when_an_action_changes_the_message(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    folder: str,
    label: bool,
    starred: bool,
    unread: bool,
) -> None:  # BR-14
    fake_proton.filters.clear()
    fake_proton.messages.clear()
    fake_proton.add_filter("M", MODEL_SCRIPT)
    labels = ["5", folder, *(["L1"] if label else []), *(["10"] if starred else [])]
    row = mail(fake_proton, "m1", labels=labels, unread=int(unread))
    changes = folder != "F1" or not label or not starred or unread
    entries = preview(work_account, client, "M").entries
    assert bool(entries) == changes
    row["labels"], row["unread"] = applied(labels), 0
    assert preview(work_account, client, "M").entries == ()


# BR-15


def test_declared_differs_warns_without_blocking(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    assert not preview(work_account, client, "News").declared_differs
    declare(work_account, "News", NEWS + "\n\n")
    assert not preview(work_account, client, "News").declared_differs
    declare(work_account, "News", "keep;")
    assert preview(work_account, client, "News").declared_differs
    declare(work_account, "News", NEWS, enabled=False)
    assert preview(work_account, client, "News").declared_differs


def test_an_invalid_local_file_is_an_error(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    work_account.filters_dir.mkdir(parents=True)
    (work_account.filters_dir / "bad.yaml").write_text("- not a mapping\n")
    with pytest.raises(ValidationError):
        preview(work_account, client, "News")


# BR-17, BR-18


def test_nothing_to_do_needs_no_confirmation_and_writes_nothing(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    report = run(work_account, client, "News", "", "")
    assert report.ok and not report.started and not report.refused
    assert not calls(fake_proton, "apply") and audit_lines(work_account) == []
    assert not work_account.retroactive_dir.exists()


@pytest.mark.parametrize(
    ("typed", "reason"), [("news", "why"), ("News", "  "), ("", "")]
)
def test_a_wrong_name_or_blank_reason_is_refused(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    typed: str,
    reason: str,
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "m1")
    report = run(work_account, client, "News", typed, reason)
    assert report.refused and not report.ok and not report.started
    assert len(report.preview.entries) == 1
    assert not calls(fake_proton, "apply") and not work_account.retroactive_dir.exists()
    [line] = audit_lines(work_account)
    assert (line["kind"], line["outcome"]) == ("check", "refused")
    assert line["detail"] == {"command": "apply-retroactive", "name": "News"}


def test_a_failing_audit_on_refusal_is_raised(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "m1")
    work_account.audit_log.mkdir(parents=True)
    with pytest.raises(SieveAsCodeError, match="cannot write audit log"):
        run(work_account, client, "News", "x", "r")


# BR-19


def test_a_not_previewable_run_proceeds_without_a_snapshot(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("X", "size :over 1M;")
    report = run(work_account, client, "X", "X", "trust me")
    assert report.ok and report.started and report.snapshot is None
    assert len(calls(fake_proton, "apply")) == 1
    assert audit_lines(work_account)[0]["detail"]["messages"] is None
    assert not work_account.retroactive_dir.exists()


# BR-20, BR-21, BR-22, BR-23, BR-25


def test_a_confirmed_run_snapshots_then_applies_once_and_audits(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    report = started(fake_proton, work_account, client)
    assert report.ok and report.started and report.failed is None
    [apply] = calls(fake_proton, "apply")
    assert apply.argv[-1] == "f1"
    [path] = snapshots(work_account)
    assert report.snapshot == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    document = json.loads(path.read_text())
    assert set(document) == {
        "format",
        "created",
        "account",
        "fingerprint",
        "filter",
        "script_sha256",
        "messages",
        "checksum",
    }
    assert document["messages"] == ["m1", "m2", "m3"] and document["filter"] == "News"
    assert document["fingerprint"] == client.fingerprint
    assert document["checksum"] == checksum(document)
    text = path.read_text()
    assert (
        "news.example" not in text and "Subject" not in text and "fileinto" not in text
    )
    [line] = audit_lines(work_account)
    assert (line["kind"], line["outcome"]) == ("write", "started")
    assert line["detail"] == {
        "command": "apply-retroactive",
        "name": "News",
        "reason": "tidy up",
        "messages": 3,
    }


def test_an_unwritable_snapshot_stops_before_anything_starts(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    work_account.retroactive_dir.parent.mkdir(parents=True)
    work_account.retroactive_dir.write_text("in the way")
    fake_proton.add_filter("News", NEWS)
    mail(fake_proton, "m1")
    with pytest.raises(BackupError):
        run(work_account, client, "News", "News", "r")
    assert not calls(fake_proton, "apply") and audit_lines(work_account) == []


def test_a_failing_apply_keeps_the_snapshot_and_is_audited(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.failures["mail settings filters apply"] = (4, "server said no")
    report = started(fake_proton, work_account, client)
    assert not report.ok and not report.started
    assert report.failed is not None and "server said no" in report.failed
    assert len(snapshots(work_account)) == 1
    [line] = audit_lines(work_account)
    assert line["outcome"] == "failed" and line["detail"]["exit_code"] == 4


def test_a_failing_audit_never_replaces_the_report(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    work_account.audit_log.mkdir(parents=True)
    report = started(fake_proton, work_account, client)
    assert report.started and not report.ok
    assert report.audit_error is not None and "audit log" in report.audit_error
    assert len(calls(fake_proton, "apply")) == 1


def test_results_are_frozen(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    report = started(fake_proton, work_account, client)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.started = False  # type: ignore[misc]


# BR-24


def snapshot_name(age: timedelta) -> str:
    return (datetime.now(UTC) - age).strftime(SNAPSHOT_TIME)


def old_snapshots(paths: AccountPaths) -> tuple[Path, Path, Path, Path]:
    paths.retroactive_dir.mkdir(parents=True)
    old = paths.retroactive_dir / snapshot_name(timedelta(days=11))
    recent = paths.retroactive_dir / snapshot_name(timedelta(days=9))
    foreign = paths.retroactive_dir / "notes.json"
    folder = paths.retroactive_dir / snapshot_name(timedelta(days=30))
    for item in (old, recent, foreign):
        item.write_text("{}")
    folder.mkdir()
    return old, recent, foreign, folder


def test_snapshots_over_ten_days_old_are_pruned_and_audited(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    old, recent, foreign, folder = old_snapshots(work_account)
    report = started(fake_proton, work_account, client)
    assert report.prune_error is None and report.ok
    assert not old.exists()
    assert recent.exists() and foreign.exists() and folder.is_dir()
    assert report.snapshot is not None and report.snapshot.exists()
    prune = audit_lines(work_account)[-1]
    assert (prune["kind"], prune["outcome"]) == ("write", "prune")
    assert prune["detail"] == {"removed": 1, "kept": 2}


def test_nothing_is_pruned_when_nothing_is_old(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    started(fake_proton, work_account, client)
    assert [line["outcome"] for line in audit_lines(work_account)] == ["started"]


def test_a_failed_removal_is_reported_without_failing_the_run(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, *_ = old_snapshots(work_account)
    real = Path.unlink

    def refuse(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == old:
            raise PermissionError(13, "Permission denied")
        real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)
    report = started(fake_proton, work_account, client)
    assert report.ok and report.started
    assert report.prune_error is not None and "Permission denied" in report.prune_error
    assert old.exists()


def test_a_failing_prune_audit_is_reported(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_snapshots(work_account)
    real = os.write
    writes: list[int] = []

    def second_fails(fd: int, data: bytes) -> int:
        writes.append(fd)
        if len(writes) == 2:
            raise OSError(28, "No space left on device")
        return real(fd, data)

    monkeypatch.setattr(os, "write", second_fails)
    report = started(fake_proton, work_account, client)
    assert report.ok
    assert report.prune_error is not None and "No space left" in report.prune_error


# BR-26, BR-27


def moved_to_news(fake: FakeProton, mid: str) -> None:
    row = next(r for r in fake.messages if r["id"] == mid)
    row["labels"] = ["5", "F1"]


def test_status_reports_done_pending_and_unexpected(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    report = started(fake_proton, work_account, client)
    moved_to_news(fake_proton, "m1")
    fake_proton.messages[:] = [m for m in fake_proton.messages if m["id"] != "m3"]
    mail(fake_proton, "m4")
    result = status(work_account, client)
    assert result.snapshot == report.snapshot and result.filter == "News"
    assert result.done == 1
    assert [e.message_id for e in result.pending] == ["m2"]
    assert [(u.message_id, u.reason) for u in result.unexpected] == [
        ("m3", "gone"),
        ("m4", "new"),
    ]
    assert not result.script_changed


def test_status_after_completion_and_after_a_script_change(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    started(fake_proton, work_account, client)
    for mid in ("m1", "m2", "m3"):
        moved_to_news(fake_proton, mid)
    done = status(work_account, client)
    assert (done.done, done.pending, done.unexpected) == (3, (), ())
    fake_proton.filters[0]["sieve"] = NEWS + "\n\n"
    assert not status(work_account, client).script_changed
    fake_proton.filters[0]["sieve"] = NEWS + 'fileinto "Receipts";'
    assert status(work_account, client).script_changed


def test_status_takes_a_name_a_path_or_the_latest(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    report = started(fake_proton, work_account, client)
    assert report.snapshot is not None
    assert status(work_account, client, report.snapshot).snapshot == report.snapshot
    assert (
        status(work_account, client, report.snapshot.name).snapshot == report.snapshot
    )
    stem = report.snapshot.stem
    assert status(work_account, client, stem).snapshot == report.snapshot
    later = work_account.retroactive_dir / "99990101T000000000000Z.json"
    later.write_text(report.snapshot.read_text())
    assert status(work_account, client).snapshot == later


def test_status_without_snapshots_is_a_backup_error(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    with pytest.raises(BackupError, match="no retroactive snapshots"):
        status(work_account, client)
    work_account.retroactive_dir.mkdir(parents=True)
    with pytest.raises(BackupError, match="no retroactive snapshots"):
        status(work_account, client)
    with pytest.raises(BackupError, match="no retroactive snapshot ghost"):
        status(work_account, client, "ghost")


def rewrite(path: Path, **changes: Any) -> None:
    """Change a snapshot field and re-seal it with a valid checksum."""
    document = json.loads(path.read_text())
    document.update(changes)
    document["checksum"] = checksum(document)
    path.write_text(json.dumps(document))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"fingerprint": "other"}, "different Proton account"),
        ({"format": 2}, "unsupported snapshot format"),
        ({"messages": "m1"}, "wrong type"),
        ({"messages": [1]}, "wrong type"),
        ({"filter": 5}, "wrong type"),
    ],
)
def test_status_refuses_a_foreign_or_malformed_snapshot(
    fake_proton: FakeProton,
    client: ProtonClient,
    work_account: AccountPaths,
    change: dict[str, Any],
    message: str,
) -> None:
    report = started(fake_proton, work_account, client)
    assert report.snapshot is not None
    rewrite(report.snapshot, **change)
    with pytest.raises(BackupError, match=message):
        status(work_account, client)


def test_status_refuses_an_altered_or_unreadable_snapshot(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    report = started(fake_proton, work_account, client)
    path = report.snapshot
    assert path is not None
    original = path.read_text()
    path.write_text(original.replace("m1", "m9"))
    with pytest.raises(BackupError, match="checksum mismatch"):
        status(work_account, client)
    for text, message in [
        ("not json", "not valid JSON"),
        ("[]", "not a snapshot"),
        ('{"format": 1}', "unexpected or missing fields"),
    ]:
        path.write_text(text)
        with pytest.raises(BackupError, match=message):
            status(work_account, client)
    path.write_text(original)
    path.chmod(0)
    with pytest.raises(BackupError, match="cannot read"):
        status(work_account, client)
    path.chmod(0o600)


def test_status_needs_an_enabled_previewable_filter(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    started(fake_proton, work_account, client)
    fake_proton.filters[0]["sieve"] = "size :over 1M;"
    with pytest.raises(ValidationError, match="not previewable: size at line 1"):
        status(work_account, client)
    fake_proton.filters[0]["status"] = 0
    with pytest.raises(ValidationError, match="disabled"):
        status(work_account, client)
    fake_proton.filters.clear()
    with pytest.raises(ValidationError, match="no live filter named 'News'"):
        status(work_account, client)


# BR-28


def test_audit_all_counts_each_enabled_filter_over_one_listing(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("News", NEWS)
    fake_proton.add_filter("Off", NEWS, status=0)
    fake_proton.add_filter("Odd", "size :over 1M;")
    fake_proton.add_filter(
        "Team", 'if header :contains "to" "t@x" { fileinto "News"; }'
    )
    mail(fake_proton, "m1")
    mail(fake_proton, "m2")
    fake_proton.recipients = {"m2": ["t@x"]}
    rows = {r.name: r for r in audit_all(work_account, client).rows}
    assert set(rows) == {"News", "Odd", "Team"}
    assert rows["News"].changes == 2 and rows["News"].note is None
    assert rows["Odd"].changes is None and rows["Odd"].note == (
        "not previewable: size at line 1"
    )
    assert rows["Team"].changes == 1 and rows["Team"].note is not None
    plain = [c for c in fake_proton.calls if c.path[-2:] == ("messages", "list")]
    assert len([c for c in plain if "--to" not in c.argv]) == 1
    [line] = audit_lines(work_account)
    assert (line["kind"], line["outcome"]) == ("check", "audited")
    assert line["detail"] == {"filters": 3, "not_previewable": 1, "approximate": 1}


def test_audit_all_with_no_enabled_filter_reads_no_messages(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    fake_proton.add_filter("Off", NEWS, status=0)
    assert audit_all(work_account, client).rows == ()
    assert not [c for c in fake_proton.calls if c.path[-2:] == ("messages", "list")]
    assert audit_lines(work_account)[0]["detail"]["filters"] == 0


# BR-29


def test_no_private_text_reaches_the_audit_log_or_errors(
    fake_proton: FakeProton, client: ProtonClient, work_account: AccountPaths
) -> None:
    started(fake_proton, work_account, client)
    audit_all(work_account, client)
    text = work_account.audit_log.read_text()
    for private in ("news.example", "Subject", "Sender", "fileinto", "m1@"):
        assert private not in text
    fake_proton.filters[0]["sieve"] = 'if header :contains "subject" "secret" { size; }'
    with pytest.raises(ValidationError) as raised:
        status(work_account, client)
    assert "secret" not in str(raised.value)
