"""
The schematic primitives, asserted on their GENERATED C# with EPLAN closed.

Why assert on the text: EPLAN's script engine emits no compiler output through
the API. A C# error writes no result file and reaches the caller as a bare
timeout, so a mistake in the generated source is invisible from Python at
runtime. Pinning the text is the only cheap way to catch it.

Each test names the failure it prevents. Several of these correspond to bugs
that actually occurred while building this: `Page.Placements` (does not exist),
`Activator.CreateInstance(SymbolVariant, int)` (no such constructor), and
`SetLiveProp` being called before it was defined.
"""

import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(os.path.dirname(HERE), "mcp_server")
for p in (MCP, os.path.join(MCP, "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

from api.actions import schematic as S  # noqa: E402
from api.actions import live  # noqa: E402


# A static C# member definition. The return type may be generic and therefore
# contain spaces and commas ("Dictionary<string, object>"), so it is matched
# loosely up to the helper name.
_DEFINES = r"static\s+[\w<>\[\],.?\s]+?\s+%s\s*\("


@pytest.fixture
def capture(monkeypatch):
    """Capture generated C# and return a canned success, executing nothing."""
    seen = {"scripts": []}

    def fake(script, timeout=30.0):
        seen["scripts"].append(script)
        seen["cs"] = script
        seen["timeout"] = timeout
        return {"success": True, "results": {"success": True}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


def _balanced(cs):
    """Braces balanced, and no line breaks out of a C# string literal."""
    if cs.count("{") != cs.count("}"):
        return False
    stripped = cs.replace("\\\\", "").replace('\\"', "")
    return all(line.count('"') % 2 == 0 for line in stripped.splitlines())


ALL_CALLS = [
    ("symbol_catalog_1", lambda: S.live_symbol_catalog()),
    ("symbol_catalog_2", lambda: S.live_symbol_catalog(library="LIB")),
    ("symbol_catalog_3", lambda: S.live_symbol_catalog(library="LIB", symbol="SL")),
    ("create_page", lambda: S.live_create_page(location="L", counter=1)),
    ("place_symbol", lambda: S.live_place_symbol("P", "LIB", "SL", 10.0, 20.0)),
    ("read_page", lambda: S.live_read_page("P")),
    ("remove_placement", lambda: S.live_remove_placement("P", handle="h")),
    ("remove_page", lambda: S.live_remove_placement("P", remove_page=True)),
]


# ---------------------------------------------------------------------------
# Every generated script must be syntactically plausible
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,call", ALL_CALLS, ids=[c[0] for c in ALL_CALLS])
def test_generated_script_is_well_formed(label, call, capture):
    call()
    cs = capture["cs"]
    assert _balanced(cs), "%s: unbalanced braces or a value escaped its literal" % label
    assert "[Start]" in cs
    assert "{{RESULT_PATH}}" in cs, "a script with no result path can only time out"
    assert "LockingStep" in cs, "project access without a LockingStep throws"
    assert "finally" in cs, "the LockingStep must be disposed on every path"


@pytest.mark.parametrize("label,call", ALL_CALLS, ids=[c[0] for c in ALL_CALLS])
def test_generated_class_names_are_unique(label, call, capture):
    """Two scripts with the same class name in one session collide."""
    call()
    first = re.search(r"public class (\w+)", capture["cs"]).group(1)
    call()
    second = re.search(r"public class (\w+)", capture["cs"]).group(1)
    assert first != second


@pytest.mark.parametrize("label,call", ALL_CALLS, ids=[c[0] for c in ALL_CALLS])
def test_no_generated_script_reads_the_nonexistent_page_placements(label, call, capture):
    """
    THE bug this whole design exists to prevent. Page has no `Placements`;
    reading it returns null, and treating null as "no placements" reported an
    empty page after three objects had been created successfully.
    """
    call()
    assert not re.search(r"\bGetReadable\([^)]*\"Placements\"", capture["cs"])
    assert '"AllPlacements"' in capture["cs"] or "AllPlacements" in capture["cs"]


@pytest.mark.parametrize("label,call", ALL_CALLS, ids=[c[0] for c in ALL_CALLS])
def test_every_helper_used_is_defined(label, call, capture):
    """
    `SetLiveProp` shipped as a call before it was a definition; EPLAN reported
    CS0103 and the tool returned only a timeout. Catch that class here.
    """
    call()
    cs = capture["cs"]
    for helper in ("MemberList", "GetReadable", "RequireMethod", "Call",
                   "TryRead", "MakeValue", "MakePoint", "PtDict", "Handle",
                   "Snap", "SetProp", "SetLiveProp", "GetWritable",
                   "RequireReadable", "MethodByShape"):
        if helper + "(" in cs:
            assert re.search(_DEFINES % re.escape(helper), cs), (
                "%s calls %s but the script does not define it (CS0103)"
                % (label, helper)
            )
    for helper in ("GuardScratch", "FindPage", "PagePlacements", "DumpPlacement",
                   "ReadPage", "ResolveOnPage", "FindPinAt"):
        if helper + "(" in cs:
            assert re.search(_DEFINES % re.escape(helper), cs), (
                "%s calls %s but it is not defined" % (label, helper)
            )


# ---------------------------------------------------------------------------
# The API call forms that were established by live measurement
# ---------------------------------------------------------------------------

def test_place_symbol_binds_the_four_arg_instance_overload(capture):
    """
    Function.Create(Page, SymbolVariant, PointD, PointD) is an INSTANCE method.
    Two of the four candidate designs asked for a STATIC
    Create(SymbolVariant, Page) - which does not exist, so no device was ever
    placed. Bound by parameter-type NAMES, not typeof().
    """
    S.live_place_symbol("P", "LIB", "SL", 10.0, 20.0)
    cs = capture["cs"]
    assert 'RequireMethod(funcType, "Create"' in cs
    assert '"Page", "SymbolVariant", "PointD", "PointD"' in cs
    assert ", false)" in cs.split('RequireMethod(funcType, "Create"')[1][:200], (
        "the four-arg Create must be bound as an INSTANCE method"
    )


def test_place_symbol_builds_the_variant_with_the_two_arg_constructor(capture):
    """
    `Activator.CreateInstance(svType, new object[]{ 0 })` throws
    MissingMethodException - SymbolVariant has only () and (Symbol, int).
    """
    S.live_place_symbol("P", "LIB", "SL", 10.0, 20.0)
    cs = capture["cs"]
    assert "varType.GetConstructor(new Type[] { symType, typeof(int) })" in cs
    assert "Activator.CreateInstance(varType, new object[] { VARNR" not in cs


def test_place_symbol_builds_a_fresh_symbol_per_call(capture):
    """A SymbolVariant cannot be reused: the second Create throws
    ObjectAlreadyCreatedException."""
    S.live_place_symbol("P", "LIB", "SL", 10.0, 20.0)
    cs = capture["cs"]
    assert "symCtor.Invoke" in cs and "varCtor.Invoke" in cs


def test_no_script_constructs_pointd_by_name(capture):
    """
    The point type must come from the member it is handed to. Resolving
    Eplan.EplApi.Base.PointD directly silently matches nothing if the script
    engine compiles against a different Base assembly than the object model.
    """
    for _, call in ALL_CALLS:
        call()
        # Strip C# comments: the helper block DOCUMENTS the forbidden forms, and
        # a rule written down is not a rule violated.
        cs = re.sub(r"//[^\n]*", "", capture["cs"])
        assert 'FindType("Eplan.EplApi.Base.PointD")' not in cs
        assert "new PointD(" not in cs
    S.live_place_symbol("P", "LIB", "SL", 1.0, 2.0)
    assert "create.GetParameters()[2].ParameterType" in capture["cs"]


def test_create_page_binds_the_only_three_arg_overload(capture):
    S.live_create_page(location="L", counter=1)
    cs = capture["cs"]
    assert 'RequireMethod(pageType, "Create"' in cs
    assert "GetNestedType(\"DocumentType\")" in cs


def test_create_page_reads_the_name_back_rather_than_predicting_it(capture):
    """Measured live: a plant designation set at creation did not appear in the
    page name. Predicting the name gives a value later calls cannot address."""
    S.live_create_page(plant="P1", location="L1", counter=5)
    cs = capture["cs"]
    assert 'string realName = PropText(page, "Name");' in cs
    assert 'results["page"] = realName;' in cs


def test_create_page_uses_op_implicit_for_property_values(capture):
    """PropertyValue has no public constructor."""
    S.live_create_page(location="L", counter=1)
    cs = capture["cs"]
    assert 'SetProp(ppl, "PAGE_COUNTER"' in cs
    assert "op_Implicit" in cs


# ---------------------------------------------------------------------------
# The scratch guard
# ---------------------------------------------------------------------------

WRITERS = [
    ("create_page", lambda **kw: S.live_create_page(location="L", counter=1, **kw)),
    ("place_symbol", lambda **kw: S.live_place_symbol("P", "LIB", "SL", 1.0, 2.0, **kw)),
    ("remove", lambda **kw: S.live_remove_placement("P", handle="h", **kw)),
    ("remove_page", lambda **kw: S.live_remove_placement("P", remove_page=True, **kw)),
]


@pytest.mark.parametrize("label,call", WRITERS, ids=[w[0] for w in WRITERS])
def test_every_writer_guards_by_default(label, call, capture):
    call()
    cs = capture["cs"]
    assert "GuardScratch(project, false," in cs, (
        "%s does not run the scratch guard, or does not default it to refuse"
        % label
    )


@pytest.mark.parametrize("label,call", WRITERS, ids=[w[0] for w in WRITERS])
def test_the_override_is_honoured(label, call, capture):
    call(allow_real_project=True)
    assert "GuardScratch(project, true," in capture["cs"]


@pytest.mark.parametrize("label,call", WRITERS, ids=[w[0] for w in WRITERS])
def test_the_guard_runs_before_anything_is_created(label, call, capture):
    """A guard that fires after a Create has already let the write happen."""
    call()
    cs = capture["cs"]
    guard = cs.index("GuardScratch(")
    for marker in ("Activator.CreateInstance(pageType", "Activator.CreateInstance(funcType"):
        if marker in cs:
            assert guard < cs.index(marker), "%s creates before it guards" % label


def test_readers_do_not_guard(capture):
    """
    A read cannot damage anything, so it must work against a real project.

    Checks for the CALL, not the definition: the helper block is spliced into
    every script in this module, so GuardScratch is always *defined*.
    """
    S.live_read_page("P")
    assert "GuardScratch(project," not in capture["cs"]
    S.live_symbol_catalog()
    assert "GuardScratch(project," not in capture["cs"]
    S.live_symbol_catalog(library="LIB")
    assert "GuardScratch(project," not in capture["cs"]


# ---------------------------------------------------------------------------
# Argument validation happens BEFORE a script is built
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_x", ["1; Evil()", None, "abc", float("inf")])
def test_a_bad_coordinate_never_reaches_a_script(bad_x, capture):
    result = S.live_place_symbol("P", "LIB", "SL", bad_x, 20.0)
    assert result["success"] is False
    assert not capture["scripts"], "a rejected value still generated a script"


def test_a_result_path_token_in_an_argument_is_refused(capture):
    result = S.live_read_page("page{{RESULT_PATH}}")
    assert result["success"] is False
    assert "RESULT_PATH" in result["error"]
    assert not capture["scripts"]


def test_symbol_without_library_is_refused(capture):
    result = S.live_symbol_catalog(symbol="SL")
    assert result["success"] is False
    assert "library" in result["error"]
    assert not capture["scripts"]


def test_create_page_requires_a_name_part(capture):
    result = S.live_create_page(counter=1)
    assert result["success"] is False
    assert not capture["scripts"]


def test_remove_requires_exactly_one_mode(capture):
    both = S.live_remove_placement("P", handle="h", remove_page=True)
    assert both["success"] is False
    neither = S.live_remove_placement("P")
    assert neither["success"] is False
    assert not capture["scripts"]


def test_connect_refuses_a_pin_to_itself(capture):
    result = S.live_connect_pins("P", "h1", 0, "h1", 0)
    assert result["success"] is False
    assert not capture["scripts"]


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------

def test_a_script_that_reported_failure_is_not_reported_as_success(monkeypatch):
    """
    _execute_script returns outer success:True whenever the result FILE was
    written - including when the script caught an exception and wrote
    success:false into it. Returning that outer True is how a reflective failure
    comes back looking like a success with the real error one level down.
    """
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True,
        "results": {"success": False, "error": "No readable property 'Nope'."},
    })
    result = S.live_read_page("P")
    assert result["success"] is False
    assert "Nope" in result["error"]


def test_a_timeout_explains_that_it_is_probably_a_compile_error(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": False, "message": "Timeout waiting for script results",
    })
    result = S.live_read_page("P")
    assert result["success"] is False
    assert "compile" in result["hint"].lower()
    assert "eplan_get_system_messages" in result["hint"]


def test_writes_offer_an_undo_handle(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True,
        "results": {"success": True, "page": "+L/1", "handle": "h9"},
    })
    result = S.live_place_symbol("P", "LIB", "SL", 1.0, 2.0)
    assert result["undo"]["tool"] == "eplan_live_remove_placement"
    assert result["undo"]["handle"] == "h9"


def test_create_page_offers_page_removal_as_its_undo(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True, "results": {"success": True, "page": "+L/1"},
    })
    result = S.live_create_page(location="L", counter=1)
    assert result["undo"]["remove_page"] is True


def test_pins_are_annotated_with_their_frame(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True,
        "results": {
            "success": True,
            "page": "+L/1",
            "placements": [{
                "clrType": "Function",
                "location": {"x": 60.0, "y": 200.0},
                "boundingBox": [{"x": 58.0, "y": 192.0}, {"x": 63.0, "y": 208.0}],
                "pins": [{"index": 0, "raw": {"x": 0.0, "y": 6.0}}],
            }],
        },
    })
    result = S.live_read_page("P")
    pin = result["placements"][0]["pins"][0]
    assert pin["frame"] == "relative"
    assert pin["point"] == {"x": 60.0, "y": 206.0}


def test_an_unresolvable_pin_frame_is_warned_about(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True,
        "results": {
            "success": True,
            "placements": [{
                "clrType": "Function",
                "location": {"x": 60.0, "y": 200.0},
                "boundingBox": [{"x": 58.0, "y": 192.0}, {"x": 63.0, "y": 208.0}],
                "pins": [{"index": 0, "raw": {"x": 999.0, "y": 999.0}}],
            }],
        },
    })
    result = S.live_read_page("P")
    assert result["placements"][0]["pins"][0]["point"] is None
    assert "pinFrameWarning" in result
    assert "(0,0)" in result["pinFrameWarning"]


# ---------------------------------------------------------------------------
# The live.py helper splice this module depends on
# ---------------------------------------------------------------------------

def test_extra_helpers_land_before_the_start_method():
    cs = live._script("Demo", "            results[\"x\"] = 1;\n",
                      extra_helpers="    static int Demo2() { return 1; }")
    assert cs.index("static int Demo2()") < cs.index("[Start]")


def test_script_without_extra_helpers_is_unchanged():
    """live_query_functions and friends must be untouched by the new hook."""
    a = live._script("Demo", "            results[\"x\"] = 1;\n")
    b = live._script("Demo", "            results[\"x\"] = 1;\n", extra_helpers="")
    assert a == b


# ---------------------------------------------------------------------------
# The tools must actually be PUBLISHED, not merely importable
# ---------------------------------------------------------------------------

SCHEMATIC_TOOL_NAMES = (
    "eplan_live_symbol_catalog",
    "eplan_live_create_page",
    "eplan_live_place_symbol",
    "eplan_live_connect_pins",
    "eplan_live_read_page",
    "eplan_live_remove_placement",
)


@pytest.fixture(scope="module")
def published_full():
    """Tool names build_app publishes in the default 'full' mode."""
    import asyncio
    import server
    app, _registry, _ = server.build_app(mode="full")
    return {t.name for t in asyncio.run(app.list_tools())}


@pytest.mark.parametrize("name", SCHEMATIC_TOOL_NAMES)
def test_tool_is_published_in_full_mode(name, published_full):
    """
    Exporting from api.actions is not enough - a function that server.py never
    registers is invisible to a client, and nothing else in the suite would
    notice.
    """
    assert name in published_full


@pytest.mark.parametrize("name", SCHEMATIC_TOOL_NAMES)
def test_tool_is_reachable_in_discovery_mode(name):
    """
    Discovery mode publishes a small core and hides the rest behind meta-tools.
    Hidden must still mean REACHABLE: a tool the registry cannot resolve is
    simply gone for any session running in that mode.
    """
    import server
    _app, registry, _ = server.build_app(mode="discovery")
    short = name[len("eplan_"):]
    hit = registry.describe([short])
    assert hit, "%s is not in the discovery registry" % name


def test_published_docstrings_warn_that_writes_touch_a_real_project(published_full):
    """
    server.py passes __doc__ through unchanged, so these docstrings are the
    model's only warning that a write is scoped to scratch by default.
    """
    for func in (S.live_create_page, S.live_place_symbol,
                 S.live_connect_pins, S.live_remove_placement):
        doc = func.__doc__ or ""
        assert "WRITES" in doc, "%s does not say it writes" % func.__name__
        assert "scratch" in doc.lower(), (
            "%s does not mention the scratch-only default" % func.__name__
        )
