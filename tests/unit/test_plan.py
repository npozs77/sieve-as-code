"""Unit 4 BR-3 to BR-15: diff and plan."""

import json
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sieve_as_code.client import ProtonClient, connect
from sieve_as_code.declared import render
from sieve_as_code.model import (
    ClientError,
    Filter,
    FilterOrder,
    FilterSet,
    SieveAsCodeError,
    ValidationError,
)
from sieve_as_code.plan import PlanEntry, PlanResult, Reorder, diff, plan
from sieve_as_code.settings import AccountPaths
from tests.fake_proton import FakeProton

SCRIPTS = ["keep;", "stop;", "keep;  ", "\tkeep;", "discard;"]
NAMES = st.lists(st.sampled_from("abcdef"), unique=True, max_size=6)
EXPIRE = 'require ["vnd.proton.expire"];\nexpire "day" "7";'


def state(*items: tuple[str, str, bool] | str, live: bool = False) -> FilterSet:
    """A FilterSet from `name` or `(name, script, enabled)` in sequence order."""
    rows = [(i, "keep;", True) if isinstance(i, str) else i for i in items]
    filters = tuple(Filter(n, s, e, f"id-{n}" if live else None) for n, s, e in rows)
    return FilterSet(filters, FilterOrder(tuple(n for n, _, _ in rows)))


def kinds(result: PlanResult) -> list[tuple[str, str]]:
    return [(e.kind, e.name) for e in result.entries]


@st.composite
def pairs(draw: st.DrawFn) -> tuple[FilterSet, FilterSet]:
    def build(names: list[str], live: bool) -> FilterSet:
        rows = [(n, draw(st.sampled_from(SCRIPTS)), draw(st.booleans())) for n in names]
        return state(*rows, live=live)

    return build(draw(NAMES), False), build(draw(NAMES), True)


def simulate_apply(
    result: PlanResult, declared: FilterSet, live: FilterSet
) -> FilterSet:
    """What `apply` leaves behind, assuming new filters land last."""
    wanted = {f.name: f for f in declared.filters}
    rows = {f.name: f for f in live.filters}
    sequence = list(live.order.sequence)
    for entry in result.entries:
        if entry.kind == "create":
            rows[entry.name] = replace(wanted[entry.name], live_id=f"new-{entry.name}")
            sequence.append(entry.name)
        elif entry.kind == "content":
            rows[entry.name] = replace(
                rows[entry.name], raw_sieve=wanted[entry.name].raw_sieve
            )
        elif entry.kind == "enabled":
            rows[entry.name] = replace(rows[entry.name], enabled=bool(entry.enabled))
        else:
            rows[entry.name] = replace(rows[entry.name], enabled=False)
    if result.reorder:
        rest = [n for n in sequence if n not in result.reorder.new]
        sequence = [*result.reorder.new, *rest]
    return FilterSet(tuple(rows[n] for n in sequence), FilterOrder(tuple(sequence)))


@given(pairs())
def test_applying_a_plan_leaves_nothing_to_plan(
    pair: tuple[FilterSet, FilterSet],
) -> None:  # BR-9, BR-15, NFR-REL.1
    declared, live = pair
    after = simulate_apply(diff(declared, live, frozenset()), declared, live)
    assert diff(declared, after, frozenset()).outcome == "clean"


@given(pairs())
def test_diff_of_a_state_with_itself_is_clean_and_empty(
    pair: tuple[FilterSet, FilterSet],
) -> None:  # BR-15
    same = replace(
        pair[1], filters=tuple(replace(f, live_id=None) for f in pair[1].filters)
    )
    result = diff(same, pair[1], frozenset())
    assert result == PlanResult((), (), None, (), ())
    assert result.outcome == "clean"


@given(st.permutations("abcd"), st.permutations("abcd"))
def test_any_number_of_moves_is_one_reorder_entry(
    declared: list[str], live: list[str]
) -> None:  # BR-8
    result = diff(state(*declared), state(*live, live=True), frozenset())
    assert result.entries == ()
    assert (result.reorder is None) == (declared == live)
    if result.reorder:
        assert result.reorder == Reorder(tuple(live), tuple(declared))


SPACING = st.sampled_from(["", " ", "\t", "  \t", "\r"])


@given(SPACING, st.sampled_from(["", "\n", "\n\n"]))
def test_whitespace_only_differences_are_not_content_changes(
    trail: str, newlines: str
) -> None:  # BR-4
    noisy = f"if true {{{trail}\n\tstop;{trail}\n}}{trail}{newlines}"
    plain = "if true {\n    stop;\n}"
    result = diff(
        state(("x", plain, True)), state(("x", noisy, True), live=True), frozenset()
    )
    assert result.outcome == "clean"


def test_each_entry_kind_and_the_apply_order() -> None:  # BR-5, BR-6, BR-7, BR-14
    declared = state(
        ("new", "keep;", False), ("edit", "stop;", True), ("flip", "keep;", False)
    )
    live = state(
        ("flip", "keep;", True),
        ("edit", "keep;", True),
        ("gone", "keep;", True),
        ("quiet", "keep;", False),
        live=True,
    )
    result = diff(declared, live, frozenset())
    assert kinds(result) == [
        ("create", "new"),
        ("content", "edit"),
        ("enabled", "flip"),
        ("live-only", "gone"),
    ]
    assert result.entries[0] == PlanEntry("create", "new", None, False)
    assert result.entries[2] == PlanEntry("enabled", "flip", "id-flip", False)
    assert result.informational == ("quiet",)
    assert result.reorder == Reorder(("flip", "edit", "new"), ("new", "edit", "flip"))


def test_content_and_enabled_both_differ_gives_two_entries() -> None:  # BR-6
    result = diff(
        state(("a", "stop;", False)),
        state(("a", "keep;", True), live=True),
        frozenset(),
    )
    assert kinds(result) == [("content", "a"), ("enabled", "a")]


def test_names_match_case_sensitively() -> None:  # BR-3
    result = diff(state("Foo"), state("foo", live=True), frozenset())
    assert kinds(result) == [("create", "Foo"), ("live-only", "foo")]


def test_a_disabled_live_only_filter_is_informational_not_drift() -> None:  # BR-7
    result = diff(state("a"), state("a", ("z", "keep;", False), live=True), frozenset())
    assert result.informational == ("z",) and result.outcome == "clean"


def test_live_only_filters_do_not_cause_a_reorder() -> None:  # BR-8
    result = diff(state("a", "b"), state("a", "z", "b", live=True), frozenset())
    assert result.reorder is None


def test_created_filter_at_the_end_needs_no_reorder_but_mid_sequence_does() -> (
    None
):  # BR-9
    live = state("a", "b", live=True)
    assert diff(state("a", "b", "x"), live, frozenset()).reorder is None
    assert diff(state("a", "x", "b"), live, frozenset()).reorder == Reorder(
        ("a", "b", "x"), ("a", "x", "b")
    )


FILEINTO = 'require ["fileinto"];\nfileinto "{}";'


def targeted(*targets: tuple[str, str, bool]) -> FilterSet:
    return state(*((n, FILEINTO.format(t), e) for n, t, e in targets))


def test_missing_targets_are_listed_once_with_users_in_first_use_order() -> (
    None
):  # BR-10
    declared = targeted(("a", "Zed", True), ("b", "Alpha", True), ("c", "Zed", True))
    result = diff(declared, state(live=True), frozenset())
    assert [(m.name, m.used_by) for m in result.missing_targets] == [
        ("Zed", ("a", "c")),
        ("Alpha", ("b",)),
    ]
    assert result.outcome == "drift"


@pytest.mark.parametrize("name", ["Inbox", "ARCHIVE", "spam", "Trash"])
def test_built_in_mailboxes_are_never_missing(name: str) -> None:  # BR-10
    assert (
        diff(
            targeted(("a", name, True)), state("a", live=True), frozenset()
        ).missing_targets
        == ()
    )


def test_existing_folders_and_labels_are_not_missing_and_matching_is_exact() -> (
    None
):  # BR-10
    declared = targeted(("a", "Parent/Child", True), ("b", "receipts", True))
    result = diff(
        declared, state("a", "b", live=True), frozenset({"Parent/Child", "Receipts"})
    )
    assert [m.name for m in result.missing_targets] == ["receipts"]


def test_targets_of_disabled_filters_are_ignored() -> None:  # BR-10
    result = diff(targeted(("a", "Nope", False)), state("a", live=True), frozenset())
    assert result.missing_targets == () and result.outcome == "drift"


@pytest.mark.parametrize(
    "script",
    [
        'require ["fileinto","variables"];\nset "f" "x";\nfileinto "${f}";',
        'require ["fileinto"];\nfileinto :flags ["a"] ["b"];',
        'require ["fileinto"];\nfileinto text:\nX\n.\n;',
    ],
)
def test_unreadable_target_in_an_enabled_filter_fails_without_script_text(
    script: str,
) -> None:  # BR-11
    with pytest.raises(ValidationError, match="'a' line [23]") as caught:
        diff(state(("a", script, True)), state(live=True), frozenset())
    assert "fileinto" not in str(caught.value).replace("fileinto target", "")


def test_unreadable_target_in_a_disabled_filter_is_ignored() -> None:  # BR-11
    script = 'require ["fileinto"];\nfileinto "${x}";'
    assert (
        diff(state(("a", script, False)), state(live=True), frozenset()).missing_targets
        == ()
    )


def test_destructive_extension_is_flagged_only_when_the_filter_is_written() -> (
    None
):  # BR-12
    written = diff(state(("a", EXPIRE, True)), state(live=True), frozenset())
    assert [(f.name, f.extension) for f in written.flags] == [
        ("a", "vnd.proton.expire")
    ]
    unchanged = diff(
        state(("a", EXPIRE, True)), state(("a", EXPIRE, True), live=True), frozenset()
    )
    assert unchanged.flags == () and unchanged.outcome == "clean"
    assert diff(state(("a", EXPIRE, False)), state(live=True), frozenset()).flags == ()


def test_flags_do_not_change_the_outcome() -> None:  # BR-12, BR-13
    result = diff(
        state(("a", EXPIRE, True)), state(("a", EXPIRE, True), live=True), frozenset()
    )
    assert result.outcome == "clean"


# --- plan() ---


@pytest.fixture
def client(fake_proton: FakeProton, work_account: AccountPaths) -> ProtonClient:
    return connect(work_account)


def write_declared(paths: AccountPaths, declared: FilterSet) -> None:
    paths.filters_dir.mkdir(parents=True, exist_ok=True)
    for path, text in render(declared.filters, declared.order, paths).items():
        path.write_text(text)


def audit_lines(paths: AccountPaths) -> list[dict[str, object]]:
    return [json.loads(line) for line in paths.audit_log.read_text().splitlines()]


def test_plan_audits_clean_with_counts_only(
    client: ProtonClient, fake_proton: FakeProton, work_account: AccountPaths
) -> None:  # BR-13
    fake_proton.add_filter("a", "keep;")
    write_declared(work_account, state("a"))
    result = plan(work_account, client)
    (line,) = audit_lines(work_account)
    assert result.outcome == "clean"
    assert (line["kind"], line["outcome"]) == ("check", "clean")
    assert line["detail"] == {
        "entries": 0,
        "missing_targets": 0,
        "flags": 0,
        "renamed": 0,
    }


def test_plan_audits_drift_and_changes_nothing(
    client: ProtonClient, fake_proton: FakeProton, work_account: AccountPaths
) -> None:  # BR-13, BR-16
    fake_proton.add_filter("a", "keep;")
    write_declared(work_account, state(("a", "stop;", True), ("b", "keep;", True)))
    before = list(fake_proton.filters)
    result = plan(work_account, client)
    assert result.outcome == "drift"
    assert audit_lines(work_account)[0]["detail"] == {
        "entries": 2,
        "missing_targets": 0,
        "flags": 0,
        "renamed": 0,
    }
    assert fake_proton.filters == before
    assert {c.path[-1] for c in fake_proton.calls} <= {"get", "list", "--version"}


def test_plan_audits_invalid_declared_files_and_reraises(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-13
    with pytest.raises(ValidationError):
        plan(work_account, client)
    (line,) = audit_lines(work_account)
    assert line["outcome"] == "invalid"


def test_plan_audits_unreadable_target_as_invalid(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-11, BR-13
    write_declared(
        work_account, state(("a", 'require ["fileinto"];\nfileinto "${x}";', True))
    )
    with pytest.raises(ValidationError):
        plan(work_account, client)
    assert audit_lines(work_account)[0]["outcome"] == "invalid"


def test_plan_does_not_audit_when_proton_cannot_be_read(
    client: ProtonClient, fake_proton: FakeProton, work_account: AccountPaths
) -> None:  # BR-13
    write_declared(work_account, state("a"))
    fake_proton.failures["mail settings filters list"] = (5, "network")
    with pytest.raises(ClientError):
        plan(work_account, client)
    assert not work_account.audit_log.exists()


def test_plan_raises_when_the_audit_line_cannot_be_written(
    client: ProtonClient, work_account: AccountPaths
) -> None:
    write_declared(work_account, state())
    work_account.audit_log.parent.mkdir(parents=True, exist_ok=True)
    work_account.audit_log.mkdir()
    with pytest.raises(SieveAsCodeError, match="audit log"):
        plan(work_account, client)


def test_plan_lists_missing_targets_from_the_account(
    client: ProtonClient, fake_proton: FakeProton, work_account: AccountPaths
) -> None:  # BR-10
    fake_proton.folders.append({"id": "t1", "name": "Known", "path": "Known"})
    write_declared(work_account, targeted(("a", "Known", True), ("b", "Gone", True)))
    result = plan(work_account, client)
    assert [m.name for m in result.missing_targets] == ["Gone"]
    assert audit_lines(work_account)[0]["detail"] == {
        "entries": 2,
        "missing_targets": 1,
        "flags": 0,
        "renamed": 0,
    }


def test_plan_reports_renamed_duplicates_without_calling_them_drift(
    client: ProtonClient, fake_proton: FakeProton, work_account: AccountPaths
) -> None:  # Unit 4 BR-2, BR-13
    fake_proton.add_filter("a", "keep;")
    fake_proton.add_filter("a", "keep;")
    write_declared(work_account, state("a", "a (1)"))
    result = plan(work_account, client)
    assert result.outcome == "clean"
    assert [(r.original, r.name) for r in result.renamed] == [("a", "a (1)")]
    assert audit_lines(work_account)[0]["detail"] == {
        "entries": 0,
        "missing_targets": 0,
        "flags": 0,
        "renamed": 1,
    }


def test_plan_refuses_a_client_connected_to_another_account(
    client: ProtonClient, work_account: AccountPaths
) -> None:  # BR-18
    other = replace(work_account, account="other")
    with pytest.raises(ValidationError, match="'other'"):
        plan(other, client)
    assert not work_account.audit_log.exists()


def test_snapshot_mode_skips_target_and_flag_checks() -> None:  # BR-19
    script = 'require ["fileinto","vnd.proton.expire"];\nfileinto "${x}";'
    snapshot = state(("a", script, True))
    result = diff(snapshot, state(live=True), None)
    assert [(e.kind, e.name) for e in result.entries] == [("create", "a")]
    assert result.missing_targets == () and result.flags == ()


def test_an_unreadable_target_wins_over_a_missing_target() -> None:  # BR-10, BR-11
    declared = state(
        ("a", FILEINTO.format("Gone"), True),
        ("b", 'require ["fileinto"];\nfileinto "${x}";', True),
    )
    with pytest.raises(ValidationError, match="'b'"):
        diff(declared, state(live=True), frozenset())
