"""Unit 9 BR-6 to BR-15: the command line."""

import json
import subprocess
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
import yaml

from sieve_as_code import __version__, cli
from sieve_as_code._apply import ApplyReport
from sieve_as_code._plan import Flag, PlanEntry, PlanResult, Reorder
from sieve_as_code._restore import RestoreReport
from sieve_as_code._retroactive import RetroPreview, RetroReport
from sieve_as_code._settings import AccountPaths
from tests.fake_proton import FakeProton

SECRET = "SENTINEL-SCRIPT-TEXT"
WRITE_VERBS = {"create", "update", "delete", "enable", "disable", "reorder"}
MOVE = 'require ["fileinto"];\n# ' + SECRET + '\nfileinto "Archive";\n'
NOW = 1_700_000_000
Result = tuple[int, str, str]


@pytest.fixture
def env(
    fake_proton: FakeProton, work_account: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> AccountPaths:
    monkeypatch.setenv("SIEVE_AS_CODE_ACCOUNT", "work")
    return work_account


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str], env: AccountPaths) -> Callable[..., Result]:
    def call(*argv: str) -> Result:
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return call


@pytest.fixture
def typed(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[str]]:
    """Feed `input()` these answers; an exception instance is raised instead."""

    def feed(*answers: str | BaseException) -> list[str]:
        queue = list(answers)
        prompts: list[str] = []

        def fake_input(prompt: str = "") -> str:
            prompts.append(prompt)
            answer = queue.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        monkeypatch.setattr("builtins.input", fake_input)
        return prompts

    return feed


def declare(paths: AccountPaths, **scripts: str) -> None:
    paths.filters_dir.mkdir(parents=True, exist_ok=True)
    for name, script in scripts.items():
        entry = {"name": name, "raw_sieve": script}
        (paths.filters_dir / f"{name}.yaml").write_text(yaml.safe_dump(entry))
    paths.order_file.write_text(yaml.safe_dump({"sequence": list(scripts)}))


def writes(fake: FakeProton) -> list[str]:
    return [c.verb for c in fake.calls if c.verb in WRITE_VERBS]


def message(fake: FakeProton, mid: str = "m1") -> None:
    fake.messages.append(
        {
            "id": mid,
            "conversation_id": f"c{mid}",
            "subject": f"Subject {mid}",
            "from_name": "Sender",
            "from_address": f"{mid}@news.example",
            "time": NOW,
            "unread": 1,
            "num_attachments": 0,
            "labels": ["0"],
        }
    )


def audit(paths: AccountPaths) -> list[dict[str, Any]]:
    return [json.loads(line) for line in paths.audit_log.read_text().splitlines()]


def test_output_starts_with_the_account_and_its_fingerprint(run: Any) -> None:  # BR-10
    _, out, _ = run("discover")
    first = out.splitlines()[0]
    assert first.startswith("account: work (fingerprint ")
    assert len(first.split("fingerprint ")[1].rstrip(")")) == 12


def test_account_line_has_no_fingerprint_before_first_proton_contact(
    run: Any, tmp_path: Path
) -> None:  # BR-10
    source = tmp_path / "rule.sieve"
    source.write_text("keep;\n")
    code, out, _ = run("import", "--sieve", str(source))
    assert code == 0 and out.splitlines()[0] == "account: work"


def test_plan_with_drift_exits_one_and_shows_the_new_script(
    run: Any, env: AccountPaths
) -> None:  # BR-7, BR-11
    declare(env, mine=MOVE)
    code, out, _ = run("plan")
    assert code == 1
    assert "create: mine" in out and "outcome: drift" in out
    assert f"    + # {SECRET}" in out and '    + fileinto "Archive";' in out
    assert SECRET not in env.audit_log.read_text()


def test_plan_shows_a_unified_diff_of_a_content_change(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-7, BR-11
    fake_proton.add_filter("mine", "keep;\n")
    declare(env, mine="stop;\n")
    code, out, _ = run("plan")
    assert code == 1 and "content: mine" in out
    for line in ("    --- live", "    +++ declared", "    -keep;", "    +stop;"):
        assert line in out.splitlines()


def test_plan_exits_zero_when_clean(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-7
    fake_proton.add_filter("mine", "keep;")
    declare(env, mine="keep;")
    code, out, _ = run("plan")
    assert code == 0 and "outcome: clean" in out


def test_apply_without_yes_prints_the_plan_and_refuses(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-8
    declare(env, mine=MOVE)
    code, out, _ = run("apply")
    assert code == 1
    assert "create: mine" in out and "nothing written; re-run with --yes" in out
    assert writes(fake_proton) == [] and SECRET in out


def test_apply_with_yes_writes_and_a_second_plan_is_clean(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-8
    declare(env, mine=MOVE)
    code, out, _ = run("apply", "--yes")
    assert code == 0 and "done: create mine" in out
    assert fake_proton.names() == ["mine"]
    assert "outcome: clean" in run("plan")[1]
    assert SECRET not in env.audit_log.read_text()


def test_apply_failure_names_the_failed_action_and_exits_one(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-6, BR-8
    declare(env, a="keep;", b="stop;")
    fake_proton.failures["mail settings filters create"] = (1, "boom")
    code, out, _ = run("apply", "--yes")
    assert code == 1
    assert "failed: create a:" in out and "boom" in out
    assert "not attempted: create b" in out


def test_allow_delete_exists_on_apply_only(run: Any, env: AccountPaths) -> None:  # BR-8
    declare(env, mine="keep;")
    assert run("restore", "--allow-delete")[0] == 2
    assert run("apply", "--allow-delete", "--yes")[0] == 0


def test_restore_without_yes_refuses_and_with_yes_converges(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-8
    fake_proton.add_filter("a", "keep;")
    run("backup")
    fake_proton.add_filter("later", "stop;")
    code, out, _ = run("restore")
    assert code == 1 and "re-run with --yes" in out
    assert fake_proton.names() == ["a", "later"]
    code, out, _ = run("restore", "--yes")
    assert code == 0 and fake_proton.names() == ["a"]


def test_restore_that_leaves_a_diff_prints_it() -> None:  # BR-7
    clean = PlanResult((), (), None, (), ())
    drift = PlanResult((), (PlanEntry("content", "x"),), None, (), ())
    report = RestoreReport(clean, remaining=drift)
    assert not report.ok
    assert "remaining differences from the backup:" in cli._restore_lines(report)
    assert cli._apply_lines(ApplyReport(clean))[-1] == "outcome: clean"


def test_renderers_show_every_part_of_a_result() -> None:  # BR-7, BR-9, BR-11
    plan = PlanResult(
        (),
        (),
        Reorder(("a", "b"), ("b", "a")),
        (Flag("a", "vnd.proton.expire"),),
        ("old",),
    )
    lines = cli._plan_lines(plan)
    assert "reorder: ('a', 'b') -> ('b', 'a')" in lines
    assert "warning: a uses vnd.proton.expire" in lines
    assert "info: old is live-only and disabled" in lines
    audit_failed = ApplyReport(plan, audit_error="disk full")
    assert "error: audit log not written: disk full" in cli._apply_lines(audit_failed)
    preview = RetroPreview("f", True, None, True, (), 3, True)
    shown = cli._preview_lines(preview)
    assert any("approximate" in line for line in shown)
    assert any("uses live" in line for line in shown)
    assert "spam excluded: 3" in shown
    report = RetroReport(preview, started=True, audit_error="x", prune_error="y")
    retro = cli._retro_lines(report)
    assert "error: audit log not written: x" in retro
    assert "warning: old snapshots not removed: y" in retro


def test_discover_prints_scripts_in_import_format_and_writes_nothing(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-11, BR-12
    fake_proton.add_filter("twin", MOVE)
    fake_proton.add_filter("twin", "keep;")
    code, out, _ = run("discover")
    assert code == 0 and SECRET in out
    assert "# twin.yaml" in out and "renamed: twin -> twin (1)" in out
    assert not env.filters_dir.exists()
    run("import", "--force")
    for path in env.filters_dir.glob("*.yaml"):
        assert path.read_text().rstrip("\n") in out
    assert env.order_file.read_text().rstrip("\n") in out


def test_import_refuses_differences_without_force(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-13
    fake_proton.add_filter("mine", "keep;")
    declare(env, mine="stop;")
    code, out, _ = run("import")
    assert code == 1 and "changed: mine" in out and "re-run with --force" in out
    code, out, _ = run("import", "mine", "--force")
    assert code == 0 and "wrote:" in out


def test_import_sieve_files_and_conflicting_arguments(
    run: Any, env: AccountPaths, tmp_path: Path
) -> None:  # BR-13
    source = tmp_path / "rule.sieve"
    source.write_text("keep;\n")
    code, out, _ = run("import", "--sieve", str(source))
    assert code == 0 and "new: rule" in out
    code, _, err = run("import", "rule", "--sieve", str(source))
    assert code == 2 and "cannot be combined" in err


def test_backup_reports_unchanged_and_prunes(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-5, BR-14
    code, out, _ = run("backup")
    assert code == 0 and "snapshot:" in out and "no change" not in out
    env.backups_dir.joinpath("20200101T000000000000Z.json").write_text("{}")
    code, out, _ = run("backup", "--keep-last", "1")
    assert code == 0 and "no change since this snapshot" in out
    assert "pruned: 1 old snapshots" in out


def test_backup_prune_failure_warns_and_still_exits_zero(
    run: Any, env: AccountPaths, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-5, BR-6
    run("backup")
    env.backups_dir.joinpath("20200101T000000000000Z.json").write_text("{}")

    def refuse(self: Path, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    code, _, err = run("backup", "--keep-last", "1")
    assert code == 0 and "warning: prune failed" in err


@pytest.mark.parametrize("value", ["0", "-1", "x", "1.5"])
@pytest.mark.parametrize("flag", ["--keep-days", "--keep-last"])
def test_keep_flags_reject_anything_but_a_whole_number_of_one_or_more(
    run: Any, flag: str, value: str
) -> None:  # BR-14
    assert run("backup", flag, value)[0] == 2


def test_backup_diff_with_differences_exits_zero(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-7
    run("backup")
    first = sorted(env.backups_dir.glob("*.json"))[0]
    fake_proton.add_filter("new", "keep;")
    run("backup")
    second = sorted(env.backups_dir.glob("*.json"))[-1]
    code, out, _ = run("backup-diff", str(first), str(second))
    assert code == 0 and "outcome: drift" in out


def test_apply_retroactive_runs_after_the_exact_name_and_a_reason(
    run: Any, env: AccountPaths, fake_proton: FakeProton, typed: Any
) -> None:  # BR-9, BR-10
    fake_proton.add_filter("mine", MOVE)
    message(fake_proton)
    prompts = typed("mine", "tidy up")
    code, out, _ = run("apply-retroactive", "mine")
    assert code == 0 and "mine: 1 messages would change" in out
    assert "started:" in out and "move: Archive" in out
    assert "account work (fingerprint " in out
    assert "cannot be cancelled" in out and "'mine'" in prompts[0]
    assert audit(env)[-1]["detail"]["reason"] == "tidy up"


@pytest.mark.parametrize("answers", [["Mine", "r"], ["mine", " "], ["mine", ""]])
def test_apply_retroactive_refuses_a_wrong_name_or_blank_reason(
    run: Any,
    env: AccountPaths,
    fake_proton: FakeProton,
    typed: Any,
    answers: list[str],
) -> None:  # BR-9
    fake_proton.add_filter("mine", MOVE)
    message(fake_proton)
    typed(*answers)
    code, out, _ = run("apply-retroactive", "mine")
    assert code == 1 and "not confirmed; nothing changed" in out
    assert [c for c in fake_proton.calls if c.verb == "apply"] == []
    assert audit(env)[-1]["outcome"] == "refused"


def test_apply_retroactive_treats_end_of_input_as_empty_answers(
    run: Any, env: AccountPaths, fake_proton: FakeProton, typed: Any
) -> None:  # BR-9
    fake_proton.add_filter("mine", MOVE)
    message(fake_proton)
    typed(EOFError(), EOFError())
    code, out, _ = run("apply-retroactive", "mine")
    assert code == 1 and "not confirmed" in out


def test_apply_retroactive_with_nothing_to_do_does_not_prompt(
    run: Any, env: AccountPaths, fake_proton: FakeProton, typed: Any
) -> None:  # BR-9
    fake_proton.add_filter("mine", MOVE)
    prompts = typed()
    code, out, _ = run("apply-retroactive", "mine")
    assert code == 0 and "nothing to do" in out and prompts == []


def test_apply_retroactive_of_an_unpreviewable_filter_still_asks(
    run: Any, env: AccountPaths, fake_proton: FakeProton, typed: Any
) -> None:  # BR-9
    fake_proton.add_filter("big", "if size :over 1M { keep; }")
    typed("big", "needed")
    code, out, _ = run("apply-retroactive", "big")
    assert code == 0 and "not previewable" in out
    assert "none (filter not previewable)" in out


def test_apply_retroactive_has_no_yes_option(run: Any) -> None:  # BR-9
    assert run("apply-retroactive", "x", "--yes")[0] == 2


def test_apply_retroactive_reports_a_failed_start(
    run: Any, env: AccountPaths, fake_proton: FakeProton, typed: Any
) -> None:  # BR-6, BR-9
    fake_proton.add_filter("mine", MOVE)
    message(fake_proton)
    fake_proton.failures["mail settings filters apply"] = (1, "nope")
    typed("mine", "r")
    code, out, _ = run("apply-retroactive", "mine")
    assert code == 1 and "failed:" in out and "nope" in out


def test_retroactive_status_and_audit_print_and_exit_zero(
    run: Any, env: AccountPaths, fake_proton: FakeProton, typed: Any
) -> None:  # BR-7
    fake_proton.add_filter("mine", MOVE)
    fake_proton.add_filter("big", "if size :over 1M { keep; }")
    message(fake_proton)
    typed("mine", "r")
    run("apply-retroactive", "mine")
    code, out, _ = run("retroactive-status")
    assert code == 0 and "mine: done 0, pending 1, unexpected 0" in out
    message(fake_proton, "m2")
    fake_proton.filters[0]["sieve"] = MOVE + "stop;"
    out = run("retroactive-status")[1]
    assert "pending m1" in out and "unexpected m2: new" in out
    assert "the filter script changed" in out
    code, out, _ = run("retroactive-audit")
    assert code == 0 and "mine: 2" in out and "big: not previewable" in out


def test_plain_errors_name_the_problem_and_exit_one(
    run: Any, fake_proton: FakeProton
) -> None:  # BR-6
    fake_proton.signed_in = False
    code, out, err = run("plan")
    assert code == 1 and err.startswith("error: ") and out == ""
    assert "Traceback" not in err


def test_validation_errors_exit_two(run: Any, env: AccountPaths) -> None:  # BR-6
    assert run("plan", "--account", "../x")[0] == 2
    env.filters_dir.mkdir(parents=True)
    (env.filters_dir / "bad.yaml").write_text("name: bad\nunknown: 1\n")
    code, _, err = run("plan")
    assert code == 2 and err.startswith("error: ")


def test_interrupt_exits_130_without_a_traceback(
    run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # BR-6
    def interrupt(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", interrupt)
    code, _, err = run("plan")
    assert code == 130 and err.strip() == "interrupted"


def test_usage_errors_help_and_version_return_codes(run: Any) -> None:  # BR-14, BR-15
    assert run()[0] == 2
    assert "COMMAND" in run()[2]
    assert run("nope")[0] == 2
    assert run("backup-diff", "only-one")[0] == 2
    assert run("--help")[0] == 0
    code, out, _ = run("--version")
    assert code == 0 and __version__ in out


@pytest.mark.parametrize(
    "command",
    [
        ["discover"],
        ["plan"],
        ["apply"],
        ["import"],
        ["backup"],
        ["backup-diff", "a", "b"],
        ["restore"],
        ["apply-retroactive", "x"],
        ["retroactive-status"],
        ["retroactive-audit"],
    ],
)
def test_every_command_accepts_account(command: list[str]) -> None:  # BR-14
    args = cli._parser().parse_args([*command, "--account", "other"])
    assert args.account == "other" and callable(args.handler)


def test_main_returns_codes_and_never_raises_system_exit(run: Any) -> None:  # BR-15
    for argv in (["--help"], ["--version"], [], ["bogus"], ["plan"]):
        assert isinstance(cli.main(argv), int)


def test_console_script_points_at_main() -> None:  # BR-15
    scripts = entry_points(group="console_scripts")
    assert scripts["sieve-as-code"].value == "sieve_as_code.cli:main"
    assert scripts["sieve-as-code"].load() is cli.main


def test_restore_plan_diffs_live_against_the_backup(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-8, BR-11
    fake_proton.add_filter("a", "keep;")
    run("backup")
    fake_proton.filters[0]["sieve"] = "stop;"
    code, out, _ = run("restore")
    assert code == 1
    for line in ("    --- live", "    +++ backup", "    -stop;", "    +keep;"):
        assert line in out.splitlines()


def test_apply_plan_shows_the_diff_before_refusing(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-8, BR-11
    fake_proton.add_filter("mine", "keep;")
    declare(env, mine="stop;")
    code, out, _ = run("apply")
    assert code == 1 and "    +stop;" in out.splitlines()
    assert "nothing written; re-run with --yes" in out


def test_backup_diff_labels_the_two_snapshots_and_exits_zero(
    run: Any, env: AccountPaths, fake_proton: FakeProton
) -> None:  # BR-7, BR-11
    fake_proton.add_filter("a", "keep;")
    run("backup")
    fake_proton.filters[0]["sieve"] = "stop;"
    run("backup")
    first, second = sorted(env.backups_dir.glob("*.json"))
    code, out, _ = run("backup-diff", str(first), str(second))
    assert code == 0
    for line in (
        f"    --- {first.name}",
        f"    +++ {second.name}",
        "    -keep;",
        "    +stop;",
    ):
        assert line in out.splitlines()
