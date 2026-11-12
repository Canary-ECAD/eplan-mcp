"""
live_read_connections, and the connection-line geometry bug it exposed.

Two things are pinned here:

  1. The reader NEVER writes. A "read" tool that quietly mutates is exactly the
     surprise this layer exists to avoid, and generating connections modifies
     the project.

  2. A connection line is anchored, then drawn RELATIVE to that anchor.
     `SetGraphics` does not take absolute page coordinates - measured against
     real human-drawn lines, whose Location is the absolute anchor and whose
     graphics and connection points are relative to it. Passing absolute
     coordinates put one end of every wire at the PAGE ORIGIN: a line that
     visibly exists, reports success, and connects nothing.

Runs with EPLAN closed.
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


@pytest.fixture
def capture(monkeypatch):
    seen = {"scripts": []}

    def fake(script, timeout=30.0):
        seen["scripts"].append(script)
        seen["cs"] = script
        return {"success": True, "results": {"success": True, "total": 1,
                                             "matched": 1, "connections": []}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


# ---------------------------------------------------------------------------
# The reader must never write
# ---------------------------------------------------------------------------

def test_read_connections_carries_no_write_guard(capture):
    """A read needs no scratch guard, because it cannot damage anything."""
    S.live_read_connections()
    assert "GuardScratch(project," not in capture["cs"]


def test_read_connections_generates_no_mutating_call(capture):
    S.live_read_connections()
    run_body = capture["cs"].split("[Start]")[1]
    for mutator in ("SetGraphics", ".Remove(", "Create(page", "SetValue("):
        assert mutator not in run_body, (
            "the connection reader emits %s - a read tool must not write" % mutator
        )


def test_read_connections_does_not_generate_connections(capture):
    """
    Generating connections MUTATES the project. The tool names it as a next
    step rather than running it.

    Looks for an EXECUTED action, not for the word: the script's own error text
    legitimately says "having been generated", and matching prose would flag
    that - the same false-positive trap that bit the earlier PointD check.
    """
    S.live_read_connections()
    run_body = capture["cs"].split("[Start]")[1]
    for call in ("ExecuteAction", "ActionManager", "GenerateConnections",
                 "XEsGenerate"):
        assert call not in run_body, (
            "the connection reader invokes %s - it must read, not generate" % call
        )


# ---------------------------------------------------------------------------
# Shape of the read
# ---------------------------------------------------------------------------

def test_read_connections_binds_getconnections_by_shape(capture):
    S.live_read_connections()
    cs = capture["cs"]
    assert 'RequireMethod(finderType, "GetConnections"' in cs
    assert "ConnectionsFilter" in cs


def test_a_null_result_is_an_error_not_an_empty_project(capture):
    """
    Reporting "no connections" for a null return would be indistinguishable
    from connections simply not having been generated.
    """
    S.live_read_connections()
    assert "refusing to report" in capture["cs"]


def test_the_true_total_is_reported_alongside_the_filtered_count(capture):
    S.live_read_connections(page="+P/1")
    cs = capture["cs"]
    assert 'results["total"] = total;' in cs
    assert 'results["matched"] = matched;' in cs


def test_a_page_filter_is_applied_in_the_script(capture):
    S.live_read_connections(page="+P/1")
    assert 'cpgName != "+P/1"' in capture["cs"]


def test_no_page_filter_when_none_is_given(capture):
    S.live_read_connections()
    assert "cpgName" not in capture["cs"]


def test_a_hostile_page_name_survives(capture):
    """PAGENAME/LIMIT are token names; a page called one must not corrupt."""
    S.live_read_connections(page="+LIMIT/1")
    assert '"+LIMIT/1"' in capture["cs"]


def test_a_result_path_token_in_the_page_is_refused(capture):
    out = S.live_read_connections(page="{{RESULT_PATH}}")
    assert out["success"] is False
    assert not capture["scripts"]


@pytest.mark.parametrize("bad", ["x", -1, 0, 99999])
def test_limit_is_validated(bad, capture):
    out = S.live_read_connections(limit=bad)
    assert out["success"] is False
    assert not capture["scripts"]


# ---------------------------------------------------------------------------
# Staleness: an empty list must not read as "nothing is wired"
# ---------------------------------------------------------------------------

def _result(monkeypatch, payload):
    monkeypatch.setattr(S, "_execute_script",
                        lambda script, timeout=30.0: {"success": True,
                                                      "results": payload})


def test_zero_connections_is_reported_as_probably_ungenerated(monkeypatch):
    _result(monkeypatch, {"success": True, "total": 0, "matched": 0,
                          "connections": []})
    out = S.live_read_connections()
    assert out["stale"] is True
    assert "generate_connections" in out["nextStep"]


def test_a_page_with_none_but_a_project_with_some_is_not_stale(monkeypatch):
    """The project HAS connections, so generation has clearly run."""
    _result(monkeypatch, {"success": True, "total": 3085, "matched": 0,
                          "connections": []})
    out = S.live_read_connections(page="+P/1")
    assert out["stale"] is False
    assert "3085" in out["note"]


def test_a_populated_read_carries_no_staleness_warning(monkeypatch):
    _result(monkeypatch, {"success": True, "total": 12, "matched": 12,
                          "connections": [{"handle": "h"}]})
    out = S.live_read_connections()
    assert "stale" not in out and "nextStep" not in out


# ---------------------------------------------------------------------------
# The connection-line geometry fix
# ---------------------------------------------------------------------------

def _connect_script(monkeypatch):
    """Drive live_connect_pins past its pin probe and capture the draw script."""
    scripts = []

    probe = {
        "success": True,
        "page": "+P/1",
        "from": {"placement": {
            "location": {"x": 60.0, "y": 200.0},
            "boundingBox": [{"x": 58.0, "y": 192.0}, {"x": 63.0, "y": 208.0}],
            "pins": [{"index": 0, "raw": {"x": 0.0, "y": 6.0}}]}},
        "to": {"placement": {
            "location": {"x": 140.0, "y": 200.0},
            "boundingBox": [{"x": 138.0, "y": 192.0}, {"x": 143.0, "y": 208.0}],
            "pins": [{"index": 0, "raw": {"x": 0.0, "y": 6.0}}]}},
    }

    def fake(script, timeout=30.0):
        scripts.append(script)
        if len(scripts) == 1:          # the pin probe
            return {"success": True, "results": probe}
        return {"success": True, "results": {"success": True, "lineDrawn": True}}

    monkeypatch.setattr(S, "_execute_script", fake)
    S.live_connect_pins("+P/1", "hA", 0, "hB", 0)
    assert len(scripts) == 2, "the draw script never ran"
    return scripts[1]


def test_the_line_is_anchored_before_it_is_drawn(monkeypatch):
    """
    Without an anchor, SetGraphics places the segment relative to the page
    ORIGIN - which put one end of every wire at (0,0).
    """
    cs = _connect_script(monkeypatch)
    assert 'GetWritable(dclType, "Location")' in cs
    anchor = cs.index("locProp.SetValue(dcl")
    draw = cs.index("Call(setG, dcl")
    assert anchor < draw, "the line must be anchored BEFORE SetGraphics"


def test_setgraphics_receives_relative_coordinates(monkeypatch):
    cs = _connect_script(monkeypatch)
    assert "MakePoint(ptType, 0.0, 0.0)" in cs, (
        "the segment must start at the anchor, i.e. relative (0,0)"
    )
    assert re.search(r"MakePoint\(ptType,\s*[\d.+-]+\s*-\s*[\d.+-]+", cs), (
        "the far end must be a DIFFERENCE, not an absolute coordinate"
    )


def test_a_missing_writable_location_is_a_hard_error(monkeypatch):
    """Silently drawing from the origin is the failure being prevented."""
    cs = _connect_script(monkeypatch)
    assert "has no writable Location" in cs
    assert "page origin" in cs


def test_the_anchor_is_reported_back(monkeypatch):
    cs = _connect_script(monkeypatch)
    assert 'results["anchor"]' in cs

# ---------------------------------------------------------------------------
# Jumper properties: CONNECTION_TYPE on connections, #20808 etc on terminals
#
# These exist because EPLAN's terminal strip editor shows jumpers that were not
# reachable through this server at all. Two measured facts drive the shape:
#
#   1. kindOfWire CANNOT identify a jumper. Connection.Enums.KindOfWire has
#      exactly five members - IndividualConnection, Cable, Conduit,
#      PhaseBusbar, Line. It is the cable axis. CONNECTION_TYPE #31075 is the
#      one carrying 5 = "Jumper (automatic)".
#   2. An integer property read as TEXT loses its zero. CONNECTION_TYPE 0 is
#      "Placed" and FUNC_TERMINAL_JUMPERBAR 0 is "Automatic" - both real
#      answers, and the second is the answer we most expect on these projects.
#      The existing string loop drops anything whose text is empty, so these
#      must not go through it.
# ---------------------------------------------------------------------------

def test_connection_type_is_read(capture):
    """The jumper discriminator has to actually be in the script."""
    S.live_read_connections()
    assert "CONNECTION_TYPE" in capture["cs"]


def test_connection_type_is_read_as_a_number_not_text(capture):
    """
    A zero is a real answer here. Reading these through SafeText would put them
    behind the `s.Length > 0` guard, which cannot tell "the value is 0" from
    "the property is absent".
    """
    S.live_read_connections()
    cs = capture["cs"]
    assert 'ReadIntProp(props, "CONNECTION_TYPE"' in cs
    assert "Convert.ToInt64" in cs


def test_connection_type_five_is_decoded(capture):
    """A caller should not need the enum table to recognise a jumper."""
    S.live_read_connections()
    assert '"Jumper (automatic)"' in capture["cs"]


def test_saddle_jumper_slot_is_read(capture):
    S.live_read_connections()
    assert "CONNECTION_SADDLEJUMPER_SLOT" in capture["cs"]


def test_absence_is_recorded_rather_than_omitted(capture):
    """
    "No jumper properties on this connection" and "this build cannot read
    them" are different answers, and the whole question is which one is true.
    """
    S.live_read_connections()
    assert 'd["absentMembers"] = absent' in capture["cs"]


# ---------------------------------------------------------------------------
# Scoping a read to one terminal strip
# ---------------------------------------------------------------------------

def test_a_device_filter_is_applied_in_the_script(capture):
    S.live_read_connections(device="+P01-XT")
    cs = capture["cs"]
    assert 'ConnTouchesDevice(conn, "+P01-XT")' in cs


def test_no_device_filter_when_none_is_given(capture):
    S.live_read_connections()
    assert "ConnTouchesDevice(conn," not in capture["cs"].split("[Start]")[1]


def test_the_device_filter_runs_before_the_dump(capture):
    """
    A real project has thousands of connections. Filtering after DumpConnection
    would serialise every one of them to throw the result away.
    """
    S.live_read_connections(device="+P01-XT")
    run_body = capture["cs"].split("[Start]")[1]
    assert run_body.index("ConnTouchesDevice(conn,") < run_body.index("DumpConnection(conn)")


def test_a_hostile_device_name_survives(capture):
    S.live_read_connections(device="+DEVICENAME-1")
    assert '"+DEVICENAME-1"' in capture["cs"]


def test_a_result_path_token_in_the_device_is_refused(capture):
    out = S.live_read_connections(device="{{RESULT_PATH}}")
    assert out["success"] is False
    assert not capture["scripts"]


# ---------------------------------------------------------------------------
# live_read_terminals
# ---------------------------------------------------------------------------

def test_read_terminals_carries_no_write_guard(capture):
    S.live_read_terminals()
    assert "GuardScratch(project," not in capture["cs"]


def test_read_terminals_never_writes(capture):
    """
    Writing a jumper crest would flip a strip from Automatic to Manual and
    change how EPLAN's own terminal diagrams render it. This reads only.
    """
    S.live_read_terminals()
    run_body = capture["cs"].split("[Start]")[1]
    for mutator in ("SetValue(", "SetProp(", "SetLiveProp(", ".Remove(",
                    "Create(page", "ExecuteAction", "ActionManager"):
        assert mutator not in run_body, (
            "the terminal reader emits %s - a read tool must not write" % mutator
        )


def test_read_terminals_binds_getterminals_by_shape(capture):
    S.live_read_terminals()
    cs = capture["cs"]
    assert 'RequireMethod(finderType, "GetTerminals"' in cs
    assert "FunctionsFilter" in cs


def test_a_null_terminal_result_is_an_error_not_an_empty_project(capture):
    S.live_read_terminals()
    assert "refusing to report" in capture["cs"]


def test_read_terminals_reads_every_jumper_property(capture):
    """
    The point of the tool. FUNC_TERMINAL_JUMPERBAR and the crests live on the
    TERMINAL, not the connection, so no amount of connection reading finds
    them - if one of these drops out of the script the tool is silently back to
    answering nothing.
    """
    S.live_read_terminals()
    cs = capture["cs"]
    for prop in ("FUNC_TERMINAL_JUMPERBAR",
                 "FUNC_TERMINAL_JUMPER_EXTERN",
                 "FUNC_TERMINAL_JUMPER_INTERN",
                 "FUNC_TERMINAL_SWITCHABLE_JUMPER_EXTERN",
                 "FUNC_TERMINAL_SWITCHABLE_JUMPER_INTERN",
                 "FUNC_LOGDEF_SADDLEJUMPERCOUNT"):
        assert prop in cs, "%s is not read" % prop


def test_read_terminals_reads_strip_position(capture):
    """
    Strip order - not page position - is what decides which terminals a jumper
    chain taps and which it merely crosses.
    """
    S.live_read_terminals()
    cs = capture["cs"]
    assert "FUNC_TERMINALSORTCODE" in cs
    assert "FUNC_TERMINALDEVICEPOSITION" in cs
    assert 'ReadIntProp(props, "FUNC_TERMINALLEVEL"' in cs


def test_the_jumper_crests_use_the_indexed_reader(capture):
    """
    FUNC_TERMINAL_JUMPER_EXTERN is indexed 1..1. TryRead calls
    GetValue(o, null), which throws TargetParameterCountException on an indexed
    getter - so going through TryRead would report the crest as "threw" instead
    of reading it.
    """
    S.live_read_terminals()
    cs = capture["cs"]
    assert 'ReadIndexedProp(props, "FUNC_TERMINAL_JUMPER_EXTERN", 1' in cs
    assert 'ReadIndexedProp(props, "FUNC_TERMINAL_JUMPER_INTERN", 1' in cs
    assert 'GetPropInfoIdx(props.GetType(), name)' in cs


def test_jumper_bar_zero_is_decoded_as_automatic(capture):
    """
    0 = Automatic is the value these projects are expected to carry, so it must
    read as an answer rather than as an absence.
    """
    S.live_read_terminals()
    cs = capture["cs"]
    assert 'ReadIntProp(props, "FUNC_TERMINAL_JUMPERBAR"' in cs
    assert '"Automatic"' in cs
    assert '"Automatic, start of jumper"' in cs


def test_switchable_jumper_closed_is_decoded(capture):
    """
    "Closed" CREATES a connection to the next terminal, so it is a second
    mechanism producing jumper connections and has to be visible.
    """
    S.live_read_terminals()
    assert '"Closed"' in capture["cs"]


def test_read_terminals_reads_the_page_space_anchor(capture):
    """The insertion point is what a jumper dot gets offset from."""
    S.live_read_terminals()
    assert 'd["location"] = PtDict(loc)' in capture["cs"]


def test_read_terminals_device_filter_is_applied(capture):
    S.live_read_terminals(device="+P01-XT")
    assert '"+P01-XT"' in capture["cs"]


def test_no_terminal_device_filter_when_none_is_given(capture):
    S.live_read_terminals()
    run_body = capture["cs"].split("[Start]")[1]
    assert "DEVICENAME" not in run_body


def test_read_terminals_page_filter_is_applied(capture):
    S.live_read_terminals(page="+P/1")
    assert 'tpgName != "+P/1"' in capture["cs"]


def test_a_result_path_token_in_the_terminal_device_is_refused(capture):
    out = S.live_read_terminals(device="{{RESULT_PATH}}")
    assert out["success"] is False
    assert not capture["scripts"]


@pytest.mark.parametrize("bad", ["x", -1, 0, 99999])
def test_terminal_limit_is_validated(bad, capture):
    out = S.live_read_terminals(limit=bad)
    assert out["success"] is False
    assert not capture["scripts"]


def test_read_terminals_is_registered_as_a_tool():
    """
    server.py registers whatever is in actions.__all__, so a function missing
    from it exists but is unreachable over MCP.
    """
    from api import actions
    assert "live_read_terminals" in actions.__all__
    assert hasattr(actions, "live_read_terminals")

# ---------------------------------------------------------------------------
# The PropertyValue conversion trap, measured live 2026-09-09
#
# Convert.ToInt64 on an EPLAN PropertyValue throws
#   InvalidCastException: Unable to cast object of type
#   'Eplan.EplApi.DataModel.PropertyValue' to type 'System.IConvertible'
# because PropertyValue converts through implicit operators, which reflection
# does not apply. The first live run of this code read CONNECTION_TYPE on 3082
# real connections and FUNC_TERMINALLEVEL / FUNC_TERMINAL_JUMPERBAR on 32 real
# terminals, and EVERY ONE came back as that exception - the reader looked
# correct offline and answered nothing at all in the field.
#
# The fix is to parse the text. These tests pin the fallback, not just the
# presence of a Convert call, because a Convert-only reader passes the earlier
# "reads as a number" test while being completely broken.
# ---------------------------------------------------------------------------

def test_int_read_falls_back_to_parsing_the_text(capture):
    S.live_read_terminals()
    cs = capture["cs"]
    assert "long.TryParse" in cs, (
        "ReadIntProp relies on Convert.ToInt64 alone; a PropertyValue is not "
        "IConvertible, so every integer property would read as an exception"
    )
    assert "v.ToString()" in cs


def test_int_read_parses_culture_invariantly(capture):
    S.live_read_terminals()
    cs = capture["cs"]
    assert "System.Globalization.CultureInfo.InvariantCulture" in cs
    # System.Globalization is NOT in the shared script header, so the types must
    # be fully qualified or the generated C# will not compile.
    assert "using System.Globalization;" not in cs


def test_an_empty_property_reads_as_null_not_as_a_failure(capture):
    """
    Measured: FUNC_TERMINAL_SWITCHABLE_JUMPER_EXTERN #20292 THROWS
    EmptyPropertyException on read when no switching jumper is set - it does not
    return 0. "Not set" is a real answer and must not surface as an error.
    """
    S.live_read_terminals()
    cs = capture["cs"]
    assert "empty or threw" in cs
    assert 'into[key] = null' in cs


def test_a_non_numeric_value_is_reported_not_discarded(capture):
    """Dropping it would be indistinguishable from the property being absent."""
    S.live_read_terminals()
    assert "not an integer" in capture["cs"]
