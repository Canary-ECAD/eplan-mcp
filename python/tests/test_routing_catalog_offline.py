"""
live_routing_catalog: discovering connection symbols instead of assuming them.

Why discovery rather than a constant: a project carries SEVERAL symbols for the
same job. Measured on a production installation, `SPECIAL_en_US` holds 24
connection symbols including TWO different `TNodeUp` symbols - `TLRO` and
`TLRO_1` - which differ ONLY in pin order:

    TLRO    v2: Right+Left+Up
    TLRO_1  v2: Right+Up+Left

and six interruption-point symbols, some two-pin and some one-pin directional.
So "the corner symbol" is not a constant, and pin ORDER is load-bearing
information that must not be sorted away.

Runs with EPLAN closed.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(os.path.dirname(HERE), "mcp_server")
for p in (MCP, os.path.join(MCP, "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

from api.actions import schematic as S  # noqa: E402


def want_types(cs):
    """
    The types this call actually searches for.

    Scoped deliberately to the `wantTypes` line. The shared C# helpers carry a
    ROUTING_TYPES array naming EVERY connection type, so grepping the whole
    script for a type name always succeeds and proves nothing - the same
    false-positive trap that has bitten these checks before.
    """
    line = [l for l in cs.splitlines() if "List<string> wantTypes" in l]
    assert len(line) == 1, "expected exactly one wantTypes line, got %d" % len(line)
    return line[0]


# Shaped exactly like a real read, including the same-type duplicates.
LIVE = {
    "success": True,
    "libraries": ["SPECIAL_en_US", "NFPA_symbol_en_US"],
    "symbols": [
        {"library": "SPECIAL_en_US", "symbol": "CO", "type": "Routing",
         "variants": [
             {"variantNr": 0, "directions": ["Right", "Down"]},
             {"variantNr": 1, "directions": ["Right", "Up"]},
             {"variantNr": 2, "directions": ["Left", "Up"]},
             {"variantNr": 3, "directions": ["Left", "Down"]}]},
        {"library": "SPECIAL_en_US", "symbol": "TLRO", "type": "TNodeUp",
         "variants": [
             {"variantNr": 0, "directions": ["Up", "Left", "Right"]},
             {"variantNr": 2, "directions": ["Right", "Left", "Up"]}]},
        {"library": "SPECIAL_en_US", "symbol": "TLRO_1", "type": "TNodeUp",
         "variants": [
             {"variantNr": 0, "directions": ["Up", "Left", "Right"]},
             {"variantNr": 2, "directions": ["Right", "Up", "Left"]}]},
        {"library": "SPECIAL_en_US", "symbol": "CDPNG2",
         "type": "ConnectionDefinition", "variants": []},
    ],
}


@pytest.fixture
def live(monkeypatch):
    seen = {}

    def fake(script, timeout=30.0):
        seen["cs"] = script
        return {"success": True, "results": dict(LIVE)}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


@pytest.fixture
def capture(monkeypatch):
    """Capture the script without pretending to return symbols."""
    seen = {"scripts": []}

    def fake(script, timeout=30.0):
        seen["scripts"].append(script)
        seen["cs"] = script
        return {"success": True, "results": {"success": True, "symbols": [],
                                             "libraries": []}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


# ---------------------------------------------------------------------------
# Discovery, not assumption
# ---------------------------------------------------------------------------

def test_it_searches_every_library_by_default(capture):
    S.live_routing_catalog()
    cs = capture["cs"]
    assert 'RequireReadable(project.GetType(), "SymbolLibraries")' in cs
    assert "foreach (string ln in libNames)" in cs


def test_it_selects_by_symbol_TYPE_not_by_name(capture):
    """`CO` is this project's corner. Another project's may not be."""
    S.live_routing_catalog()
    cs = capture["cs"]
    line = want_types(cs)
    assert '"Routing"' in line and '"TNodeUp"' in line
    assert 'PropText(s, "Type")' in cs
    # The one thing it must NOT do.
    assert '"CO"' not in cs


def test_every_routing_type_is_searched_by_default(capture):
    S.live_routing_catalog()
    line = want_types(capture["cs"])
    for t in ("Routing", "DynamicRouting", "RoutingCross", "RoutingBridge",
              "TNodeUp", "TNodeDown", "TNodeLeft", "TNodeRight",
              "InterruptionPoint", "ConnectionDefinition"):
        assert '"%s"' % t in line, "%s is not searched for" % t


def test_a_single_type_narrows_the_search(capture):
    S.live_routing_catalog(symbol_type="Routing")
    line = want_types(capture["cs"])
    assert '"Routing"' in line
    assert '"TNodeUp"' not in line


def test_an_unknown_symbol_type_is_refused_with_the_real_list(capture):
    out = S.live_routing_catalog(symbol_type="Corner")
    assert out["success"] is False
    assert "TNodeUp" in out["error"]
    assert not capture["scripts"]


def test_a_library_filter_is_applied(capture):
    S.live_routing_catalog(library="SPECIAL_en_US")
    assert 'ln != "SPECIAL_en_US"' in capture["cs"]


def test_a_library_that_cannot_be_opened_is_skipped_not_fatal(capture):
    """A project can list a library it cannot open; that must not kill the walk."""
    S.live_routing_catalog()
    assert "catch { continue; }" in capture["cs"]


# ---------------------------------------------------------------------------
# Direction matching
# ---------------------------------------------------------------------------

def test_a_corner_is_found_by_the_directions_it_turns(live):
    out = S.live_routing_catalog(directions=["Right", "Down"])
    assert out["matched"] == 1
    s = out["symbols"][0]
    assert s["symbol"] == "CO" and s["matchingVariants"] == [0]


def test_direction_order_does_not_affect_matching(live):
    a = S.live_routing_catalog(directions=["Right", "Down"])
    b = S.live_routing_catalog(directions=["Down", "Right"])
    assert a["symbols"][0]["matchingVariants"] == b["symbols"][0]["matchingVariants"]


def test_directions_are_case_normalised(live):
    out = S.live_routing_catalog(directions=["right", "DOWN"])
    assert out["matched"] == 1


def test_an_invalid_direction_is_refused(capture):
    out = S.live_routing_catalog(directions=["Right", "Sideways"])
    assert out["success"] is False
    assert "Up, Down, Left, Right" in out["error"]
    assert not capture["scripts"]


def test_two_symbols_of_the_same_type_are_BOTH_returned(live):
    """
    TLRO and TLRO_1 are both TNodeUp. Choosing one is a house convention, not
    something this can decide, so both come back and the result says so.
    """
    out = S.live_routing_catalog(directions=["Up", "Left", "Right"])
    assert out["matched"] == 2
    assert {s["symbol"] for s in out["symbols"]} == {"TLRO", "TLRO_1"}
    assert out["ambiguous"] is True
    assert "house convention" in out["note"]


def test_pin_order_is_preserved_not_sorted(live):
    """
    TLRO v2 is Right+Left+Up and TLRO_1 v2 is Right+Up+Left - the ONLY thing
    telling them apart. Sorting would erase it.
    """
    out = S.live_routing_catalog(symbol_type="TNodeUp")
    by = {s["symbol"]: s for s in out["symbols"]}
    v2 = lambda s: [v["directions"] for v in by[s]["variants"] if v["variantNr"] == 2][0]
    assert v2("TLRO") == ["Right", "Left", "Up"]
    assert v2("TLRO_1") == ["Right", "Up", "Left"]
    assert v2("TLRO") != v2("TLRO_1")


def test_a_single_match_is_not_flagged_ambiguous(live):
    out = S.live_routing_catalog(directions=["Left", "Up"])
    assert out["matched"] == 1
    assert "ambiguous" not in out


def test_no_match_says_how_to_find_out_what_exists(live):
    out = S.live_routing_catalog(directions=["Up", "Up", "Up"])
    assert out["matched"] == 0
    assert "without `directions`" in out["note"]


def test_results_are_grouped_by_type(live):
    out = S.live_routing_catalog()
    assert out["byType"]["Routing"] == ["CO"]
    assert sorted(out["byType"]["TNodeUp"]) == ["TLRO", "TLRO_1"]


def test_a_symbol_with_no_pins_still_appears(live):
    """CDPNG2 carries wire properties and has no connection points at all."""
    out = S.live_routing_catalog()
    assert "ConnectionDefinition" in out["byType"]


def test_a_pinless_symbol_never_matches_a_direction_query(live):
    out = S.live_routing_catalog(directions=["Right", "Down"])
    assert "CDPNG2" not in [s["symbol"] for s in out["symbols"]]


# ---------------------------------------------------------------------------
# It is a read
# ---------------------------------------------------------------------------

def test_the_catalog_never_writes(capture):
    S.live_routing_catalog()
    cs = capture["cs"]
    assert "GuardScratch(project," not in cs
    run_body = cs.split("[Start]")[1]
    for mutator in ("SetValue(", ".Remove(", "SetGraphics"):
        assert mutator not in run_body


def test_a_failed_read_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": False, "message": "no project open"})
    assert S.live_routing_catalog()["success"] is False
