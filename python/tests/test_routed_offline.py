"""
live_connect_pins_routed: two segments through a right-angled corner.

live_connect_pins draws ONE straight segment and refuses a diagonal, which is
honest but means only devices that happen to share an axis can be wired - and
that does not survive contact with a real page layout.

The geometry is decided in Python, so all of it is testable with EPLAN closed.
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


# Two devices sharing NEITHER axis - the case the straight tool refuses.
PROBE_OFFSET = {
    "success": True,
    "page": "+P/1",
    "from": {"placement": {
        "location": {"x": 60.0, "y": 200.0},
        "boundingBox": [{"x": 58.0, "y": 192.0}, {"x": 63.0, "y": 208.0}],
        "pins": [{"index": 0, "raw": {"x": 0.0, "y": 6.0}}]}},
    "to": {"placement": {
        "location": {"x": 140.0, "y": 150.0},
        "boundingBox": [{"x": 138.0, "y": 142.0}, {"x": 143.0, "y": 158.0}],
        "pins": [{"index": 0, "raw": {"x": 0.0, "y": 6.0}}]}},
}

# The same X - already routable with one straight segment.
PROBE_ALIGNED = {
    "success": True,
    "page": "+P/1",
    "from": PROBE_OFFSET["from"],
    "to": {"placement": {
        "location": {"x": 60.0, "y": 150.0},
        "boundingBox": [{"x": 58.0, "y": 142.0}, {"x": 63.0, "y": 158.0}],
        "pins": [{"index": 0, "raw": {"x": 0.0, "y": 6.0}}]}},
}


@pytest.fixture
def run(monkeypatch):
    """Drive the tool past its pin probe and hand back the draw script."""
    state = {"probe": PROBE_OFFSET, "scripts": []}

    def fake(script, timeout=30.0):
        state["scripts"].append(script)
        # Keyed on WHICH script this is, not on how many have run - the tool can
        # legitimately be called more than once per test, and a counter then
        # feeds a draw response back as the second call's pin probe.
        if "PinProbe" in script:
            return {"success": True, "results": state["probe"]}
        return {"success": True,
                "results": {"success": True, "segments": [
                    {"handle": "s1"}, {"handle": "s2"}], "segmentCount": 2}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return state


# ---------------------------------------------------------------------------
# When it should and should not route
# ---------------------------------------------------------------------------

def test_off_axis_pins_are_routed(run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert out["success"] is True
    assert any("PinProbe" not in s for s in run["scripts"]), "the draw script never ran"


def test_pins_already_on_an_axis_are_refused(run):
    """A corner there is a redundant elbow where one segment does the job."""
    run["probe"] = PROBE_ALIGNED
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert out["success"] is False
    assert "live_connect_pins" in out["error"]
    assert all("PinProbe" in s for s in run["scripts"]), "nothing should have been drawn"


def test_the_same_pin_twice_is_refused(run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hA", 0)
    assert out["success"] is False
    assert not run["scripts"]


@pytest.mark.parametrize("bad", ["diagonal", "z", "", None, 1])
def test_an_invalid_corner_is_refused_before_anything_runs(bad, run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, corner=bad)
    assert out["success"] is False
    assert not run["scripts"]


@pytest.mark.parametrize("corner", ["x", "X", " y ", "Y"])
def test_corner_is_case_and_space_tolerant(corner, run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, corner=corner)
    assert out["success"] is True


# ---------------------------------------------------------------------------
# The corner geometry
# ---------------------------------------------------------------------------

def test_corner_x_leaves_horizontally(run):
    """corner='x': out along Y-of-from, then down X-of-to."""
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, corner="x")
    assert out["corner"] == {"x": 140.0, "y": 206.0}


def test_corner_y_leaves_vertically(run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, corner="y")
    assert out["corner"] == {"x": 60.0, "y": 156.0}


def test_the_two_modes_produce_different_corners(run):
    a = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, corner="x")
    b = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, corner="y")
    assert a["corner"] != b["corner"]


def test_the_endpoints_are_the_pins_themselves(run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert out["from_point"] == {"x": 60.0, "y": 206.0}
    assert out["to_point"] == {"x": 140.0, "y": 156.0}


# ---------------------------------------------------------------------------
# The generated script
# ---------------------------------------------------------------------------

def test_each_segment_is_anchored_then_drawn_relative(run):
    """
    The straight version drew from the PAGE ORIGIN because it passed absolute
    coordinates with Location unset. Both segments must avoid that.
    """
    S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    cs = [s for s in run["scripts"] if "PinProbe" not in s][-1]
    assert 'GetWritable(dclType, "Location")' in cs
    assert "locProp.SetValue(dcl" in cs
    assert "MakePoint(ptType, 0.0, 0.0)" in cs, "each segment starts at its anchor"
    assert "s[2] - s[0]" in cs and "s[3] - s[1]" in cs, "the far end is a difference"


def test_a_missing_writable_location_is_a_hard_error(run):
    S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    cs = [s for s in run["scripts"] if "PinProbe" not in s][-1]
    assert "page origin" in cs


def test_exactly_two_segments_are_drawn(run):
    S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    cs = [s for s in run["scripts"] if "PinProbe" not in s][-1]
    # `new double[][] { new double[] {...}, new double[] {...} }`
    assert cs.count("new double[] {") == 2, "exactly two segments"
    assert "new double[][] {" in cs


def test_the_write_is_scratch_guarded_by_default(run):
    S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert "GuardScratch(project, false," in [
        s for s in run["scripts"] if "PinProbe" not in s][-1]


def test_the_override_is_honoured(run):
    S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0, allow_real_project=True)
    assert "GuardScratch(project, true," in [
        s for s in run["scripts"] if "PinProbe" not in s][-1]


def test_the_probe_does_not_write(run):
    S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert "GuardScratch(project," not in [
        s for s in run["scripts"] if "PinProbe" in s][0]


# ---------------------------------------------------------------------------
# Undo and honesty
# ---------------------------------------------------------------------------

def test_both_segment_handles_come_back(run):
    """Removing one leaves half a wire, which is worse than leaving both."""
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert out["undo"]["handles"] == ["s1", "s2"]
    assert "half a wire" in out["undo"]["note"]


def test_it_does_not_claim_the_devices_are_wired(run):
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert "scopeNote" in out
    assert "LOGICAL" in out["scopeNote"]
    assert "wired" not in str(out.get("segments"))


def test_a_failed_probe_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": False, "message": "no such handle"})
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert out["success"] is False


def test_an_unresolvable_pin_is_refused_rather_than_guessed(monkeypatch):
    """A pin whose frame is unknown has no coordinate - not (0,0)."""
    probe = {
        "success": True,
        "from": {"placement": {"location": {"x": 60.0, "y": 200.0},
                               "boundingBox": [{"x": 58.0, "y": 192.0},
                                               {"x": 63.0, "y": 208.0}],
                               "pins": [{"index": 0, "raw": {"x": 999.0, "y": 999.0}}]}},
        "to": PROBE_OFFSET["to"],
    }
    monkeypatch.setattr(S, "_execute_script",
                        lambda script, timeout=30.0: {"success": True, "results": probe})
    out = S.live_connect_pins_routed("+P/1", "hA", 0, "hB", 0)
    assert out["success"] is False
    assert "frame is unknown" in out["error"]
