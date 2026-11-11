"""
schematic_model.py - the pure half of the schematic primitives.

Everything here runs with EPLAN closed. That is the point of the module: the
script engine reports a compile error only as a timeout, so any logic that can
live on the Python side should, where a test can simply call it.
"""

import math

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(os.path.dirname(HERE), "mcp_server")
for p in (MCP, os.path.join(MCP, "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

from api.actions.schematic_model import (  # noqa: E402
    DEFAULT_GRID_MM,
    SchematicValueError,
    absolute_pins,
    axis_aligned,
    cs_bool,
    cs_double,
    cs_int,
    cs_text,
    diff_page,
    pins_coincide,
    resolve_pin_frame,
    snap,
)


# ---------------------------------------------------------------------------
# The injection boundary. These values become CODE, not data.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected_prefix", [
    (10, "10"), (10.5, "10.5"), (-3.25, "-3.25"), (0, "0"), ("12.5", "12.5"),
])
def test_cs_double_accepts_numbers_and_numeric_strings(value, expected_prefix):
    out = cs_double(value, "x")
    assert out.startswith(expected_prefix)
    # Must always be parseable as a C# double literal, never bare like "10".
    assert "." in out or "e" in out.lower()


@pytest.mark.parametrize("bad", [
    "10; System.Diagnostics.Process.Start(\"calc\")",
    "0.0 + Evil()",
    None, "", "abc", [], {},
    float("nan"), float("inf"), float("-inf"),
])
def test_cs_double_refuses_anything_that_is_not_a_finite_number(bad):
    with pytest.raises(SchematicValueError):
        cs_double(bad, "x")


def test_cs_double_round_trips_through_float():
    assert float(cs_double(3.175, "x")) == 3.175


@pytest.mark.parametrize("bad", ["1; Evil()", "abc", None, 1.5, True, [], {}])
def test_cs_int_refuses_non_integers(bad):
    with pytest.raises(SchematicValueError):
        cs_int(bad, "n")


def test_cs_int_enforces_bounds():
    assert cs_int(5, "n", minimum=1, maximum=10) == 5
    with pytest.raises(SchematicValueError):
        cs_int(0, "n", minimum=1)
    with pytest.raises(SchematicValueError):
        cs_int(11, "n", maximum=10)


def test_cs_int_accepts_a_float_that_is_exactly_whole():
    assert cs_int(5.0, "n") == 5


def test_cs_text_rejects_the_result_path_token():
    """
    _execute_script replaces {{RESULT_PATH}} blindly across the whole script, so
    a caller value carrying it would be rewritten into a filesystem path and
    could break out of its string literal.
    """
    with pytest.raises(SchematicValueError) as exc:
        cs_text("page{{RESULT_PATH}}x", "page")
    assert "RESULT_PATH" in str(exc.value)


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_cs_text_requires_a_value_unless_empty_is_allowed(bad):
    with pytest.raises(SchematicValueError):
        cs_text(bad, "page")


@pytest.mark.parametrize("value,expected", [(None, ""), ("", ""), ("   ", "   ")])
def test_cs_text_allow_empty_passes_the_value_through(value, expected):
    """
    allow_empty means "absent is fine", not "normalise". A caller that passes
    whitespace deliberately (a filter that should match everything, say) gets
    exactly what it passed; only None becomes "".
    """
    assert cs_text(value, "contains", allow_empty=True) == expected


def test_cs_text_refuses_non_strings():
    with pytest.raises(SchematicValueError):
        cs_text(123, "page")


def test_cs_bool_renders_csharp_literals():
    assert cs_bool(True) == "true"
    assert cs_bool(False) == "false"


# ---------------------------------------------------------------------------
# Grid snapping - must agree with the C# Snap() helper exactly.
# ---------------------------------------------------------------------------

def test_snap_rounds_to_the_grid():
    assert snap(60.0, 3.175) == 60.325
    assert snap(140.0, 3.175) == 139.7
    assert snap(0.0, 3.175) == 0.0


def _csharp_snap(v, g):
    """
    Literal transcription of the C# Snap() helper in live.py.

    The property that matters is not which way a tie goes - 1.5*3.175/3.175 is
    1.4999999999999998 in binary floating point, so there is no exact tie to
    break - but that BOTH sides compute the identical value. Python's round()
    is banker's rounding and would diverge from C#'s formula; floor(v/g + 0.5)
    is what live.py emits, so that is what this module must do.
    """
    if g is None or g <= 0.0001:
        return round(float(v), 4)
    return round(math.floor(float(v) / g + 0.5) * g, 4)


@pytest.mark.parametrize("value", [
    0.0, 1.0, 3.174, 3.176, 60.0, 140.0, 200.0, -12.7,
    1.5 * 3.175, 2.5 * 3.175, 0.5 * 3.175, 99.9999,
])
def test_snap_matches_the_csharp_formula_exactly(value):
    """
    A Python-side prediction that disagrees with the C#-side placement puts the
    device on a different grid point than the caller was told.
    """
    assert snap(value, 3.175) == _csharp_snap(value, 3.175)


def test_snap_is_a_noop_for_a_zero_or_missing_grid():
    assert snap(10.123456, 0) == 10.1235
    assert snap(10.123456, None) == 10.1235


def test_default_grid_is_the_measured_one():
    """3.175mm = 1/8 inch, read off Page.GridSize on 2027.0.1."""
    assert DEFAULT_GRID_MM == pytest.approx(25.4 / 8)


# ---------------------------------------------------------------------------
# Coincidence and axis alignment
# ---------------------------------------------------------------------------

def test_pins_coincide_within_tolerance():
    assert pins_coincide({"x": 1.0, "y": 2.0}, {"x": 1.0, "y": 2.0})
    assert pins_coincide({"x": 1.0, "y": 2.0}, {"x": 1.01, "y": 2.0}, tolerance=0.05)
    assert not pins_coincide({"x": 1.0, "y": 2.0}, {"x": 1.5, "y": 2.0})


def test_coincidence_tolerance_never_merges_adjacent_grid_points():
    a = {"x": 0.0, "y": 0.0}
    b = {"x": DEFAULT_GRID_MM, "y": 0.0}
    assert not pins_coincide(a, b)


@pytest.mark.parametrize("a,b,expected", [
    ({"x": 0, "y": 0}, {"x": 10, "y": 0}, True),    # shares Y
    ({"x": 0, "y": 0}, {"x": 0, "y": 10}, True),    # shares X
    ({"x": 0, "y": 0}, {"x": 10, "y": 10}, False),  # diagonal
])
def test_axis_aligned(a, b, expected):
    assert axis_aligned(a, b) is expected


def test_axis_aligned_handles_missing_input():
    assert axis_aligned(None, {"x": 0, "y": 0}) is False
    assert axis_aligned({}, {}) is False


# ---------------------------------------------------------------------------
# Pin frame resolution - the "do not publish an offset as a page coordinate" rule
# ---------------------------------------------------------------------------

BBOX = [{"x": 58.0, "y": 192.0}, {"x": 63.0, "y": 208.0}]
LOC = {"x": 60.325, "y": 200.025}


def test_relative_pin_is_offset_by_the_location():
    """Measured live: an SL pin reports raw (0, 6.35) with location (60.3, 200)."""
    point, frame = resolve_pin_frame({"x": 0.0, "y": 6.35}, LOC, BBOX)
    assert frame == "relative"
    assert point == {"x": 60.325, "y": 206.375}


def test_absolute_pin_is_taken_as_is():
    point, frame = resolve_pin_frame({"x": 60.325, "y": 206.375}, LOC, BBOX)
    assert frame == "absolute"
    assert point == {"x": 60.325, "y": 206.375}


def test_a_pin_that_fits_neither_frame_is_unknown_not_a_guess():
    """
    The whole point: reporting (0,0) for a pin whose frame we cannot establish
    would draw wires near the page origin that touch nothing, while claiming
    success.
    """
    point, frame = resolve_pin_frame({"x": 900.0, "y": 900.0}, LOC, BBOX)
    assert frame == "unknown"
    assert point is None


@pytest.mark.parametrize("raw,loc,bbox", [
    (None, LOC, BBOX),
    ({"x": 0, "y": 0}, None, BBOX),
    ({"x": 0, "y": 0}, LOC, None),
    ({"x": 0, "y": 0}, LOC, []),
    ({"nope": 1}, LOC, BBOX),
])
def test_missing_inputs_yield_unknown_rather_than_an_exception(raw, loc, bbox):
    point, frame = resolve_pin_frame(raw, loc, bbox)
    assert frame == "unknown" and point is None


def test_absolute_pins_annotates_every_pin():
    placement = {
        "location": LOC,
        "boundingBox": BBOX,
        "pins": [
            {"index": 0, "raw": {"x": 0.0, "y": 6.35}},
            {"index": 1, "raw": {"x": 999.0, "y": 999.0}},
        ],
    }
    pins = absolute_pins(placement)
    assert pins[0]["frame"] == "relative" and pins[0]["point"] is not None
    assert pins[1]["frame"] == "unknown" and pins[1]["point"] is None
    # The original pin dicts must not be mutated in place.
    assert "frame" not in placement["pins"][0]


def test_absolute_pins_on_a_placement_with_no_pins():
    assert absolute_pins({"location": LOC, "boundingBox": BBOX}) == []
    assert absolute_pins(None) == []


# ---------------------------------------------------------------------------
# diff_page - the read format doubles as the specification format
# ---------------------------------------------------------------------------

ACTUAL = {
    "page": "+MCPTEST/777",
    "placementCount": 3,
    "placements": [
        {"clrType": "DynamicConnectionLine", "handle": "h3"},
        {"clrType": "Function", "handle": "h1", "name": "+",
         "location": {"x": 60.325, "y": 200.025}},
        {"clrType": "Function", "handle": "h2", "name": "+",
         "location": {"x": 139.7, "y": 200.025}},
    ],
}


def test_diff_page_matches_a_correct_subset():
    result = diff_page({"placementCount": 3}, ACTUAL)
    assert result["match"] and result["differences"] == []


def test_diff_page_reports_a_wrong_count():
    result = diff_page({"placementCount": 5}, ACTUAL)
    assert not result["match"]
    assert "placementCount" in result["differences"][0]


def test_diff_page_matches_a_placement_by_handle():
    result = diff_page(
        {"placements": [{"handle": "h1", "clrType": "Function"}]}, ACTUAL)
    assert result["match"]


def test_diff_page_matches_a_placement_by_type_and_location():
    result = diff_page(
        {"placements": [
            {"clrType": "Function", "location": {"x": 139.7, "y": 200.025}}]},
        ACTUAL)
    assert result["match"]


def test_diff_page_reports_a_missing_placement():
    result = diff_page(
        {"placements": [{"clrType": "Terminal"}]}, ACTUAL)
    assert not result["match"]
    assert "nothing on the page matches" in result["differences"][0]


def test_diff_page_reports_a_wrong_location_for_a_known_handle():
    result = diff_page(
        {"placements": [{"handle": "h1", "location": {"x": 0.0, "y": 0.0}}]},
        ACTUAL)
    assert not result["match"]
    assert "location" in result["differences"][0]


def test_diff_page_ignores_keys_the_expectation_does_not_mention():
    """A caller must be able to assert on one thing without describing the page."""
    result = diff_page({"placements": [{"handle": "h1"}]}, ACTUAL)
    assert result["match"]


def test_diff_page_on_an_empty_expectation_matches_anything():
    assert diff_page({}, ACTUAL)["match"]
