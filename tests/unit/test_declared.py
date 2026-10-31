"""BR-1 to BR-18: declared filter files, validation and rendering."""

import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import assume, given
from hypothesis import strategies as st

from sieve_as_code.declared import (
    load_declared,
    normalize_whitespace,
    render,
    validate_declared,
)
from sieve_as_code.model import Filter, FilterOrder, ValidationError
from sieve_as_code.settings import AccountPaths

REQUIRE = 'require ["fileinto", "copy", "regex", "variables", "imap4flags"];\n'
STATEMENTS = [
    "keep;",
    "stop;",
    "discard;",
    'fileinto "INBOX/Receipts";',
    'fileinto :copy "X";',
    'set "v" "1";',
    'addflag "\\\\Seen";',
    'if header :contains "subject" "}{[" {\n  keep;\n}',
    'if header :regex "subject" "a\\"b" { stop; }',
    "if allof (true, false) { keep; }",
    '# comment with { and "',
    '/* block { \n comment " */',
    'if header :is "x" text:\n}{ "\n.\n{\n  keep;\n}',
    "keep; # trailing }",
]
well_formed = st.lists(st.sampled_from(STATEMENTS), min_size=1, max_size=6).map(
    lambda items: REQUIRE + "\n".join(items)
)


def make_paths(root: Path) -> AccountPaths:
    return AccountPaths(
        account="work",
        filters_dir=root / "filters",
        order_file=root / "order.yaml",
        account_marker=root / "account.id",
        backups_dir=root / "backups",
        retroactive_dir=root / "retroactive",
        audit_log=root / "audit.log",
    )


def write_files(
    paths: AccountPaths, filters: dict[str, Any], order: Any = None
) -> None:
    """`filters` maps file stem to file content (mapping or raw text)."""
    paths.filters_dir.mkdir(parents=True, exist_ok=True)
    for stem, content in filters.items():
        text = content if isinstance(content, str) else yaml.safe_dump(content)
        (paths.filters_dir / f"{stem}.yaml").write_text(text, encoding="utf-8")
    if order is not None:
        paths.order_file.write_text(yaml.safe_dump(order), encoding="utf-8")


def entry(name: str, script: str = "keep;", **extra: Any) -> dict[str, Any]:
    return {"name": name, "raw_sieve": script, **extra}


def check(script: str) -> None:
    validate_declared([Filter("a", script)], FilterOrder(("a",)))


@pytest.fixture
def paths(tmp_path: Path) -> AccountPaths:
    return make_paths(tmp_path)


def test_load_returns_filters_and_order(paths: AccountPaths) -> None:
    write_files(
        paths,
        {"a": entry("a"), "b": entry("b", "stop;", enabled=False)},
        {"sequence": ["b", "a"]},
    )
    filters, order = load_declared(paths)
    assert filters == [Filter("a", "keep;"), Filter("b", "stop;", enabled=False)]
    assert order == FilterOrder(("b", "a"))


def test_load_missing_directory_or_order_file_names_path(paths: AccountPaths) -> None:
    with pytest.raises(ValidationError, match="filters directory .*filters"):
        load_declared(paths)
    paths.filters_dir.mkdir()
    with pytest.raises(ValidationError, match="order file .*order.yaml"):
        load_declared(paths)


def test_load_empty_account_is_valid(paths: AccountPaths) -> None:
    write_files(paths, {}, {"sequence": []})
    assert load_declared(paths) == ([], FilterOrder(()))


def test_load_reads_only_yaml_files_directly_in_the_directory(
    paths: AccountPaths,
) -> None:
    write_files(paths, {"a": entry("a")}, {"sequence": ["a"]})
    (paths.filters_dir / "notes.txt").write_text("not yaml: [")
    (paths.filters_dir / "old.yml").write_text("garbage: [")
    (paths.filters_dir / "sub.yaml").mkdir()
    assert load_declared(paths)[0] == [Filter("a", "keep;")]


def test_load_file_name_does_not_matter(paths: AccountPaths) -> None:
    write_files(paths, {"weird-name": entry("other")}, {"sequence": ["other"]})
    assert load_declared(paths)[0][0].name == "other"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("name: [", "bad.yaml: cannot read as YAML"),
        ("- a\n- b\n", "bad.yaml: must be a YAML mapping"),
        ("", "bad.yaml: must be a YAML mapping"),
        (entry("a", tags="x"), "bad.yaml: unknown key 'tags'"),
        ({"raw_sieve": "keep;"}, "bad.yaml: missing field 'name'"),
        ({"name": "a"}, "bad.yaml: missing field 'raw_sieve'"),
        (entry("  "), "bad.yaml: 'name' must be a non-blank string"),
        (entry(5), "bad.yaml: 'name' must be a non-blank string"),  # type: ignore[arg-type]
        (entry("a", " \n\t"), "bad.yaml: 'raw_sieve' must be a non-blank string"),
        (entry("a", None), "bad.yaml: 'raw_sieve' must be a non-blank string"),  # type: ignore[arg-type]
        (entry("a", enabled="yes"), "bad.yaml: 'enabled' must be true or false"),
    ],
)
def test_load_rejects_bad_file_naming_file_and_field(
    paths: AccountPaths, content: Any, message: str
) -> None:
    write_files(paths, {"bad": content}, {"sequence": []})
    with pytest.raises(ValidationError, match=message):
        load_declared(paths)


def test_load_binary_file_is_a_validation_error(paths: AccountPaths) -> None:
    write_files(paths, {}, {"sequence": []})
    (paths.filters_dir / "bad.yaml").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValidationError, match="bad.yaml: cannot read"):
        load_declared(paths)


@given(
    well_formed,
    st.text(alphabet=" \t", max_size=4),
    st.sampled_from(["\n", "\r\n"]),
)
def test_load_keeps_script_exactly_as_written(
    script: str, tail: str, newline: str
) -> None:
    script = script.replace("\n", newline) + tail + newline
    with tempfile.TemporaryDirectory() as root:
        files = make_paths(Path(root))
        write_files(files, {"a": entry("a", script)}, {"sequence": ["a"]})
        assert load_declared(files)[0][0].raw_sieve == script


def test_duplicate_names_across_files_name_both_files(paths: AccountPaths) -> None:
    write_files(paths, {"one": entry("a"), "two": entry("a")}, {"sequence": ["a"]})
    with pytest.raises(ValidationError, match=r"'a' \(one.yaml, two.yaml\)"):
        load_declared(paths)


def test_names_differing_in_case_are_two_filters(paths: AccountPaths) -> None:
    write_files(
        paths, {"one": entry("Foo"), "two": entry("foo")}, {"sequence": ["Foo", "foo"]}
    )
    assert [f.name for f in load_declared(paths)[0]] == ["Foo", "foo"]


@pytest.mark.parametrize(
    ("order", "message"),
    [
        (None, "order.yaml: must be a YAML mapping"),
        ({"sequence": ["a"], "extra": 1}, "order.yaml: must hold exactly the key"),
        ({"order": ["a"]}, "order.yaml: must hold exactly the key"),
        ({"sequence": "a"}, "order.yaml: 'sequence' must be a list"),
        ({"sequence": ["a", 3]}, "order.yaml: 'sequence' must be a list"),
        ({"sequence": ["a", " "]}, "order.yaml: 'sequence' must be a list"),
        ({"sequence": ["a", "a"]}, "order.yaml: 'sequence' lists 'a' twice"),
        ({"sequence": ["a", "ghost"]}, "order.yaml: 'sequence' lists unknown filter"),
        ({"sequence": []}, "order.yaml: 'sequence' is missing filter 'a'"),
    ],
)
def test_load_rejects_bad_order_file(
    paths: AccountPaths, order: Any, message: str
) -> None:
    write_files(paths, {"a": entry("a")})
    paths.order_file.write_text(yaml.safe_dump(order), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        load_declared(paths)


def test_validate_checks_in_memory_filters_like_loaded_ones() -> None:
    order = FilterOrder(("a",))
    validate_declared([Filter("a", "keep;")], order)
    with pytest.raises(ValidationError, match="filter 'a': 'raw_sieve' must be"):
        validate_declared([Filter("a", " ")], order)
    with pytest.raises(ValidationError, match="filter ' ': 'name' must be"):
        validate_declared([Filter(" ", "keep;")], order)
    with pytest.raises(ValidationError, match="duplicate filter name 'a'$"):
        validate_declared([Filter("a", "keep;"), Filter("a", "stop;")], order)
    with pytest.raises(ValidationError, match="order: 'sequence' is missing"):
        validate_declared([Filter("a", "keep;")], FilterOrder(()))


def test_first_failure_wins_script_before_duplicates() -> None:
    filters = [Filter("a", "keep;"), Filter("a", "if true {")]
    with pytest.raises(ValidationError, match="unbalanced"):
        validate_declared(filters, FilterOrder(("a",)))


@pytest.mark.parametrize(
    ("script", "message"),
    [
        ("if true {\n keep;", "line 1: unbalanced '{'"),
        ("keep;\n}", "line 2: unbalanced '}'"),
        ('keep;\nif header :is "a" ["b", "c" { keep; }', "line 2: unbalanced '\\['"),
        ('if header :is "a" ["b" } keep;', "line 1: unbalanced '}'"),
        ("keep; ]", "line 1: unbalanced ']'"),
        ('keep;\n"abc', "line 2: unterminated string"),
        ('keep; "a\\"', "line 1: unterminated string"),
        ("keep;\n/* open", "line 2: unterminated comment"),
        ('if header :is "x" text:\nabc', "line 1: unterminated text: block"),
        ('keep;\n"a\nb"\n{', "line 4: unbalanced '{'"),
        ('if header :is "x" text:\na\n.\n{ }\n}', "line 5: unbalanced '}'"),
        ("/* a\nb */\n}", "line 3: unbalanced '}'"),
        ('fileinto "X";', "line 1: 'fileinto' needs require \"fileinto\""),
        ('keep;\nFILEINTO "X";', "line 2: 'fileinto' needs require"),
        ('require ["fileinto"];\nreject "no";', "line 2: 'reject' needs require"),
        (
            'require ["fileinto"];\nfileinto :copy "X";',
            "':copy' needs require \"copy\"",
        ),
        ('if header :regex "a" "b" { keep; }', "':regex' needs require \"regex\""),
    ],
)
def test_script_problem_is_reported_with_line_and_no_script_text(
    script: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message) as error:
        check(script)
    assert script not in str(error.value)


@pytest.mark.parametrize(
    ("command", "extension"),
    [
        ("fileinto", "fileinto"),
        ("reject", "reject"),
        ("ereject", "ereject"),
        ("vacation", "vacation"),
        ("include", "include"),
        ("set", "variables"),
        ("addflag", "imap4flags"),
        ("setflag", "imap4flags"),
        ("removeflag", "imap4flags"),
    ],
)
def test_each_gated_command_needs_its_extension(command: str, extension: str) -> None:
    with pytest.raises(ValidationError, match=f'needs require "{extension}"'):
        check(f'{command} "x";')
    check(f'require "{extension}";\n{command} "x";')
    check(f'require ["{extension.upper()}"];\n{command} "x";')


@pytest.mark.parametrize(
    "script",
    [
        '# fileinto "X";',
        '/* fileinto "X"; */ keep;',
        'if header :is "a" "fileinto" { keep; }',
        'if header :is "a" text:\nfileinto "X";\n}\n.\n{ keep; }',
        "keep; # }",
        'if header :contains "subject" "}" { keep; }',
        'if exists "set" { keep; }',
        'unknowncommand "a" "b"\nkeep',
        'require ["vnd.proton.expire", "nonsense"];\nfoo;',
        "if allof (true, false) { keep; }",
        "keep;;",
    ],
)
def test_what_the_check_cannot_prove_wrong_passes(script: str) -> None:
    check(script)


@given(well_formed)
def test_well_formed_scripts_pass(script: str) -> None:
    check(script)


@given(well_formed)
def test_broken_scripts_fail_without_echoing_the_script(script: str) -> None:
    for broken, message in [
        (script + "\nif true {\n  keep;", "unbalanced"),
        (script + '\nkeep; "oops', "unterminated string"),
        (script + "\nkeep; /* oops", "unterminated comment"),
        ((script + '\nfileinto "X";').split("\n", 1)[1], "needs require"),
    ]:
        with pytest.raises(ValidationError, match=message) as error:
            check(broken)
        assert broken not in str(error.value)


@given(st.text())
def test_normalize_whitespace_is_idempotent_and_leaves_no_tabs_or_trailing_space(
    script: str,
) -> None:
    once = normalize_whitespace(script)
    assert normalize_whitespace(once) == once
    assert "\t" not in once
    assert all(line == line.rstrip() for line in once.split("\n"))
    assert not once.endswith("\n")


def test_normalize_whitespace_examples() -> None:
    assert normalize_whitespace("a\t\tb  \r\n\tc\n\n") == "a       b\n    c"


def test_render_exact_text(paths: AccountPaths) -> None:
    filters = [
        Filter("one", "keep;"),
        Filter("two", "if true {\n\tstop;  \n}\n", enabled=False),
        Filter("Zoë", "keep; # ünï"),
    ]
    rendered = render(filters, FilterOrder(("two", "one", "Zoë")), paths)
    assert rendered == {
        paths.order_file: "sequence:\n- two\n- one\n- Zoë\n",
        paths.filters_dir / "one.yaml": "name: one\nraw_sieve: keep;\n",
        paths.filters_dir
        / "two.yaml": (
            "name: two\nraw_sieve: |-\n  if true {\n      stop;\n  }\nenabled: false\n"
        ),
        paths.filters_dir / "Zoë.yaml": "name: Zoë\nraw_sieve: 'keep; # ünï'\n",
    }


def test_render_writes_nothing(paths: AccountPaths) -> None:
    render([Filter("a", "keep;")], FilterOrder(("a",)), paths)
    assert not paths.filters_dir.exists()
    assert not paths.order_file.exists()


@given(st.text(min_size=1))
def test_rendered_file_name_stays_inside_the_directory(name: str) -> None:
    files = make_paths(Path("/accounts/work"))
    rendered = render([Filter(name, "keep;")], FilterOrder((name,)), files)
    (path,) = [p for p in rendered if p != files.order_file]
    assert path.parent == files.filters_dir
    assert not any(char in path.name for char in "/\\\0")
    assert not path.name.startswith(".")
    assert path.name.endswith(".yaml")


@pytest.mark.parametrize(
    "names",
    [
        ("Foo", "foo"),
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        (".x", "_x"),
        ("café", "café"),
        ("STRASSE", "straße"),
    ],
)
def test_render_refuses_colliding_file_names_naming_both_filters(
    paths: AccountPaths, names: tuple[str, str]
) -> None:
    filters = [Filter(names[0], "keep;"), Filter(names[1], "stop;")]
    with pytest.raises(ValidationError) as error:
        render(filters, FilterOrder(names), paths)
    assert repr(names[0]) in str(error.value)
    assert repr(names[1]) in str(error.value)


def test_render_accepts_distinct_names(paths: AccountPaths) -> None:
    names = ("a", "a2", "b/c", "b_d")
    filters = [Filter(name, "keep;") for name in names]
    assert len(render(filters, FilterOrder(names), paths)) == len(names) + 1


@st.composite
def declared_sets(draw: st.DrawFn) -> tuple[list[Filter], FilterOrder]:
    names = draw(
        st.lists(
            st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 _./-]{0,10}", fullmatch=True),
            unique=True,
            max_size=5,
        )
    )
    scripts = st.one_of(
        well_formed, st.text(alphabet="ab \t\n;é日", min_size=1).filter(str.strip)
    )
    filters = [
        Filter(name, draw(scripts), enabled=draw(st.booleans())) for name in names
    ]
    return filters, FilterOrder(tuple(draw(st.permutations(names))))


@given(declared_sets())
def test_render_then_load_round_trips(
    declared: tuple[list[Filter], FilterOrder],
) -> None:
    filters, order = declared
    with tempfile.TemporaryDirectory() as root:
        files = make_paths(Path(root))
        try:
            rendered = render(filters, order, files)
        except ValidationError:
            assume(False)
        files.filters_dir.mkdir()
        for path, text in rendered.items():
            path.write_text(text, encoding="utf-8")
        loaded, loaded_order = load_declared(files)
    expected = {
        f.name: Filter(f.name, normalize_whitespace(f.raw_sieve), f.enabled)
        for f in filters
    }
    assert {f.name: f for f in loaded} == expected
    assert loaded_order == order
