"""Unit 7 BR-1 to BR-16: import."""

import dataclasses
import itertools
import os
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sieve_as_code._client import ProtonClient, connect
from sieve_as_code._declared import load_declared, load_local, normalize_whitespace
from sieve_as_code._importer import ImportReport, import_live, import_sieve_files
from sieve_as_code._live import discover
from sieve_as_code._model import (
    ClientError,
    Filter,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code._plan import diff
from sieve_as_code._settings import AccountPaths
from tests.fake_proton import FakeProton

FRESH = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
_counter = itertools.count()


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def write_local(paths: AccountPaths, files: dict[str, str], order: list[str]) -> None:
    paths.filters_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in files.items():
        (paths.filters_dir / filename).write_text(text)
    sequence = "\n".join(f"- {name!r}" for name in order)
    paths.order_file.write_text(
        f"sequence:\n{sequence}\n" if order else "sequence: []\n"
    )


def filter_yaml(name: str, script: str = "keep;", enabled: bool = True) -> str:
    flag = "" if enabled else "enabled: false\n"
    return f"name: {name!r}\nraw_sieve: {script!r}\n{flag}"


def tree(paths: AccountPaths) -> dict[str, bytes]:
    """Every file under the account's filters root, by relative name."""
    root = paths.order_file.parent
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def declared_names(paths: AccountPaths) -> list[str]:
    return list(load_declared(paths)[1].sequence)


def test_other_account_is_rejected(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-1
    other = dataclasses.replace(work_account, account="other")
    calls = len(fake_proton.calls)
    with pytest.raises(ValidationError, match="account"):
        import_live(other, client)
    assert len(fake_proton.calls) == calls
    assert not work_account.filters_dir.exists()


def test_import_only_reads_proton_and_writes_no_audit_line(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-2
    fake_proton.add_filter("a")
    fake_proton.add_filter("a")
    before = len(fake_proton.calls)
    report = import_live(work_account, client)
    verbs = {call.verb for call in fake_proton.calls[before:]}
    assert verbs <= {"list", "get"}
    assert not work_account.audit_log.exists()
    assert [(r.original, r.name) for r in report.renamed] == [("a", "a (1)")]
    assert report.ok and report.new == ("a", "a (1)")


def test_import_all_writes_files_and_order_last(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-12, BR-14, BR-15
    fake_proton.add_filter("one", "keep;")
    fake_proton.add_filter("two", "stop;", status=0)
    report = import_live(work_account, client)
    assert [p.name for p in report.written] == ["one.yaml", "two.yaml", "order.yaml"]
    filters, order = load_declared(work_account)
    assert {f.name: f.enabled for f in filters} == {"one": True, "two": False}
    assert order.sequence == ("one", "two")


def test_single_name_imports_only_that_filter(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-3
    fake_proton.add_filter("one")
    fake_proton.add_filter("two")
    fake_proton.add_filter("two")
    import_live(work_account, client, name="two (1)")
    assert declared_names(work_account) == ["two (1)"]
    import_live(work_account, client, name="one")
    assert declared_names(work_account) == ["two (1)", "one"]


def test_unknown_name_is_rejected_without_writing(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-3
    fake_proton.add_filter("one")
    with pytest.raises(ValidationError, match="'nope'"):
        import_live(work_account, client, name="nope")
    assert not work_account.filters_dir.exists()


def test_live_read_failure_propagates_without_writing(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-2
    fake_proton.failures["mail settings filters list"] = (1, "boom")
    with pytest.raises(ClientError):
        import_live(work_account, client)
    assert not work_account.filters_dir.exists()


def test_empty_account_writes_an_empty_order_file(
    work_account: AccountPaths, client: ProtonClient
) -> None:  # BR-12, BR-15
    report = import_live(work_account, client)
    assert report.written == (work_account.order_file,)
    assert load_declared(work_account) == ([], load_declared(work_account)[1])
    assert declared_names(work_account) == []


def test_missing_directory_and_order_file_are_empty_local_state(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-6
    fake_proton.add_filter("x")
    assert not work_account.filters_dir.exists()
    assert not work_account.order_file.exists()
    assert import_live(work_account, client).ok


def test_invalid_local_file_blocks_even_with_force(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-6
    fake_proton.add_filter("x")
    write_local(work_account, {"bad.yaml": "name: bad\nextra: 1\n"}, [])
    before = tree(work_account)
    with pytest.raises(ValidationError, match="unknown key"):
        import_live(work_account, client, force=True)
    assert tree(work_account) == before


def test_invalid_live_script_is_rejected_before_writing(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-5, BR-16
    fake_proton.add_filter("good")
    fake_proton.add_filter("bad", 'if true { fileinto "SECRET-FOLDER";')
    with pytest.raises(ValidationError) as error:
        import_live(work_account, client)
    assert "SECRET-FOLDER" not in str(error.value)
    assert not work_account.filters_dir.exists()


def test_equal_local_file_keeps_its_bytes_and_second_import_writes_nothing(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-7, BR-12
    fake_proton.add_filter("a", "keep;")
    handmade = "# my note\nname: a\nraw_sieve: keep;   \n"
    write_local(work_account, {"a.yaml": handmade}, ["a"])
    first = import_live(work_account, client)
    assert first.written == () and first.new == () and first.changed == ()
    assert (work_account.filters_dir / "a.yaml").read_text() == handmade
    fake_proton.add_filter("b")
    assert import_live(work_account, client).written != ()
    snapshot = tree(work_account)
    again = import_live(work_account, client)
    assert again.ok and again.written == () and tree(work_account) == snapshot


def test_local_only_filter_is_preserved_and_listed_after_live(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-8, BR-9
    fake_proton.add_filter("a")
    write_local(work_account, {"mine.yaml": filter_yaml("mine")}, ["mine"])
    before = (work_account.filters_dir / "mine.yaml").read_bytes()
    report = import_live(work_account, client)
    assert report.preserved == ("mine",) and report.ok
    assert declared_names(work_account) == ["a", "mine"]
    assert (work_account.filters_dir / "mine.yaml").read_bytes() == before


def test_filter_missing_from_order_file_is_appended_sorted_and_dangling_dropped(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-9
    write_local(
        work_account,
        {"b.yaml": filter_yaml("b"), "a.yaml": filter_yaml("a")},
        ["ghost"],
    )
    report = import_sieve_files(work_account, [])
    assert report.written == (work_account.order_file,)
    assert declared_names(work_account) == ["a", "b"]


def test_changed_script_enabled_or_moved_entry_is_refused_and_force_writes(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-10, BR-11
    fake_proton.add_filter("a", "keep;")
    fake_proton.add_filter("b", "stop;")
    fake_proton.add_filter("c", "keep;")
    write_local(
        work_account,
        {
            "a.yaml": filter_yaml("a", "discard;"),
            "b.yaml": filter_yaml("b", "stop;", enabled=False),
            "c.yaml": filter_yaml("c"),
        },
        ["c", "a", "b"],
    )
    before = tree(work_account)
    report = import_live(work_account, client)
    assert report.refused and not report.ok and report.written == ()
    assert report.changed == ("a", "b") and report.reordered
    assert tree(work_account) == before
    forced = import_live(work_account, client, force=True)
    assert forced.ok and forced.changed == ("a", "b")
    assert declared_names(work_account) == ["a", "b", "c"]
    assert import_live(work_account, client).written == ()


def test_pure_insertion_into_the_order_needs_no_force(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-10
    for name in ("a", "x", "b"):
        fake_proton.add_filter(name)
    write_local(
        work_account,
        {"a.yaml": filter_yaml("a"), "b.yaml": filter_yaml("b")},
        ["a", "b"],
    )
    report = import_live(work_account, client)
    assert report.ok and report.new == ("x",) and not report.reordered
    assert declared_names(work_account) == ["a", "x", "b"]


def test_local_only_filter_in_the_middle_counts_as_a_move(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-10
    fake_proton.add_filter("a")
    fake_proton.add_filter("b")
    write_local(
        work_account,
        {n + ".yaml": filter_yaml(n) for n in ("a", "mine", "b")},
        ["a", "mine", "b"],
    )
    assert import_live(work_account, client).reordered
    assert import_live(work_account, client, force=True).ok
    assert declared_names(work_account) == ["a", "b", "mine"]


def test_filter_is_written_to_the_file_that_holds_it(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-13
    fake_proton.add_filter("spam", "keep;")
    write_local(work_account, {"my-rules.yaml": filter_yaml("spam", "stop;")}, ["spam"])
    import_live(work_account, client, force=True)
    assert sorted(p.name for p in work_account.filters_dir.iterdir()) == [
        "my-rules.yaml"
    ]
    assert load_declared(work_account)[0][0].raw_sieve == "keep;"


@pytest.mark.parametrize(
    ("live", "local_file", "numbered"),
    [("a/b", "a_b.yaml", "a_b (1).yaml"), ("Foo", "foo.yaml", "Foo (1).yaml")],
)
def test_clashing_file_name_gets_a_number_and_the_other_file_is_untouched(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    live: str,
    local_file: str,
    numbered: str,
) -> None:  # BR-13
    fake_proton.add_filter(live)
    write_local(work_account, {local_file: filter_yaml("other")}, ["other"])
    before = (work_account.filters_dir / local_file).read_bytes()
    import_live(work_account, client)
    assert (work_account.filters_dir / local_file).read_bytes() == before
    files, _ = load_local(work_account)
    assert {f.name for f in files.values()} == {live, "other"}
    # Compare names, not `.exists()`: a case-insensitive filesystem hides the spelling.
    assert numbered in {path.name for path in work_account.filters_dir.iterdir()}


def test_write_failure_names_the_path_and_a_rerun_completes(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # BR-14
    for name in ("a", "b", "c"):
        fake_proton.add_filter(name)
    real = os.replace
    calls = {"n": 0}

    def flaky(src: os.PathLike[str], dst: os.PathLike[str]) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError(13, "Permission denied")
        real(src, dst)

    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", flaky)
        with pytest.raises(SieveAsCodeError, match=r"b\.yaml: Permission denied"):
            import_live(work_account, client)
    assert sorted(p.name for p in work_account.filters_dir.iterdir()) == ["a.yaml"]
    report = import_live(work_account, client)
    assert report.ok and declared_names(work_account) == ["a", "b", "c"]
    assert not list(work_account.order_file.parent.rglob("*.tmp"))


def test_unwritable_directory_is_a_named_error(
    work_account: AccountPaths, client: ProtonClient, fake_proton: FakeProton
) -> None:  # BR-14
    fake_proton.add_filter("a")
    work_account.order_file.parent.mkdir(parents=True, exist_ok=True)
    work_account.filters_dir.write_text("a file, not a directory")
    with pytest.raises(SieveAsCodeError, match="cannot write"):
        import_live(work_account, client)


def test_sieve_files_are_named_by_stem_and_default_enabled(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-4
    source = tmp_path / "Spam.SIEVE"
    source.write_text("discard;\n")
    report = import_sieve_files(work_account, [source])
    assert report.new == ("Spam",) and report.renamed == ()
    (item,) = load_declared(work_account)[0]
    assert item == Filter("Spam", "discard;", True)


@pytest.mark.parametrize("filename", ["notes.txt", ".sieve", "plain"])
def test_non_sieve_suffix_is_rejected(
    work_account: AccountPaths, tmp_path: Path, filename: str
) -> None:  # BR-4
    source = tmp_path / filename
    source.write_text("keep;")
    with pytest.raises(ValidationError, match="not a .sieve file"):
        import_sieve_files(work_account, [source])
    assert not work_account.filters_dir.exists()


def test_unreadable_and_non_utf8_sources_are_rejected(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-4, BR-16
    with pytest.raises(ValidationError, match="cannot read"):
        import_sieve_files(work_account, [tmp_path / "missing.sieve"])
    binary = tmp_path / "bin.sieve"
    binary.write_bytes(b"\xff\xfeSECRET")
    with pytest.raises(ValidationError, match="not valid UTF-8") as error:
        import_sieve_files(work_account, [binary])
    assert "SECRET" not in str(error.value)


def test_two_sources_with_one_name_are_rejected(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-4
    (tmp_path / "x").mkdir()
    first, second = tmp_path / "x.sieve", tmp_path / "x" / "x.sieve"
    first.write_text("keep;")
    second.write_text("stop;")
    with pytest.raises(ValidationError) as error:
        import_sieve_files(work_account, [first, second])
    assert str(first) in str(error.value) and str(second) in str(error.value)


def test_sieve_import_keeps_the_local_enabled_flag_and_appends_to_the_order(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-4, BR-9
    write_local(
        work_account,
        {
            "a.yaml": filter_yaml("a", "keep;", enabled=False),
            "z.yaml": filter_yaml("z"),
        },
        ["z", "a"],
    )
    same, other = tmp_path / "a.sieve", tmp_path / "n.sieve"
    same.write_text("keep;\n")
    other.write_text("stop;")
    report = import_sieve_files(work_account, [same, other])
    assert report.ok and report.new == ("n",) and report.changed == ()
    assert report.preserved == ()
    filters, order = load_declared(work_account)
    assert order.sequence == ("z", "a", "n")
    assert {f.name: f.enabled for f in filters} == {"a": False, "z": True, "n": True}


def test_sieve_import_with_a_different_script_needs_force(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-11
    write_local(work_account, {"a.yaml": filter_yaml("a", "keep;")}, ["a"])
    source = tmp_path / "a.sieve"
    source.write_text("stop;")
    before = tree(work_account)
    report = import_sieve_files(work_account, [source])
    assert report.refused and report.changed == ("a",)
    assert tree(work_account) == before
    assert import_sieve_files(work_account, [source], force=True).ok
    assert load_declared(work_account)[0][0].raw_sieve == "stop;"


def test_sieve_script_is_validated_before_anything_is_written(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-5
    good, bad = tmp_path / "good.sieve", tmp_path / "bad.sieve"
    good.write_text("keep;")
    bad.write_text("if true {")
    with pytest.raises(ValidationError, match="bad"):
        import_sieve_files(work_account, [good, bad])
    assert not work_account.filters_dir.exists()


def test_imported_scripts_are_written_normalised(
    work_account: AccountPaths, tmp_path: Path
) -> None:  # BR-5
    source = tmp_path / "t.sieve"
    source.write_text("if true {\n\tkeep;   \n}\n\n")
    import_sieve_files(work_account, [source])
    assert load_declared(work_account)[0][0].raw_sieve == ("if true {\n    keep;\n}")


def test_report_is_frozen_and_ok_means_not_refused() -> None:
    report = ImportReport()
    assert report.ok and not ImportReport(refused=True).ok
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.refused = True  # type: ignore[misc]


names = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 _./-]{0,6}", fullmatch=True)
scripts = st.sampled_from(["keep;", "stop;", "discard;", "if true {\n\tkeep;  \n}"])
live_rows = st.lists(st.tuples(names, scripts, st.booleans()), max_size=5)


def fresh_paths(base: AccountPaths) -> AccountPaths:
    root = base.order_file.parent / f"r{next(_counter)}"
    return dataclasses.replace(
        base, filters_dir=root / "filters", order_file=root / "order.yaml"
    )


@FRESH
@given(live_rows)
def test_import_then_load_equals_live_and_plan_is_clean(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    rows: list[tuple[str, str, bool]],
) -> None:  # BR-15, idempotence
    paths = fresh_paths(work_account)
    fake_proton.filters.clear()
    for name, script, enabled in rows:
        fake_proton.add_filter(name, script, 1 if enabled else 0)
    first = import_live(paths, client)
    assert first.ok and first.changed == ()
    live = discover(client)
    filters, order = load_declared(paths)
    assert order == live.order
    assert [(f.name, f.enabled) for f in filters] == [
        (f.name, f.enabled) for f in live.filters
    ] or sorted((f.name, f.enabled) for f in filters) == sorted(
        (f.name, f.enabled) for f in live.filters
    )
    by_name = {f.name: f for f in filters}
    for item in live.filters:
        assert by_name[item.name].raw_sieve == normalize_whitespace(item.raw_sieve)
    from sieve_as_code._model import FilterSet

    declared = FilterSet(tuple(by_name[n] for n in order.sequence), order)
    plan = diff(declared, live, None)
    assert plan.outcome == "clean" and plan.informational == ()
    again = import_live(paths, client)
    assert again.ok and again.written == ()


@FRESH
@given(live_rows, live_rows, st.booleans())
def test_local_only_filters_survive_byte_for_byte(
    work_account: AccountPaths,
    client: ProtonClient,
    fake_proton: FakeProton,
    live: list[tuple[str, str, bool]],
    local: list[tuple[str, str, bool]],
    force: bool,
) -> None:  # BR-8
    paths = fresh_paths(work_account)
    fake_proton.filters.clear()
    for name, script, enabled in live:
        fake_proton.add_filter(name, script, 1 if enabled else 0)
    live_names = {f.name for f in discover(client).filters}
    only = {}
    for name, script, enabled in local:
        if name not in live_names and name not in only:
            only[name] = filter_yaml(name, script, enabled)
    files = {f"local-{i}.yaml": text for i, text in enumerate(only.values())}
    write_local(paths, files, list(only))
    before = {n: (paths.filters_dir / n).read_bytes() for n in files}
    import_live(paths, client, force=force)
    for filename, content in before.items():
        assert (paths.filters_dir / filename).read_bytes() == content
    assert set(only) <= set(declared_names(paths))
