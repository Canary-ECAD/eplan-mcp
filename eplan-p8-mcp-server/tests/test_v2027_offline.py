"""Offline tests for api/actions/v2027.py - tools on API members new in EPLAN 2027.

_execute_script is replaced by a capture stub, so no EPLAN is needed. What is
pinned here is what breaks silently inside EPLAN's script engine: a static
reference to a 2027-only member (a compile error on 2026 that surfaces only as
a timeout), a caller value escaping its string literal, and a destructive call
running without its guard.
"""

import re

import pytest

from api.actions import v2027


@pytest.fixture
def capture(monkeypatch):
    captured = {}

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        captured["timeout"] = timeout
        return {"success": True, "results": {"stubbed": True}}

    monkeypatch.setattr(v2027, "_execute_script", fake_execute)
    return captured


INJECTION = '"; System.Environment.Exit(0); string y = "'


def _string_literals_balanced(cs: str) -> bool:
    stripped = cs.replace("\\\\", "").replace('\\"', "")
    return all(line.count('"') % 2 == 0 for line in stripped.splitlines())


def _code_only(cs: str) -> str:
    """C# with string literals emptied and // comments dropped - what compiles."""
    no_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', cs)
    return "\n".join(line.split("//")[0] for line in no_strings.splitlines())


ALL_CALLS = [
    (v2027.live_read_terminal_jumpers, {}),
    (v2027.live_read_terminal_jumpers, {"contains": "-X1", "all_levels": False}),
    (v2027.parts_db_export_edz, {"part_numbers": ["PXC.3209510"], "file_path": "C:/t/a.edz"}),
    (v2027.remove_unused_user_properties, {"target": "project"}),
    (v2027.remove_unused_user_properties, {"target": "project", "confirm": True}),
    (v2027.remove_unused_user_properties, {"target": "parts_db"}),
    (v2027.remove_unused_user_properties, {"target": "parts_db", "confirm": True}),
]


@pytest.mark.parametrize("fn,kwargs", ALL_CALLS)
def test_generated_script_is_well_formed(capture, fn, kwargs):
    fn(**kwargs)
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert "{{RESULT_PATH}}" in cs
    assert cs.count("[Start]") == 1
    # Every template token was substituted.
    for token in ("CONTAINS", "ALL_LEVELS", "LIMIT", "PATH\"", "WANTED",
                  "INCLUDE_REFS", "CONFIRM", "GUARD", "CLASSNAME"):
        assert token not in cs.replace("RESULT_PATH", ""), token


@pytest.mark.parametrize("fn,kwargs", ALL_CALLS)
def test_no_datamodel_using_directive(capture, fn, kwargs):
    fn(**kwargs)
    for line in capture["script"].splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line


@pytest.mark.parametrize("fn,kwargs,member", [
    (v2027.live_read_terminal_jumpers, {}, "GetJumpers"),
    (v2027.parts_db_export_edz, {"part_numbers": ["A"], "file_path": "C:/a.edz"}, "ExportPartsToEDZ"),
    (v2027.remove_unused_user_properties, {"target": "project", "confirm": True},
     "RemoveUnusedUserPropertyDefinitions"),
    (v2027.remove_unused_user_properties, {"target": "parts_db", "confirm": True},
     "RemoveUnusedUserPropertyDefinitions"),
])
def test_2027_members_are_reached_by_reflection(capture, fn, kwargs, member):
    """A static `.Member(` call would not compile on 2026; it must be a name string."""
    fn(**kwargs)
    cs = capture["script"]
    assert '"%s"' % member in cs
    assert ".%s(" % member not in _code_only(cs)
    assert "new in EPLAN 2027" in cs


def test_jumpers_values_cannot_escape_their_literal(capture):
    v2027.live_read_terminal_jumpers(contains=INJECTION)
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert "System.Environment.Exit(0);" not in cs.replace('\\"', "").split('"')[0::2][0]


def test_jumpers_token_inside_a_value_is_not_rewritten(capture):
    """One-pass substitution: a filter containing a token name stays literal."""
    v2027.live_read_terminal_jumpers(contains="LIMIT ALL_LEVELS", limit=7)
    cs = capture["script"]
    assert 'Matches(tn, "LIMIT ALL_LEVELS")' in cs
    assert "jumpers.Count >= 7" in cs


def test_jumpers_rejects_a_non_integer_limit(capture):
    r = v2027.live_read_terminal_jumpers(limit="5; Exit()")
    assert r["success"] is False
    assert "script" not in capture


def test_jumpers_reads_bridge_fields_not_properties(capture):
    """BridgeSegments / BridgedTerminal are public FIELDS on Terminal.Bridge."""
    v2027.live_read_terminal_jumpers()
    cs = capture["script"]
    assert 'GetField("BridgeSegments")' in cs
    assert 'GetField("BridgedTerminal")' in cs


def test_edz_values_cannot_escape_their_literal(capture):
    v2027.parts_db_export_edz(part_numbers=[INJECTION, "PATH"],
                              file_path="C:/t/" + INJECTION + ".edz")
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert '"PATH"' in cs  # a part number equal to a token name stays literal


@pytest.mark.parametrize("kwargs", [
    {"part_numbers": [], "file_path": "C:/a.edz"},
    {"part_numbers": None, "file_path": "C:/a.edz"},
    {"part_numbers": ["A"], "file_path": "C:/a.xml"},
    {"part_numbers": [5], "file_path": "C:/a.edz"},
    {"part_numbers": ["A{{RESULT_PATH}}"], "file_path": "C:/a.edz"},
])
def test_edz_rejects_bad_arguments_before_any_script(capture, kwargs):
    r = v2027.parts_db_export_edz(**kwargs)
    assert r["success"] is False
    assert "script" not in capture


def test_edz_accepts_a_single_part_number_string(capture):
    v2027.parts_db_export_edz(part_numbers="ABC", file_path="C:/a.edz")
    assert '{ "ABC" }' in capture["script"]


def test_edz_include_references_flag_is_passed(capture):
    v2027.parts_db_export_edz(part_numbers=["A"], file_path="C:/a.edz",
                              include_references=False)
    assert "new object[] { path, parts, false }" in capture["script"]


def test_remove_unused_rejects_unknown_target(capture):
    r = v2027.remove_unused_user_properties(target="everything", confirm=True)
    assert r["success"] is False
    assert "script" not in capture


@pytest.mark.parametrize("target", ["project", "parts_db"])
def test_remove_unused_preview_never_calls_the_remover(capture, target):
    r = v2027.remove_unused_user_properties(target=target)
    cs = capture["script"]
    assert "if (false)" in cs
    assert "if (true)" not in cs
    assert r["mode"].startswith("preview")


def test_remove_unused_project_write_is_scratch_guarded(capture):
    v2027.remove_unused_user_properties(target="project", confirm=True)
    cs = capture["script"]
    assert "GuardScratch(project, false," in cs
    assert cs.index("GuardScratch(project, false,") < cs.index('"RemoveUnusedUserPropertyDefinitions"')


def test_remove_unused_project_guard_can_be_waived_explicitly(capture):
    v2027.remove_unused_user_properties(target="project", confirm=True,
                                        allow_real_project=True)
    assert "GuardScratch(project, true," in capture["script"]


def test_remove_unused_project_preview_needs_no_guard(capture):
    v2027.remove_unused_user_properties(target="project")
    assert "GuardScratch(project," not in capture["script"]
