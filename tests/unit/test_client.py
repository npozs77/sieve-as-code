"""BR-1 to BR-21: the `proton` client, against the in-memory fake."""

import hashlib
import subprocess
from collections.abc import Callable
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sieve_as_code.client import TESTED_MINIMUM, ProtonClient, connect, fingerprint_of
from sieve_as_code.model import ClientError
from sieve_as_code.settings import AccountPaths
from tests.fake_proton import FakeProton

PREFIX = ["proton", "--profile", "work", "--no-input", "--output", "json"]
FILTERS = ["mail", "settings", "filters"]


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def plain_client(fake: FakeProton) -> ProtonClient:
    """A client without `connect`, for tests that build their own fake."""
    return ProtonClient("proton", "work")


def every_method(client: ProtonClient) -> list[Callable[[], object]]:
    return [
        client.list_filters,
        lambda: client.get_filter("f1"),
        lambda: client.create_filter("n", "keep;"),
        lambda: client.update_filter("f1", "stop;"),
        lambda: client.enable_filter("f1"),
        lambda: client.disable_filter("f1"),
        lambda: client.reorder_filters(["f1"]),
        client.list_folders,
        client.list_labels,
        lambda: client.create_label("L"),
        lambda: client.create_folder("F"),
        client.list_messages,
        lambda: client.apply_retroactively("f1"),
        lambda: client.delete_filter("f1"),
    ]


# BR-1
def test_commands_carry_profile_no_input_and_json(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    client.list_filters()
    client.create_label("L")
    assert fake_proton.calls[-2].argv[:6] == PREFIX
    assert fake_proton.calls[-1].argv[:6] == PREFIX


def test_version_probe_has_no_profile(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    connect(work_account)
    assert fake_proton.calls[0].argv == ["proton", "--version"]


def test_configured_binary_is_used(
    fake_proton: FakeProton, work_account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIEVE_AS_CODE_PROTON_CLI", "/opt/proton")
    connect(work_account)
    assert {call.argv[0] for call in fake_proton.calls} == {"/opt/proton"}


# BR-2
@given(st.text(), st.text(min_size=1))
def test_script_travels_on_stdin_only(script: str, new_script: str) -> None:
    fake = FakeProton()
    fake.add_filter("old")
    with mock.patch.object(subprocess, "run", fake.run):
        plain_client(fake).create_filter("n", script)
        plain_client(fake).update_filter("f1", new_script)
    create, update = fake.calls
    assert create.stdin == script
    assert create.argv[1:] == PREFIX[1:] + [
        *FILTERS,
        "create",
        "--name",
        "n",
        "--sieve",
        "-",
    ]
    assert update.stdin == new_script
    assert update.argv[1:] == PREFIX[1:] + [*FILTERS, "update", "f1", "--sieve", "-"]


def test_failure_message_never_holds_the_script(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.failures["mail settings filters create"] = (
        1,
        "bad script\nsecond line",
    )
    with pytest.raises(ClientError) as raised:
        client.create_filter("n", "SECRET-SCRIPT")
    assert "SECRET-SCRIPT" not in str(raised.value)
    assert "second line" not in str(raised.value)


# BR-3, BR-4, BR-5
def test_no_call_ever_passes_dry_run(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.add_filter("a")
    for method in every_method(client):
        method()
    assert all("--dry-run" not in call.argv for call in fake_proton.calls)


def test_reads_use_only_read_verbs(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    client = connect(work_account)
    fake_proton.add_filter("a")
    client.list_filters()
    client.get_filter("f1")
    client.list_folders()
    client.list_labels()
    client.list_messages()
    assert {call.verb for call in fake_proton.calls} == {"--version", "get", "list"}


def test_each_method_makes_exactly_one_call(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.add_filter("a")
    for method in every_method(client):
        before = len(fake_proton.calls)
        method()
        assert len(fake_proton.calls) == before + 1


def test_a_failed_write_is_not_retried(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.failures["mail settings filters enable"] = (5, "network")
    before = len(fake_proton.calls)
    with pytest.raises(ClientError):
        client.enable_filter("f1")
    assert len(fake_proton.calls) == before + 1


# BR-6, BR-7
def test_connect_probes_version_then_account(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    connect(work_account)
    assert [call.path for call in fake_proton.calls] == [
        ("--version",),
        ("account", "get"),
    ]


def test_not_signed_in_names_the_login_command(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    fake_proton.signed_in = False
    with pytest.raises(ClientError, match="--profile work account login") as raised:
        connect(work_account)
    assert raised.value.exit_code == 2


def test_wrong_account_stops_all_further_calls(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    connect(work_account)
    fake_proton.account_id = "another-account"
    fake_proton.calls.clear()
    with pytest.raises(ClientError, match="different Proton account"):
        connect(work_account)
    assert len(fake_proton.calls) == 2


# BR-8
@given(st.tuples(*[st.integers(0, 30)] * 3))
def test_warning_iff_below_tested_minimum(version: tuple[int, int, int]) -> None:
    fake = FakeProton(version_output="proton version {}.{}.{}\n".format(*version))
    with (
        mock.patch.object(subprocess, "run", fake.run),
        mock.patch("sys.stderr") as stderr,
    ):
        from sieve_as_code.client import _check_version

        _check_version("proton")
    assert bool(stderr.write.called) == (version < TESTED_MINIMUM)


@pytest.mark.parametrize(
    ("output", "warns"),
    [
        ("proton version 4.2.9\n", True),
        ("proton version 4.3.0\n", False),
        ("proton version 4.3.1\n", False),
        ("proton version 4.10.0\n", False),
        ("proton version 5.0.0\n", False),
        ("dev build\n", True),
        ("", True),
    ],
)
def test_version_boundaries(
    fake_proton: FakeProton,
    work_account: AccountPaths,
    capsys: pytest.CaptureFixture[str],
    output: str,
    warns: bool,
) -> None:
    fake_proton.version_output = output
    connect(work_account)
    assert bool(capsys.readouterr().err) == warns


def test_failing_version_probe_warns_and_continues(
    fake_proton: FakeProton,
    work_account: AccountPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_proton.version_exit = 1
    assert connect(work_account).account == "work"
    assert "cannot read the proton version" in capsys.readouterr().err


def test_old_version_warning_names_detected_and_tested(
    fake_proton: FakeProton,
    work_account: AccountPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_proton.version_output = "proton version 4.2.3\n"
    connect(work_account)
    warning = capsys.readouterr().err
    assert "4.2.3" in warning
    assert "4.3.0" in warning


# BR-9
@given(st.text(min_size=1))
def test_fingerprint_is_twelve_hex_of_sha256(account_id: str) -> None:
    result = fingerprint_of(account_id)
    assert result == hashlib.sha256(account_id.encode()).hexdigest()[:12]
    assert len(result) == 12
    assert result == result.lower()


def test_first_use_creates_an_owner_only_marker(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    client = connect(work_account)
    marker = work_account.account_marker
    assert marker.read_text() == client.fingerprint + "\n"
    assert marker.stat().st_mode & 0o777 == 0o600
    assert marker.parent.stat().st_mode & 0o777 == 0o700


def test_matching_marker_passes_again(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    first = connect(work_account)
    assert connect(work_account) == first


def test_mismatching_marker_is_refused_and_left_unchanged(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    work_account.account_marker.parent.mkdir(parents=True)
    work_account.account_marker.write_text("aaaaaaaaaaaa\n")
    with pytest.raises(ClientError, match="aaaaaaaaaaaa"):
        connect(work_account)
    assert work_account.account_marker.read_text() == "aaaaaaaaaaaa\n"


def test_unusable_marker_location_is_a_client_error(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    work_account.account_marker.parent.parent.mkdir(parents=True)
    work_account.account_marker.parent.write_text("a file, not a directory")
    with pytest.raises(ClientError, match="account.id"):
        connect(work_account)


# BR-10
@pytest.mark.parametrize(
    ("code", "hint"),
    [
        (1, "command line was wrong"),
        (3, "no such thing"),
        (4, "use the id a listing printed"),
        (5, "check with a list before repeating"),
        (6, "confirmation policy"),
        (7, "proton report"),
        (42, "unexpected failure"),
    ],
)
def test_exit_codes_carry_a_hint_and_the_code(
    client: ProtonClient, fake_proton: FakeProton, code: int, hint: str
) -> None:
    fake_proton.failures["mail settings filters enable"] = (code, "")
    with pytest.raises(ClientError, match=hint) as raised:
        client.enable_filter("f1")
    assert raised.value.exit_code == code
    assert "mail settings filters enable" in str(raised.value)


def test_stderr_first_line_is_capped_at_200_characters(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.failures["mail settings filters enable"] = (1, "x" * 500)
    with pytest.raises(ClientError) as raised:
        client.enable_filter("f1")
    assert "x" * 200 in str(raised.value)
    assert "x" * 201 not in str(raised.value)


def test_arguments_are_not_in_the_command_path(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    with pytest.raises(ClientError) as raised:
        client.get_filter("a-filter-name")
    assert "a-filter-name" not in str(raised.value)


# BR-11, BR-13
def malformed(key: str) -> list[str]:
    return [
        "not json",
        "[]",
        "{}",
        f'{{"{key}": [1]}}',
        f'{{"{key}": [], "has_more": true}}',
    ]


LISTINGS: list[tuple[str, str, Callable[[ProtonClient], object]]] = [
    ("mail settings filters list", "filters", lambda c: c.list_filters()),
    ("mail settings folders list", "folders", lambda c: c.list_folders()),
    ("mail settings labels list", "labels", lambda c: c.list_labels()),
    ("mail messages list", "messages", lambda c: c.list_messages()),
]


@pytest.mark.parametrize(("path", "key", "call"), LISTINGS)
def test_malformed_listings_are_client_errors(
    client: ProtonClient,
    fake_proton: FakeProton,
    path: str,
    key: str,
    call: Callable[[ProtonClient], object],
) -> None:
    for output in malformed(key):
        fake_proton.outputs[path] = output
        with pytest.raises(ClientError, match="unexpected proton output") as raised:
            call(client)
        assert path in str(raised.value)
        assert output not in str(raised.value)


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        "[]",
        "{}",
        '{"id": "a", "name": "n", "status": 1}',
        '{"id": "a", "name": "n", "status": "x", "sieve": ""}',
        '{"id": "", "name": "n", "status": 1, "sieve": ""}',
    ],
)
def test_malformed_filter_detail_is_a_client_error(
    client: ProtonClient, fake_proton: FakeProton, output: str
) -> None:
    fake_proton.outputs["mail settings filters get"] = output
    with pytest.raises(ClientError, match="unexpected proton output"):
        client.get_filter("a")


@pytest.mark.parametrize(
    "output", ["not json", "[]", "{}", '{"ids": []}', '{"ids": [1]}', '{"ids": [""]}']
)
def test_malformed_create_response_is_a_client_error(
    client: ProtonClient, fake_proton: FakeProton, output: str
) -> None:
    fake_proton.outputs["mail settings filters create"] = output
    with pytest.raises(ClientError, match="unexpected proton output"):
        client.create_filter("n", "keep;")


@pytest.mark.parametrize("output", ["not json", "[]", "{}", '{"id": 5}', '{"id": ""}'])
def test_malformed_account_response_is_a_client_error(
    fake_proton: FakeProton, work_account: AccountPaths, output: str
) -> None:
    fake_proton.outputs["account get"] = output
    with pytest.raises(ClientError, match="unexpected proton output"):
        connect(work_account)


# BR-12
def test_missing_binary_names_the_variable(
    fake_proton: FakeProton, work_account: AccountPaths
) -> None:
    fake_proton.missing = True
    with pytest.raises(ClientError, match="SIEVE_AS_CODE_PROTON_CLI"):
        connect(work_account)


@pytest.mark.parametrize(
    ("path", "call", "seconds"),
    [
        ("mail settings filters list", lambda c: c.list_filters(), 30),
        ("mail messages list", lambda c: c.list_messages(), 120),
    ],
)
def test_timeout_names_the_seconds(
    client: ProtonClient,
    fake_proton: FakeProton,
    path: str,
    call: Callable[[ProtonClient], object],
    seconds: int,
) -> None:
    fake_proton.hangs.add(path)
    with pytest.raises(ClientError, match=f"within {seconds}s"):
        call(client)


# BR-14, BR-15
def test_list_filters_keeps_order_and_maps_status(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.add_filter("b", status=1)
    fake_proton.add_filter("a", status=0)
    refs = client.list_filters()
    assert [(r.name, r.enabled) for r in refs] == [("b", True), ("a", False)]
    assert [r.live_id for r in refs] == ["f1", "f2"]


def test_an_empty_listing_is_an_empty_list(client: ProtonClient) -> None:
    assert client.list_filters() == []


def test_get_filter_returns_the_script_verbatim(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    script = 'require ["fileinto"];\r\n# ünï\n'
    fake_proton.add_filter("n", sieve=script, status=0)
    result = client.get_filter("f1")
    assert (result.name, result.raw_sieve, result.enabled, result.live_id) == (
        "n",
        script,
        False,
        "f1",
    )


def test_list_then_get_reproduces_a_filter(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    created = client.create_filter("n", "keep;", enabled=False)
    ref = client.list_filters()[0]
    assert client.get_filter(ref.live_id).live_id == created == ref.live_id


# BR-16, BR-17, BR-18
def test_create_returns_id_and_marks_disabled_only_when_asked(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    client.create_filter("on", "keep;")
    client.create_filter("off", "keep;", enabled=False)
    on, off = fake_proton.calls[-2:]
    assert "--disabled" not in on.argv
    assert off.argv[-1] == "--disabled"
    assert [e["status"] for e in fake_proton.filters] == [1, 0]


def test_delete_always_confirms_and_enable_disable_mirror(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.add_filter("a")
    client.disable_filter("f1")
    assert fake_proton.filters[0]["status"] == 0
    client.enable_filter("f1")
    assert fake_proton.filters[0]["status"] == 1
    client.delete_filter("f1")
    assert fake_proton.calls[-1].argv[-2:] == ["f1", "--yes"]
    assert fake_proton.filters == []


def test_reorder_is_one_call_with_ids_in_order(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    for name in "abc":
        fake_proton.add_filter(name)
    before = len(fake_proton.calls)
    client.reorder_filters(["f3", "f1"])
    assert len(fake_proton.calls) == before + 1
    assert fake_proton.calls[-1].argv[-2:] == ["f3", "f1"]
    assert fake_proton.names() == ["c", "a", "b"]


def test_reorder_without_ids_is_refused(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    before = len(fake_proton.calls)
    with pytest.raises(ValueError):
        client.reorder_filters([])
    assert len(fake_proton.calls) == before


# BR-19
def test_target_path_falls_back_to_name(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.labels.append({"id": "l1", "name": "Work"})
    fake_proton.folders.append({"id": "d1", "name": "Sub", "path": "Top/Sub"})
    assert [(t.id, t.name, t.path) for t in client.list_labels()] == [
        ("l1", "Work", "Work")
    ]
    assert [(t.id, t.name, t.path) for t in client.list_folders()] == [
        ("d1", "Sub", "Top/Sub")
    ]


def test_label_and_folder_creates_mirror_each_other(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    client.create_label("L")
    client.create_folder("F")
    label, folder = fake_proton.calls[-2:]
    assert label.argv[6:] == ["mail", "settings", "labels", "create", "--name", "L"]
    assert folder.argv[6:] == ["mail", "settings", "folders", "create", "--name", "F"]


def test_parent_is_passed_only_when_given(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    client.create_folder("Top")
    client.create_folder("Sub", parent_id="t1")
    assert "--parent" not in fake_proton.calls[-2].argv
    assert fake_proton.calls[-1].argv[-2:] == ["--parent", "t1"]
    assert [t.path for t in client.list_folders()] == ["Top", "Top/Sub"]


# BR-20, BR-21
def test_messages_ask_for_every_folder_and_filter_by_recipient_only_when_given(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    fake_proton.messages.append({"id": "m1", "labels": ["0"]})
    assert client.list_messages() == [{"id": "m1", "labels": ["0"]}]
    client.list_messages(to="me@example.org")
    plain, filtered = fake_proton.calls[-2:]
    assert plain.argv[6:] == [
        "mail",
        "messages",
        "list",
        "--folder",
        "all",
        "--limit",
        "0",
    ]
    assert filtered.argv[-2:] == ["--to", "me@example.org"]


def test_apply_retroactively_is_one_call(
    client: ProtonClient, fake_proton: FakeProton
) -> None:
    before = len(fake_proton.calls)
    client.apply_retroactively("f1")
    assert len(fake_proton.calls) == before + 1
    assert fake_proton.calls[-1].argv[-2:] == ["apply", "f1"]


def test_unrunnable_binary_is_a_client_error(
    work_account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **options: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(subprocess, "run", refuse)
    with pytest.raises(ClientError, match="cannot run `proton`: Permission denied"):
        connect(work_account)
