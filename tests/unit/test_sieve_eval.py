"""Unit 8 BR-6 to BR-8, BR-10, BR-12, BR-13: the Sieve evaluator."""

import contextlib
import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sieve_as_code._model import SieveAsCodeError, UnsupportedSieve
from sieve_as_code._sieve_eval import MailMessage, Outcome, compile_script, evaluate


def message(**fields: object) -> MailMessage:
    base: dict[str, object] = {
        "id": "m1",
        "subject": "Weekly Digest",
        "from_name": "News Desk",
        "from_address": "Desk@News.Example",
        "time": 0,
        "unread": True,
        "labels": frozenset(),
    }
    return MailMessage(**{**base, **fields})  # type: ignore[arg-type]


def outcome(script: str, **fields: object) -> Outcome:
    return evaluate(compile_script(script), message(**fields))


def hit(test: str, **fields: object) -> bool:
    script = f'require ["fileinto"];\nif {test} {{ fileinto "x"; }}'
    return bool(outcome(script, **fields).files)


def quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@pytest.mark.parametrize(
    ("test", "expected"),
    [
        ('address :is "from" "desk@news.example"', True),
        ('address "from" "DESK@NEWS.EXAMPLE"', True),
        ('address :is "from" "news.example"', False),
        ('address :contains "from" "news"', True),
        ('address :matches "from" "d*@news.?xample"', True),
        ('address :domain :is "from" "news.example"', True),
        ('address :localpart :is "from" "desk"', True),
        ('address :localpart :is "from" "news.example"', False),
        ('address :is "from" ["nobody@x", "desk@news.example"]', True),
        ('header :contains "from" "news desk"', True),
        ('header :is "from" "News Desk <Desk@News.Example>"', True),
        ('header :matches "subject" "weekly*"', True),
        ('header :is "subject" "weekly"', False),
        ('header :contains ["from", "subject"] "digest"', True),
        ('header :contains "SUBJECT" "digest"', True),
        ("true", True),
        ("false", False),
        ('not header :contains "subject" "digest"', False),
        ('allof(true, header :contains "subject" "digest")', True),
        ("allof(true, false)", False),
        ('anyof(false, header :contains "subject" "digest")', True),
        ("anyof(false, false)", False),
    ],
)
def test_tests_match_as_the_subset_defines(test: str, expected: bool) -> None:  # BR-7
    assert hit(test) is expected


def test_a_message_without_an_address_matches_no_address_test() -> None:  # BR-7
    assert not hit('address :matches "from" "*"', from_address="")
    assert hit('header :is "from" ""', from_name="", from_address="")


def test_an_address_without_at_sign_is_all_local_part() -> None:  # BR-7
    assert hit('address :localpart :is "from" "root"', from_address="root")
    assert hit('address :domain :is "from" ""', from_address="root")


def test_wildcards_can_be_escaped() -> None:  # BR-7
    assert hit('header :matches "subject" "a\\\\*b"', subject="a*b")
    assert not hit('header :matches "subject" "a\\\\*b"', subject="axb")
    assert hit('header :matches "subject" "a\\\\"', subject="a\\")


def test_branches_stop_and_comments() -> None:  # BR-8
    script = """require ["fileinto"]; # comment
/* block
comment */
if header :contains "subject" "zzz" { fileinto "A"; }
elsif header :contains "subject" "digest" { fileinto "B"; stop; }
else { fileinto "C"; }
fileinto "D";
"""
    assert outcome(script).files == ("B",)
    assert outcome(script, subject="x").files == ("C", "D")
    assert outcome(script, subject="zzz").files == ("A", "D")


def test_stop_ends_the_script_from_inside_a_nested_block() -> None:  # BR-8
    script = 'if true { if true { stop; } fileinto "A"; } fileinto "B";'
    assert outcome(script).files == ()


def test_duplicate_targets_keep_their_first_spelling() -> None:  # BR-8
    assert outcome('fileinto "News"; fileinto "NEWS"; fileinto "B";').files == (
        "News",
        "B",
    )


def test_an_if_without_else_does_nothing_when_false() -> None:  # BR-8
    assert outcome('if false { fileinto "A"; }').files == ()


def test_flag_commands_build_the_final_set() -> None:  # BR-12
    assert outcome('addflag "\\\\Seen"; addflag ["\\\\FLAGGED"];').flags == {
        "\\seen",
        "\\flagged",
    }
    assert outcome('addflag "\\\\Seen"; setflag "\\\\Flagged";').flags == {"\\flagged"}
    assert outcome(
        'addflag ["\\\\Seen", "\\\\Flagged"]; removeflag "\\\\Seen";'
    ).flags == {"\\flagged"}


def test_expire_keeps_the_last_value() -> None:  # BR-13
    assert outcome('expire "day" "7"; expire "DAY" "30";').expire_days == 30
    assert outcome("stop;").expire_days is None


def test_targets_and_recipient_keys_are_collected() -> None:  # BR-9, BR-10
    compiled = compile_script(
        'if anyof(address :is "to" "A@B.com", header :contains ["to", "subject"] "X") '
        '{ fileinto "A"; fileinto "a"; } else { fileinto "B"; }'
    )
    assert compiled.mailboxes == ("A", "B")
    assert compiled.recipient_keys == ("a@b.com", "x")


def test_recipient_tests_use_the_matched_keys() -> None:  # BR-10
    test = 'address :is "to" "team@x.org"'
    assert not hit(test)
    assert hit(test, to_keys=frozenset({"team@x.org"}))
    assert not hit(test, to_keys=frozenset({"other"}))


@pytest.mark.parametrize(
    ("script", "construct", "line"),
    [
        ("size :over 1M;", "size", 1),
        ("\n\nkeep;", "keep", 3),
        ('fileinto :copy "A";', ":copy", 1),
        ("fileinto;", "syntax", 1),
        ('if header :regex "from" "x" { stop; }', ":regex", 1),
        ('if header :comparator "i;octet" "from" "x" { stop; }', ":comparator", 1),
        ('if header :all "from" "x" { stop; }', ":all", 1),
        ('if header :contains "cc" "x" { stop; }', "header name", 1),
        ('if exists "x" { stop; }', "exists", 1),
        ("if { stop; }", "syntax", 1),
        ('vacation "away";', "vacation", 1),
        ('addflag "\\\\Deleted";', "flag", 1),
        ('expire "week" "2";', "expire", 1),
        ('expire "day" "0";', "expire", 1),
        ('expire "day" "x";', "expire", 1),
        ('if address :matches "to" "a*" { stop; }', "to test", 1),
        ('if address :domain "to" "a" { stop; }', "to test", 1),
        ('if header :contains "from" "x" { stop;', "syntax", 1),
        ('if header :contains "from" "x" stop;', "syntax", 1),
        ('if header :contains "from" ["x", ] { stop; }', "syntax", 1),
        ("stop", "syntax", 1),
        ("}", "syntax", 1),
        ('"stop";', "syntax", 1),
        ("@", "character", 1),
        ('require "x"; fileinto "unterminated', "character", 1),
        ("text:\nx\n.\n;", "text block", 1),
    ],
)
def test_anything_else_is_unsupported(script: str, construct: str, line: int) -> None:
    with pytest.raises(UnsupportedSieve) as raised:  # BR-6
        compile_script(script)
    assert (raised.value.construct, raised.value.line) == (construct, line)
    assert 'x" {' not in str(raised.value)


def test_more_than_ten_recipient_keys_is_unsupported() -> None:  # BR-10
    keys = ", ".join(f'"k{n}"' for n in range(11))
    with pytest.raises(UnsupportedSieve, match="recipient keys"):
        compile_script(f'if header :is "to" [{keys}] {{ stop; }}')
    ten = ", ".join(f'"k{n}"' for n in range(10))
    compile_script(f'if header :is "to" [{ten}] {{ stop; }}')


def test_deep_nesting_is_unsupported_not_a_crash() -> None:  # BR-6
    with pytest.raises(UnsupportedSieve, match="nesting"):
        compile_script("if " + "not " * 5000 + "true { stop; }")


def test_unsupported_sieve_is_a_package_error() -> None:
    assert issubclass(UnsupportedSieve, SieveAsCodeError)


def test_results_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome("stop;").expire_days = 1  # type: ignore[misc]


ASCII = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=0x24F))


def ascii_fold(text: str) -> str:
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in text)


@given(value=ASCII, key=ASCII)
def test_is_and_contains_follow_the_ascii_casemap_comparator(
    value: str, key: str
) -> None:  # BR-7
    subject = {"subject": value}
    assert hit(f'header :contains "subject" {quoted(key)}', **subject) == (
        ascii_fold(key) in ascii_fold(value)
    )
    assert hit(f'header :is "subject" {quoted(key)}', **subject) == (
        ascii_fold(key) == ascii_fold(value)
    )


def reference_matches(pattern: str, text: str) -> bool:
    if not pattern:
        return not text
    head, rest = pattern[0], pattern[1:]
    if head == "*":
        return any(reference_matches(rest, text[i:]) for i in range(len(text) + 1))
    if not text:
        return False
    return (head == "?" or head == text[0]) and reference_matches(rest, text[1:])


@given(
    pattern=st.text(alphabet="ab*?", max_size=6),
    value=st.text(alphabet="abAB", max_size=6),
)
def test_matches_agrees_with_a_reference_wildcard_matcher(
    pattern: str, value: str
) -> None:  # BR-7
    test = f'header :matches "subject" {quoted(pattern)}'
    assert hit(test, subject=value) == reference_matches(pattern.lower(), value.lower())


@given(st.booleans(), st.booleans(), st.booleans())
def test_not_allof_and_anyof_are_boolean_algebra(a: bool, b: bool, c: bool) -> None:
    names = {True: "true", False: "false"}
    args = f"{names[a]}, {names[b]}, {names[c]}"
    assert hit(f"not {names[a]}") == (not a)
    assert hit(f"allof({args})") == all([a, b, c])
    assert hit(f"anyof({args})") == any([a, b, c])


TOKENS = [
    "if", "elsif", "else", "true", "false", "not", "allof", "anyof", "(", ")", "{", "}",
    "[", "]", ",", ";", '"a"', '"from"', '"to"', '"day"', '"1"', '"\\\\Seen"',
    "fileinto", "stop", "address", "header", ":is", ":contains", ":all", "addflag",
    "require", "expire",
]  # fmt: skip


@given(st.lists(st.sampled_from(TOKENS), max_size=25) | st.text(max_size=40))
def test_any_text_compiles_or_is_unsupported(parts: list[str] | str) -> None:  # BR-6
    script = parts if isinstance(parts, str) else " ".join(parts)
    with contextlib.suppress(UnsupportedSieve):
        compile_script(script)


REQUIRE = (
    'require ["fileinto", "imap4flags", "environment", "variables", "relational", '
    '"comparator-i;ascii-numeric", "spamtest"];\n'
)
TEST = (
    'environment :matches "vnd.proton.spam-threshold" "*",\n'
    '  spamtest :value "ge" :comparator "i;ascii-numeric" "${1}"'
)
GUARDS = [
    "# Do not run this script on spam messages\n"
    f"if allof ({TEST})\n{{\n  return;\n}}\n",
    f"if allof ({TEST})\n{{\n\n}}\n",
    f"/* guard */ IF ALLOF ({TEST}) {{ RETURN; }}\n",
    'if allof (environment :matches "vnd.proton.spam-threshold" "*", '
    'spamtest :value "ge" :comparator "i;ascii-numeric" "${1}") { return; }\n',
]
BODIES = [
    'fileinto "x";',
    'if header :contains "subject" "digest" { fileinto "x"; } else { stop; }',
    'addflag "\\\\Seen"; fileinto "y";',
]


@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("subject", ["Weekly Digest", "other"])
def test_the_proton_spam_guard_is_ignored_in_every_layout(
    guard: str, subject: str
) -> None:  # BR-30
    body = BODIES[1]
    assert outcome(REQUIRE + guard + body, subject=subject) == outcome(
        REQUIRE + body, subject=subject
    )


@given(st.sampled_from(GUARDS), st.sampled_from(BODIES), st.text(max_size=20))
def test_the_guard_never_changes_an_outcome(
    guard: str, body: str, subject: str
) -> None:  # BR-30
    assert outcome(REQUIRE + guard + body, subject=subject) == outcome(
        REQUIRE + body, subject=subject
    )


def test_a_script_of_only_the_guard_compiles_to_nothing() -> None:  # BR-30
    compiled = compile_script(REQUIRE + GUARDS[0])
    assert compiled.mailboxes == () and compiled.recipient_keys == ()
    assert outcome(REQUIRE + GUARDS[1]) == Outcome((), frozenset(), None)


@pytest.mark.parametrize(
    ("script", "construct"),
    [
        (GUARDS[3].replace("spam-threshold", "other-threshold"), "environment"),
        (GUARDS[3].replace('"ge"', '"gt"'), "environment"),
        (GUARDS[3].replace("{ return; }", "{ return; stop; }"), "environment"),
        (GUARDS[3].replace("{ return; }", "{ return; } else { stop; }"), "else"),
        ('fileinto "x";\n' + GUARDS[3], "environment"),
        (GUARDS[3] + GUARDS[3], "environment"),
        (f"if true {{ {GUARDS[3]} }}", "environment"),
        ("return;", "return"),
    ],
)
def test_other_forms_of_the_guard_stay_unsupported(
    script: str, construct: str
) -> None:  # BR-30
    with pytest.raises(UnsupportedSieve) as raised:
        compile_script(REQUIRE + script)
    assert raised.value.construct == construct
