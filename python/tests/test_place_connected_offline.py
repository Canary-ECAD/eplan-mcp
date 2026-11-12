"""
live_place_connected: place a device by RELATIONSHIP, not by coordinate.

The point of the tool is that "put a contact 40mm below -K1's pin 2" needs no
millimetre arithmetic from the caller. It solves for the location such that the
new symbol's own pin faces the anchor pin across a shared axis, which is the
condition EPLAN needs to draw an autoconnecting line - so it draws no line, and
should not.

Everything it refuses, it refuses because the placement would LOOK right and
fail to connect: an off-grid pin, a rotation with no pin facing back, a pin
whose position could not be resolved. Those are the expensive failures, because
nothing about them is visible until connections are generated and something is
quietly missing.

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


GRID = 3.175

# -A1 at (120.65, 234.95): pin0 faces Up, pin1 faces Down.
ANCHOR = {
    "location": {"x": 120.65, "y": 234.95},
    "boundingBox": [{"x": 118.0, "y": 228.0}, {"x": 123.0, "y": 242.0}],
    "pins": [
        {"index": 0, "direction": "Up", "raw": {"x": 0.0, "y": 6.35}},
        {"index": 1, "direction": "Down", "raw": {"x": 0.0, "y": -6.35}},
    ],
}
# SL v0 is vertical, v1 horizontal - measured.
VERTICAL = {"library": "L", "symbol": "SL", "variantNr": 0, "type": "Function",
            "pins": [{"direction": "Up", "offset": {"x": 0.0, "y": 6.35}},
                     {"direction": "Down", "offset": {"x": 0.0, "y": -6.35}}]}
HORIZONTAL = {"library": "L", "symbol": "SL", "variantNr": 1, "type": "Function",
              "pins": [{"direction": "Left", "offset": {"x": -6.35, "y": 0.0}},
                       {"direction": "Right", "offset": {"x": 6.35, "y": 0.0}}]}
# A symbol with TWO pins facing the same way - the ambiguous case.
TWO_UP = {"library": "L", "symbol": "DBL", "variantNr": 0, "type": "Function",
          "pins": [{"direction": "Up", "offset": {"x": -5.0, "y": 6.35}},
                   {"direction": "Up", "offset": {"x": 5.0, "y": 6.35}}]}


@pytest.fixture
def eplan(monkeypatch):
    state = {"anchor": ANCHOR, "candidate": VERTICAL, "grid": GRID,
             "scripts": [], "placed": [], "place_args": []}

    def fake(script, timeout=30.0):
        state["scripts"].append(script)
        if "ReadVariantPins" in script and "results[\"candidate\"]" in script:
            return {"success": True, "results": {
                "success": True, "page": "+P/1", "gridSize": state["grid"],
                "anchor": dict(state["anchor"]),
                "candidate": dict(state["candidate"])}}
        state["placed"].append(script)
        return {"success": True, "results": {
            "success": True, "page": "+P/1", "handle": "new1",
            "placed": {"location": {"x": 0.0, "y": 0.0},
                       "boundingBox": [{"x": -1.0, "y": -1.0}, {"x": 1.0, "y": 1.0}],
                       "pins": []}}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return state


def place(**kw):
    args = dict(page="+P/1", to_handle="hA", to_pin=1, library="L",
                symbol="SL", distance=38.1)
    args.update(kw)
    return S.live_place_connected(**args)


# ---------------------------------------------------------------------------
# It solves for the location
# ---------------------------------------------------------------------------

def test_the_location_is_solved_from_the_relationship(eplan):
    """
    Anchor pin faces Down at y=228.60. 38.1mm down puts the new pin at 190.50.
    That pin sits +6.35 above its own symbol, so the symbol goes at 184.15.
    Confirmed against the live run.
    """
    out = place()
    assert out["success"]
    al = out["alignment"]
    assert al["placed"]["point"] == {"x": 120.65, "y": 190.50}
    assert al["location"] == {"x": 120.65, "y": 184.15}
    assert al["axis"] == "y"


def test_it_goes_the_way_the_anchor_pin_faces(eplan):
    down = place(to_pin=1)["alignment"]["placed"]["point"]
    up = place(to_pin=0)["alignment"]["placed"]["point"]
    assert down["y"] < ANCHOR["location"]["y"] < up["y"]
    assert down["x"] == up["x"] == 120.65


def test_a_horizontal_run_solves_on_the_x_axis(eplan):
    eplan["anchor"] = {
        "location": {"x": 100.0, "y": 200.0},
        "boundingBox": [{"x": 93.0, "y": 198.0}, {"x": 107.0, "y": 202.0}],
        "pins": [{"index": 0, "direction": "Right", "raw": {"x": 6.35, "y": 0.0}}],
    }
    eplan["candidate"] = HORIZONTAL
    al = place(to_pin=0)["alignment"]
    assert al["axis"] == "x"
    assert al["placed"]["direction"] == "Left"
    assert al["placed"]["point"]["y"] == 200.0


def test_the_new_symbol_is_placed_without_snapping(eplan):
    """
    The location was SOLVED to put a pin on the grid. Re-snapping the location
    would move the pin back off it - the symbol's own pin offset need not be a
    grid multiple.
    """
    place()
    assert "bool doSnap = false;" in eplan["placed"][0]


def test_no_line_is_ever_drawn(eplan):
    """Two facing pins on a shared axis ARE the connection."""
    place()
    for cs in eplan["scripts"]:
        # Checks for CALLS, not for words. "DynamicConnectionLine" appears in a
        # comment in the shared helpers, so grepping the whole script for the
        # name flags every script ever emitted - the same false positive that
        # has bitten these checks twice already.
        assert "SetGraphics" not in cs
        assert 'FindType("Eplan.EplApi.DataModel.DynamicConnectionLine")' not in cs


def test_the_result_says_connections_still_need_generating(eplan):
    assert "generate_connections" in place()["alignment"]["note"]


# ---------------------------------------------------------------------------
# What it refuses, and why each would look right and fail
# ---------------------------------------------------------------------------

def test_an_off_grid_distance_is_refused_with_the_nearest_multiples(eplan):
    out = place(distance=40.0)
    assert out["success"] is False
    assert "not a multiple of the page grid" in out["error"]
    assert "38.1" in out["error"], "the nearest usable distance is not offered"
    assert not eplan["placed"]


def test_an_exact_grid_multiple_is_accepted(eplan):
    assert place(distance=GRID * 12)["success"]


def test_a_rotation_with_no_pin_facing_back_is_refused(eplan):
    """
    SL v1 faces Left/Right; against a Down-facing anchor nothing of it faces
    back. Placed anyway it would sit in exactly the right place and never
    connect.
    """
    eplan["candidate"] = HORIZONTAL
    out = place(variant_nr=1)
    assert out["success"] is False
    assert "no pin facing Up" in out["error"]
    assert "variant_nr is the rotation" in out["error"]
    assert not eplan["placed"]


def test_two_pins_facing_back_is_refused_rather_than_guessed(eplan):
    eplan["candidate"] = TWO_UP
    out = place(symbol="DBL")
    assert out["success"] is False
    assert out["ambiguous"] is True
    assert "pass new_pin" in out["error"]
    assert not eplan["placed"]


def test_naming_the_pin_resolves_it(eplan):
    eplan["candidate"] = TWO_UP
    out = place(symbol="DBL", new_pin=1)
    assert out["success"]
    assert out["alignment"]["placed"]["pin"] == 1
    # Pin 1 sits +5 in x, so the symbol shifts -5 to put the pin on the axis.
    assert out["alignment"]["location"]["x"] == pytest.approx(115.65)


def test_a_named_pin_that_faces_the_wrong_way_is_refused(eplan):
    out = place(new_pin=1)          # SL v0 pin1 faces Down, same as the anchor
    assert out["success"] is False
    assert "does not face" in out["error"]
    assert not eplan["placed"]


def test_a_pin_index_that_does_not_exist_is_refused(eplan):
    out = place(to_pin=99)
    assert out["success"] is False
    assert "has no pin 99" in out["error"]
    assert "0, 1" in out["error"], "it should say which pins there are"
    assert not eplan["placed"]


def test_a_pin_with_no_direction_cannot_anchor_anything(eplan):
    eplan["anchor"] = dict(ANCHOR, pins=[
        {"index": 0, "direction": "Undefined", "raw": {"x": 0.0, "y": 0.0}}])
    out = place(to_pin=0)
    assert out["success"] is False
    assert "no axis to line up along" in out["error"]
    assert not eplan["placed"]


def test_an_unresolvable_pin_position_is_never_treated_as_the_origin(eplan):
    """The failure this replaces: a device placed at (0,0) on the page frame."""
    eplan["anchor"] = {
        "location": {"x": 120.65, "y": 234.95},
        "pins": [{"index": 0, "direction": "Down"}],   # no raw, no bbox
    }
    out = place(to_pin=0)
    assert out["success"] is False
    assert "page origin" in out["error"]
    assert not eplan["placed"]


@pytest.mark.parametrize("bad", [0, -10.0, "x"])
def test_a_nonpositive_or_nonnumeric_distance_is_refused(bad, eplan):
    out = place(distance=bad)
    assert out["success"] is False
    assert not eplan["scripts"]


def test_the_direction_comes_from_the_pin_not_the_sign_of_distance(eplan):
    out = place(distance=-38.1)
    assert out["success"] is False
    assert "DIRECTION comes from the anchor pin" in out["error"]


@pytest.mark.parametrize("bad", ["{{RESULT_PATH}}", None, 7])
def test_a_hostile_handle_never_reaches_a_script(bad, eplan):
    out = place(to_handle=bad)
    assert out["success"] is False
    assert not eplan["scripts"]


def test_a_failed_probe_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": False, "message": "no project open"})
    assert place()["success"] is False


def test_opposites_are_symmetric():
    for a, b in S.OPPOSITE_DIRECTION.items():
        assert S.OPPOSITE_DIRECTION[b] == a
