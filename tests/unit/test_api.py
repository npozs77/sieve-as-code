"""Unit 9 BR-1 to BR-5, BR-16, BR-17: the public API."""

import dataclasses
import inspect
import pkgutil
import tomllib
from pathlib import Path
from typing import Any

import pytest

import sieve_as_code as api
from sieve_as_code._model import Filter, FilterOrder
from sieve_as_code._settings import AccountPaths
from tests.fake_proton import FakeProton

FUNCTIONS = [
    "apply",
    "apply_retroactive",
    "backup",
    "backup_diff",
    "discover",
    "import_live",
    "import_sieve_files",
    "load_declared",
    "plan",
    "restore",
    "retroactive_audit",
    "retroactive_preview",
    "retroactive_status",
    "validate_declared",
]
SUBJECTS = {"name", "sources", "a", "b", "ref", "declared"}
WRITE_VERBS = {"create", "update", "delete", "enable", "disable", "reorder"}
OLD_SNAPSHOTS = ("20200101T000000000000Z.json", "20200102T000000000000Z.json")


@pytest.fixture
def account(
    fake_proton: FakeProton, work_account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> AccountPaths:
    monkeypatch.setenv("SIEVE_AS_CODE_ACCOUNT", "work")
    return work_account


def declare(paths: AccountPaths, **scripts: str) -> None:
    paths.filters_dir.mkdir(parents=True, exist_ok=True)
    for name, script in scripts.items():
        (paths.filters_dir / f"{name}.yaml").write_text(
            f"name: {name}\nraw_sieve: {script!r}\n"
        )
    sequence = "".join(f"- {name}\n" for name in scripts)
    paths.order_file.write_text(f"sequence:\n{sequence}")


def writes(fake: FakeProton) -> list[str]:
    return [c.verb for c in fake.calls if c.verb in WRITE_VERBS]


def old_snapshots(paths: AccountPaths) -> list[Path]:
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    made = [paths.backups_dir / name for name in OLD_SNAPSHOTS]
    for path in made:
        path.write_text("{}")
    return made


def test_all_lists_exactly_the_documented_names_and_each_resolves() -> None:  # BR-1
    assert set(FUNCTIONS) <= set(api.__all__)
    assert len(set(api.__all__)) == len(api.__all__)
    for name in api.__all__:
        assert hasattr(api, name), name
    for name in FUNCTIONS:
        assert inspect.getdoc(getattr(api, name)), name


def test_internal_surfaces_are_not_exported() -> None:  # BR-1
    for hidden in ("AccountPaths", "ProtonClient", "connect", "account_paths"):
        assert hidden not in api.__all__


def test_only_cli_is_a_public_module() -> None:  # BR-1, BR-17
    names = {m.name for m in pkgutil.iter_modules(api.__path__)}
    assert {n for n in names if not n.startswith("_")} == {"cli"}


def test_only_the_subject_is_positional_and_account_is_keyword() -> None:  # BR-2
    for name in FUNCTIONS:
        params = inspect.signature(getattr(api, name)).parameters
        for pname, param in params.items():
            if pname not in SUBJECTS:
                assert param.kind is inspect.Parameter.KEYWORD_ONLY, (name, pname)
        if name != "validate_declared":
            assert params["account"].default is None


def test_confirmations_default_to_false() -> None:  # BR-3
    for name, pname in [
        ("apply", "confirmed"),
        ("apply", "allow_delete"),
        ("restore", "confirmed"),
        ("import_live", "force"),
        ("import_sieve_files", "force"),
    ]:
        default = inspect.signature(getattr(api, name)).parameters[pname].default
        assert default is False


def test_apply_without_confirmation_writes_nothing(
    account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-3
    declare(account, mine="keep;")
    report = api.apply()
    assert report.refused
    assert writes(fake_proton) == []
    assert fake_proton.filters == []


def test_account_comes_from_argument_then_environment(
    account: AccountPaths, fake_proton: FakeProton, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-2
    declare(account, mine="keep;")
    assert api.plan().outcome == "drift"
    assert account.account_marker.exists()
    monkeypatch.setenv("SIEVE_AS_CODE_ACCOUNT", "other")
    assert api.plan(account="work").outcome == "drift"


@pytest.mark.parametrize("bad", ["../x", ".hidden", "a/b", ""])
def test_invalid_account_name_is_rejected_before_any_call(
    bad: str, fake_proton: FakeProton, work_account: AccountPaths
) -> None:  # BR-2
    with pytest.raises(api.ValidationError):
        api.plan(account=bad)
    assert fake_proton.calls == []


def test_offline_functions_make_no_proton_call(
    account: AccountPaths, fake_proton: FakeProton, tmp_path: Path
) -> None:  # BR-2
    api.backup()
    api.backup()
    first = sorted(account.backups_dir.glob("*.json"))[0]
    fake_proton.calls.clear()
    declare(account, mine="keep;")
    source = tmp_path / "from-file.sieve"
    source.write_text("keep;\n")
    assert api.load_declared().filters[0].name == "mine"
    api.validate_declared(api.load_declared())
    assert api.backup_diff(first, first).outcome == "clean"
    assert api.import_sieve_files([source], force=True).ok
    assert fake_proton.calls == []


def test_apply_retroactive_requires_confirmation_arguments() -> None:  # BR-3
    with pytest.raises(TypeError):
        api.apply_retroactive("x")  # type: ignore[call-arg]


def test_results_are_frozen_and_snapshot_gains_defaulted_fields(
    account: AccountPaths,
) -> None:  # BR-4
    snapshot = api.backup()
    assert snapshot.pruned == () and snapshot.prune_error is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.pruned = ("x",)  # type: ignore[misc]


def test_validate_declared_raises_on_duplicate_names() -> None:  # BR-4
    twin = Filter("a", "keep;", True, None)
    bad = api.FilterSet((twin, twin), FilterOrder(("a", "a")))
    with pytest.raises(api.ValidationError):
        api.validate_declared(bad)


def test_backup_prunes_by_argument_over_environment(
    account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-5
    old = old_snapshots(account)
    monkeypatch.setenv("SIEVE_AS_CODE_KEEP_LAST", "5")
    monkeypatch.setenv("SIEVE_AS_CODE_KEEP_DAYS", "36500")
    snapshot = api.backup(keep_days=1, keep_last=1)
    assert set(snapshot.pruned) == {p.name for p in old}
    assert snapshot.path.exists()
    assert not any(p.exists() for p in old)


def test_backup_takes_each_limit_from_the_environment_when_unset(
    account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-5
    old = old_snapshots(account)
    monkeypatch.setenv("SIEVE_AS_CODE_KEEP_DAYS", "36500")
    assert api.backup(keep_last=1).pruned == ()
    assert all(p.exists() for p in old)


def test_backup_without_limits_never_prunes(account: AccountPaths) -> None:  # BR-5
    old = old_snapshots(account)
    assert api.backup().pruned == ()
    assert all(p.exists() for p in old)


def test_unchanged_backup_still_prunes(account: AccountPaths) -> None:  # BR-5
    api.backup()
    old_snapshots(account)
    again = api.backup(keep_last=1)
    assert again.unchanged and len(again.pruned) == 2


@pytest.mark.parametrize("bad", [0, -1, True, "3"])
def test_bad_retention_argument_fails_before_any_proton_call(
    bad: Any, account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-5
    with pytest.raises(api.ValidationError):
        api.backup(keep_last=bad)
    with pytest.raises(api.ValidationError):
        api.backup(keep_days=bad)
    assert fake_proton.calls == []


def test_bad_retention_variable_fails_before_any_proton_call(
    account: AccountPaths, fake_proton: FakeProton, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-5
    monkeypatch.setenv("SIEVE_AS_CODE_KEEP_LAST", "0")
    with pytest.raises(api.ValidationError):
        api.backup()
    assert fake_proton.calls == []


def test_prune_failure_keeps_the_snapshot(
    account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-5
    old = old_snapshots(account)

    def refuse(self: Path, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    snapshot = api.backup(keep_last=1)
    assert snapshot.prune_error and snapshot.path.exists()
    assert all(p.exists() for p in old)


def test_apply_snapshot_never_prunes(
    account: AccountPaths, fake_proton: FakeProton, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-5
    old = old_snapshots(account)
    monkeypatch.setenv("SIEVE_AS_CODE_KEEP_LAST", "1")
    declare(account, mine="keep;")
    assert api.apply(confirmed=True).ok
    assert all(p.exists() for p in old)


def test_version_matches_pyproject() -> None:  # BR-16
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    assert api.__version__ == project["version"]


def test_every_command_wrapper_returns_its_result_type(
    account: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-2, BR-4
    fake_proton.add_filter("mine", "stop;")
    assert api.discover().filters[0].name == "mine"
    assert api.import_live(force=True).ok
    assert api.plan().outcome == "clean"
    first = api.backup().path
    fake_proton.add_filter("later", "keep;")
    second = api.backup().path
    assert api.backup_diff(first, second).entries
    assert api.restore(first, confirmed=True).ok
    assert api.retroactive_audit().rows[0].name == "mine"
    preview = api.retroactive_preview("mine")
    assert preview.previewable and not preview.entries
    report = api.apply_retroactive("mine", confirmed_name="mine", reason="r")
    assert report.ok and not report.started
    fake_proton.messages.append(
        {
            "id": "m1",
            "conversation_id": "c1",
            "subject": "s",
            "from_name": "n",
            "from_address": "a@b.c",
            "time": 1_700_000_000,
            "unread": 1,
            "num_attachments": 0,
            "labels": ["0"],
        }
    )
    fake_proton.filters[0]["sieve"] = 'require ["fileinto"]; fileinto "Archive";'
    started = api.apply_retroactive("mine", confirmed_name="mine", reason="r")
    assert started.started and started.snapshot is not None
    assert api.retroactive_status().filter == "mine"
