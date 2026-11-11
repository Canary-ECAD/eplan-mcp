"""Offline tests for api/actions/scripted.py: the generated C# must stay
well-formed and injection-free for every parameter. _execute_script is
replaced by a capture stub, so no EPLAN is needed."""

import os
import re

import pytest

from api.actions import scripted


@pytest.fixture
def capture(monkeypatch):
    """Stub _execute_script; captures the generated C# instead of running it."""
    captured = {}

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        return {"success": True, "results": {"stubbed": True}}

    monkeypatch.setattr(scripted, "_execute_script", fake_execute)
    return captured


INJECTION = '100).ToList(); System.Environment.Exit(0); var x = db.Parts.Take(1'


def _string_literals_balanced(cs: str) -> bool:
    """After stripping escape sequences, every line must contain an even
    number of quotes - i.e. no value broke out of its string literal."""
    stripped = cs.replace("\\\\", "").replace('\\"', "")
    return all(line.count('"') % 2 == 0 for line in stripped.splitlines())


# ---------------------------------------------------------------------------
# parts_db_query: limit must be an integer, never raw text in the script
# ---------------------------------------------------------------------------

def test_parts_db_query_rejects_non_integer_limit(capture):
    result = scripted.parts_db_query(limit=INJECTION)
    assert result["success"] is False
    assert "limit" in result["error"].lower()
    assert "script" not in capture, "malicious limit must never reach the script"


def test_parts_db_query_coerces_numeric_string_limit(capture):
    result = scripted.parts_db_query(limit="25")
    assert result["success"] is True
    assert ".Take(25)" in capture["script"]


def test_parts_db_query_default_limit_in_script(capture):
    scripted.parts_db_query()
    assert ".Take(100)" in capture["script"]


# ---------------------------------------------------------------------------
# filter_property / filter_value hardening
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "PartNr; evil()",
    'PartNr")',
    "1Leading",
    "a-b",
    "a b",
])
def test_query_and_count_reject_non_identifier_filter_property(capture, bad):
    for func in (scripted.parts_db_query, scripted.parts_db_count):
        result = func(filter_property=bad, filter_value="x")
        assert result["success"] is False
        assert "filter_property" in result["error"]
    assert "script" not in capture


def test_filter_value_is_escaped_not_injected(capture):
    scripted.parts_db_query(filter_property="PartNr", filter_value='X"); evil(); ("')
    script = capture["script"]
    # The payload's quotes must arrive escaped, leaving every literal intact.
    assert 'X\\"); evil(); (\\"' in script
    assert _string_literals_balanced(script)


def test_return_properties_are_escaped(capture):
    scripted.parts_db_query(return_properties=['PartNr', 'bad"name'])
    script = capture["script"]
    assert 'bad\\"name' in script


# ---------------------------------------------------------------------------
# parts_db_get_part / create / update escaping
# ---------------------------------------------------------------------------

def test_get_part_escapes_part_number(capture):
    scripted.parts_db_get_part('P"); evil(); ("')
    script = capture["script"]
    assert 'P\\"); evil(); (\\"' in script
    assert _string_literals_balanced(script)


def test_create_with_no_properties_yields_empty_arrays(capture):
    result = scripted.parts_db_create("PN-1")
    assert result["success"] is True
    script = capture["script"]
    assert "string[] propNames = new string[] {  };" in script
    assert "string[] propValues = new string[] {  };" in script


def test_create_property_values_stringified_and_escaped(capture):
    scripted.parts_db_create("PN-2", {"ARTICLE_DESCR1": 'x"y', "ARTICLE_NOTE": 42})
    script = capture["script"]
    assert '"x\\"y"' in script
    assert '"42"' in script


def test_update_escapes_all_three_arguments(capture):
    scripted.parts_db_update('p"n', 'prop"name', 'va"lue')
    stripped = capture["script"].replace('\\"', "").replace("\\\\", "")
    for line in stripped.splitlines():
        assert line.count('"') % 2 == 0, f"unbalanced literal: {line!r}"


# ---------------------------------------------------------------------------
# settings / pathmap: numeric coercion and escaping
# ---------------------------------------------------------------------------

def test_settings_index_coercion_blocks_injection(capture):
    # A non-numeric index raises before any script is generated.
    with pytest.raises((TypeError, ValueError)):
        scripted.settings_get_string("USER.X", index="1); evil((")
    assert "script" not in capture


def test_settings_set_int_coerces_value(capture):
    result = scripted.settings_set_int("USER.X", "7")
    assert result["success"] is True
    assert '"USER.X", 7, 0' in capture["script"]


def test_settings_path_with_quotes_escaped(capture):
    scripted.settings_get_bool('USER."quoted"')
    assert 'USER.\\"quoted\\"' in capture["script"]


def test_pathmap_substitute_escapes_backslashes(capture):
    scripted.pathmap_substitute(r"C:\Users\test\$(DOC)")
    script = capture["script"]
    assert r"C:\\Users\\test" in script


# ---------------------------------------------------------------------------
# C# 5 discipline: EPLAN's script engine predates C# 6, and a compile error
# is invisible from here (it looks like a timeout), so guard the syntax.
# ---------------------------------------------------------------------------

# Every script-generating entry point, with arguments that exercise the
# branches that build C# (filters on, properties supplied).
# execute_custom_script is excluded: its C# comes from the caller, not here.
SCRIPT_GENERATORS = [
    ("parts_db_query", lambda: scripted.parts_db_query(limit=5)),
    ("parts_db_query_filtered", lambda: scripted.parts_db_query(
        filter_property="PartNr", filter_value="147", limit=5)),
    ("parts_db_count", lambda: scripted.parts_db_count()),
    ("parts_db_count_filtered", lambda: scripted.parts_db_count(
        filter_property="PartNr", filter_value="147")),
    ("parts_db_get_part", lambda: scripted.parts_db_get_part("PN-1")),
    ("parts_db_create", lambda: scripted.parts_db_create(
        "PN-1", {"ARTICLE_MANUFACTURER": "BOSAQ"})),
    ("parts_db_update", lambda: scripted.parts_db_update(
        "PN-1", "ARTICLE_DESCR1", "x")),
    ("parts_db_list_product_groups", lambda: scripted.parts_db_list_product_groups()),
    ("settings_get_string", lambda: scripted.settings_get_string("USER.X")),
    ("settings_set_string", lambda: scripted.settings_set_string("USER.X", "v")),
    ("settings_get_bool", lambda: scripted.settings_get_bool("USER.X")),
    ("settings_set_bool", lambda: scripted.settings_set_bool("USER.X", True)),
    ("settings_get_int", lambda: scripted.settings_get_int("USER.X")),
    ("settings_set_int", lambda: scripted.settings_set_int("USER.X", 1)),
    ("settings_get_double", lambda: scripted.settings_get_double("USER.X")),
    ("settings_set_double", lambda: scripted.settings_set_double("USER.X", 1.5)),
    ("pathmap_substitute", lambda: scripted.pathmap_substitute("$(MD_DOCUMENTS)")),
    ("pathmap_get_common_paths", lambda: scripted.pathmap_get_common_paths()),
    ("get_system_messages", lambda: scripted.get_system_messages()),
]

_GENERATOR_IDS = [name for name, _ in SCRIPT_GENERATORS]


def _strip_comments(cs: str) -> str:
    """Drop // comments so prose about forbidden syntax isn't flagged as it."""
    return "\n".join(line.split("//")[0] for line in cs.splitlines())


@pytest.mark.parametrize("name,call", SCRIPT_GENERATORS, ids=_GENERATOR_IDS)
def test_generated_csharp_is_csharp5(capture, name, call):
    call()
    code = _strip_comments(capture["script"])

    # ?. / ?[] - null-conditional, C# 6. This was the real cause of every
    # parts_db_* "timeout"; EPLAN reports CS1525 + CS1003 and nothing else.
    assert "?." not in code, f"{name}: null-conditional operator"
    assert "?[" not in code, f"{name}: null-conditional indexer"
    # Interpolated strings, C# 6.
    assert '$"' not in code, f"{name}: interpolated string"
    # Dictionary index initializer, C# 6.
    assert not re.search(r"new Dictionary<[^>]*>\s*\{\s*\[", code), \
        f"{name}: dictionary index initializer"
    # nameof, C# 6.
    assert "nameof(" not in code, f"{name}: nameof"


@pytest.mark.parametrize("name,call", SCRIPT_GENERATORS, ids=_GENERATOR_IDS)
def test_no_ambiguous_single_arg_getproperty(capture, name, call):
    """Every ARTICLE_* member is declared twice on
    MDPartsDatabaseItemPropertyList (parameterless + int-indexed), so a
    one-argument GetProperty(name) throws AmbiguousMatchException for all of
    them. Only the overload that pins Type.EmptyTypes selects the right one."""
    call()
    code = _strip_comments(capture["script"])
    for match in re.finditer(r"GetProperty\(([^;]*?)\)\s*;", code, re.S):
        args = match.group(1)
        assert "Type.EmptyTypes" in args, \
            f"{name}: GetProperty without an index-parameter filter: {args.strip()!r}"


# ---------------------------------------------------------------------------
# Property-name aliases
# ---------------------------------------------------------------------------

# Reads resolve friendly names inside the generated C# (upstream's
# FriendlyToArticle map) and are covered by test_parts_db_offline.py. Only the
# WRITE path resolves them in Python, so that is what is tested here.

def test_friendly_property_alias_resolved_for_update(capture):
    scripted.parts_db_update("PN-1", "Manufacturer", "BOSAQ")
    assert '"ARTICLE_MANUFACTURER"' in capture["script"]
    assert '"Manufacturer"' not in capture["script"]


def test_unknown_property_name_passes_through(capture):
    scripted.parts_db_update("PN-1", "ARTICLE_SOMETHING_ODD", "v")
    assert '"ARTICLE_SOMETHING_ODD"' in capture["script"]


def test_friendly_property_aliases_resolved_for_create(capture):
    scripted.parts_db_create("PN-1", {"Manufacturer": "BOSAQ", "Description1": "d"})
    script = capture["script"]
    assert '"ARTICLE_MANUFACTURER", "ARTICLE_DESCR1"' in script


@pytest.mark.parametrize("call", [
    lambda: scripted.parts_db_create("PN-1", {"ARTICLE_MANUFACTURER": "BOSAQ"}),
    lambda: scripted.parts_db_update("PN-1", "ARTICLE_MANUFACTURER", "BOSAQ"),
], ids=["create", "update"])
def test_write_path_goes_through_mdpropertyvalue(capture, call):
    """Upstream's #33 fixed the READ path only: create and update still did
    SetValue(propList, "a string"). The setter takes an MDPropertyValue, and
    MDPropertyValue has only a default constructor - the conversion that works
    in source is compile-time only - so a bare string is an ArgumentException,
    caught and reported as a failed property. Both paths must construct one."""
    call()
    script = capture["script"]
    assert "new MDPropertyValue()" in script
    assert "pv.Set(value)" in script
    assert "WriteProp(" in script
    # And the lookup must pin the non-indexed overload, or every property
    # throws AmbiguousMatchException before the write is even attempted.
    assert "Type.EmptyTypes" in script


# ---------------------------------------------------------------------------
# A timeout must name the compile error EPLAN logged, not blame EPLAN
# ---------------------------------------------------------------------------

class _FakeManager:
    """Behaves like a live EPLAN whose script failed to compile: the
    ExecuteScript call succeeds, and no result file ever appears."""

    def __init__(self):
        self.script_path = None

    def execute_action(self, command, **kw):
        self.script_path = command.split('/ScriptFile:"')[1].rstrip('"')
        self.kw = kw
        return {"success": True}


@pytest.fixture
def fake_eplan(monkeypatch):
    manager = _FakeManager()
    monkeypatch.setattr(scripted, "_get_connected_manager", lambda: (manager, None))
    return manager


def test_timeout_reports_eplan_compile_errors(fake_eplan, monkeypatch):
    def fake_messages(min_level="Warning", max_messages=100):
        name = os.path.basename(fake_eplan.script_path)
        return {
            "success": True,
            "messages": [
                {"text": "unrelated older message"},
                {"text": "Compile errors in script C:\\gen\\" + name + " :"},
                {"text": "CS1525 (Row:22, Column:40): Invalid expression term"},
                {"text": "The script C:\\gen\\" + name + " cannot be compiled."},
            ],
        }

    monkeypatch.setattr(scripted, "get_system_messages", fake_messages)
    result = scripted._execute_script("// never compiles", timeout=0.2)

    assert result["success"] is False
    assert "did not compile" in result["message"]
    assert "CS1525" in result["message"]
    # The bracketing header/footer are kept for context; older ones are not.
    assert len(result["compile_errors"]) == 3
    assert "unrelated older message" not in result["compile_errors"]


def test_genuine_timeout_says_no_compile_error(fake_eplan, monkeypatch):
    """With the cause unconfirmed, `message` stays the verbatim string
    upstream (#28) preserves for callers matching on it, and the reasoning
    goes in `error`. `message` only stops saying "timeout" once the compiler
    has actually been confirmed as the cause - see the test above."""
    monkeypatch.setattr(
        scripted, "get_system_messages",
        lambda min_level="Warning", max_messages=100: {"success": True, "messages": []},
    )
    result = scripted._execute_script("// compiles but hangs", timeout=0.2)

    assert result["success"] is False
    assert result["message"] == "Timeout waiting for script results"
    assert result["errorType"] == "McpScriptNoResult"
    assert "no compile error" in result["error"]
    assert "compile_errors" not in result


def test_diagnostics_do_not_recurse(fake_eplan, monkeypatch):
    """If reading the message tree itself times out, the outer timeout must
    still return - that diagnostic runs a script through this same function."""
    calls = []

    def reentrant_messages(min_level="Warning", max_messages=100):
        calls.append(1)
        # Exactly what the real get_system_messages does: run another script.
        scripted._execute_script("// diagnostic", timeout=0.1)
        return {"success": True, "messages": []}

    monkeypatch.setattr(scripted, "get_system_messages", reentrant_messages)
    result = scripted._execute_script("// outer", timeout=0.2)

    assert result["success"] is False
    assert len(calls) == 1, "diagnostics recursed"


def test_get_part_uses_generic_product_group(capture):
    """MDPart has no ProductTopGroup member - that is the name of the enum
    TYPE. Reflection over MDPart (2026) lists ProductGroup, ProductSubGroup
    and GenericProductGroup. Using the wrong one is CS1061: another compile
    error, another silent timeout."""
    scripted.parts_db_get_part("PN-1")
    script = capture["script"]
    assert "part.GenericProductGroup" in script
    assert "part.ProductTopGroup" not in script


def test_cs0105_noise_does_not_crowd_out_the_real_error(fake_eplan, monkeypatch):
    """EPLAN pre-imports the namespaces every generated script declares, so
    CS0105 fires on nearly every script and never explains a failure. It
    stays in compile_errors, but must not lead the summary line."""
    def fake_messages(min_level="Warning", max_messages=100):
        name = os.path.basename(fake_eplan.script_path)
        return {
            "success": True,
            "messages": [
                {"text": "Compile errors in script C:\gen\\" + name + " :"},
                {"text": "CS0105 (Row:1, Column:7): The using directive for 'System' appeared previously"},
                {"text": "CS0105 (Row:4, Column:7): The using directive for 'Eplan.EplApi.Scripting' appeared previously"},
                {"text": "CS1525 (Row:12, Column:20): Invalid expression term '.'"},
                {"text": "The script C:\gen\\" + name + " cannot be compiled."},
            ],
        }

    monkeypatch.setattr(scripted, "get_system_messages", fake_messages)
    result = scripted._execute_script("// never compiles", timeout=0.2)

    assert result["message"] == "Script did not compile: CS1525 (Row:12, Column:20): Invalid expression term '.'"
    # Still recorded in full for anyone who wants the raw tree.
    assert sum("CS0105" in e for e in result["compile_errors"]) == 2


def test_summary_falls_back_when_every_line_is_cs0105(fake_eplan, monkeypatch):
    """If CS0105 is somehow all there is, report it rather than an empty
    'Script did not compile: ' with no reason attached."""
    def fake_messages(min_level="Warning", max_messages=100):
        name = os.path.basename(fake_eplan.script_path)
        return {
            "success": True,
            "messages": [
                {"text": "Compile errors in script C:\gen\\" + name + " :"},
                {"text": "CS0105 (Row:1, Column:7): The using directive for 'System' appeared previously"},
                {"text": "The script C:\gen\\" + name + " cannot be compiled."},
            ],
        }

    monkeypatch.setattr(scripted, "get_system_messages", fake_messages)
    result = scripted._execute_script("// never compiles", timeout=0.2)

    assert "CS0105" in result["message"]


def test_script_label_names_the_calling_tool(fake_eplan, monkeypatch):
    monkeypatch.setattr(scripted, "get_system_messages",
                        lambda *a, **k: {"success": True, "messages": []})

    def live_place_symbol():
        return scripted._execute_script("// no result", timeout=0.1)
    live_place_symbol()
    assert fake_eplan.kw["label"] == "live_place_symbol"
