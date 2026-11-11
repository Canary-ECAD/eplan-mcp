"""
Pure helpers for the schematic primitives - no EPLAN, no pythonnet, no I/O.

Everything here is testable with EPLAN closed, which matters because the script
engine gives no compiler output: a C# compile error writes no result file and
reaches the caller as an indistinguishable "timeout". So as much logic as
possible lives on this side of the boundary, where a test can simply call it.

Two jobs:

1. THE INJECTION BOUNDARY. Every caller value that reaches generated C# goes
   through cs_double / cs_int / cs_text here. Numbers are interpolated OUTSIDE
   any string literal - they are code - so a non-number must be refused rather
   than escaped. Text goes inside a literal and is escaped, and additionally may
   not contain the {{RESULT_PATH}} token, because _execute_script replaces that
   token blindly across the whole script text.

2. GEOMETRY THE MODEL SHOULD NOT HAVE TO DO. Grid snapping, deciding whether a
   pin coordinate is relative or absolute, whether two pins coincide, and
   whether two points share an axis (an unrouted connection line can only be
   drawn between points that do).
"""

import math

__all__ = [
    "SchematicValueError",
    "cs_double", "cs_int", "cs_text", "cs_bool",
    "snap", "pins_coincide", "axis_aligned", "axis_alignment_message",
    "resolve_pin_frame", "absolute_pins", "diff_page",
    "DEFAULT_GRID_MM", "COINCIDENCE_TOLERANCE_MM",
]


# EPLAN's default schematic grid, measured live on 2027.0.1 via Page.GridSize:
# 3.175 mm, i.e. one eighth of an inch. Coordinates that do not sit on it tend
# to produce devices that look right but refuse to auto-connect.
DEFAULT_GRID_MM = 3.175

# Two pins are "the same point" within this distance. Deliberately smaller than
# half a grid step, so two pins on ADJACENT grid points are never merged.
COINCIDENCE_TOLERANCE_MM = 0.05

# The placeholder _execute_script substitutes. A caller value containing it
# would be rewritten into a filesystem path inside the generated script.
_RESULT_TOKEN = "{{RESULT_PATH}}"


class SchematicValueError(ValueError):
    """A caller value that must never reach generated C#."""


# ---------------------------------------------------------------------------
# The injection boundary
# ---------------------------------------------------------------------------

def cs_double(value, what):
    """
    A finite float, rendered so C# parses it identically on any locale.

    Interpolated outside a string literal, so this is CODE. A string that
    happens to look numeric is accepted (models routinely send "100.0"), but
    anything else - including NaN and infinity, which render as tokens C# does
    not accept - is refused.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise SchematicValueError(
            "%s must be a number, got %r. It is interpolated into C# source "
            "outside any string literal, so a non-number would be code." % (what, value)
        )
    if math.isnan(out) or math.isinf(out):
        raise SchematicValueError(
            "%s must be finite, got %r (C# would not parse NaN/Infinity here)."
            % (what, value)
        )
    # repr() keeps full precision and always emits a '.' or exponent, so the
    # value can never be mistaken for an int literal.
    text = repr(out)
    if "." not in text and "e" not in text and "E" not in text:
        text += ".0"
    return text


def cs_int(value, what, minimum=None, maximum=None):
    """An exact integer, likewise interpolated as code."""
    if isinstance(value, bool):
        raise SchematicValueError("%s must be an integer, not a bool." % what)
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise SchematicValueError(
            "%s must be an integer, got %r. It is interpolated into C# source "
            "outside any string literal." % (what, value)
        )
    if isinstance(value, float) and out != value:
        raise SchematicValueError("%s must be a whole number, got %r." % (what, value))
    if minimum is not None and out < minimum:
        raise SchematicValueError("%s must be >= %d, got %d." % (what, minimum, out))
    if maximum is not None and out > maximum:
        raise SchematicValueError("%s must be <= %d, got %d." % (what, maximum, out))
    return out


def cs_text(value, what, allow_empty=False):
    """
    A string bound for a C# string literal.

    Returns the RAW string; the caller passes it through cs_escape. The check
    that matters here is the {{RESULT_PATH}} token: _execute_script replaces it
    blindly across the whole script, so a caller value carrying it would be
    rewritten into a path and could break out of its literal.
    """
    if value is None:
        if allow_empty:
            return ""
        raise SchematicValueError("%s is required." % what)
    if not isinstance(value, str):
        raise SchematicValueError("%s must be a string, got %r." % (what, type(value).__name__))
    if not allow_empty and not value.strip():
        raise SchematicValueError("%s must not be empty." % what)
    if _RESULT_TOKEN in value:
        raise SchematicValueError(
            "%s must not contain %s: the script runner substitutes that token "
            "across the whole script, so it would be rewritten into a file path."
            % (what, _RESULT_TOKEN)
        )
    return value


def cs_bool(value):
    """Render a Python bool as a C# bool literal."""
    return "true" if value else "false"


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def snap(value, grid=DEFAULT_GRID_MM):
    """
    Round to the nearest grid multiple, matching the C# Snap() helper exactly.

    Uses floor(v/g + 0.5) rather than round(), because Python's round() is
    banker's rounding and C#'s Math.Round defaults to it too - both would break
    ties toward even and disagree with the intuitive "half goes up".
    """
    if grid is None or grid <= 0.0001:
        return round(float(value), 4)
    return round(math.floor(float(value) / grid + 0.5) * grid, 4)


def pins_coincide(a, b, tolerance=COINCIDENCE_TOLERANCE_MM):
    """Do two {'x','y'} points describe the same place?"""
    if not a or not b:
        return False
    try:
        return (abs(float(a["x"]) - float(b["x"])) <= tolerance
                and abs(float(a["y"]) - float(b["y"])) <= tolerance)
    except (KeyError, TypeError, ValueError):
        return False


def axis_aligned(a, b, tolerance=COINCIDENCE_TOLERANCE_MM):
    """
    True when two points share an X or a Y.

    A DynamicConnectionLine drawn with SetGraphics(p1, p2) is a single straight
    segment. Two points that share neither axis need a corner or a T-node, which
    this primitive layer does not draw - so the caller must be told rather than
    handed a diagonal that EPLAN will not treat as a connection.
    """
    if not a or not b:
        return False
    try:
        return (abs(float(a["x"]) - float(b["x"])) <= tolerance
                or abs(float(a["y"]) - float(b["y"])) <= tolerance)
    except (KeyError, TypeError, ValueError):
        return False


def axis_alignment_message(a, b):
    """Explain a refusal to draw a diagonal, with the numbers that caused it."""
    return (
        "Refusing to draw a diagonal connection: (%.4f, %.4f) and (%.4f, %.4f) "
        "share neither X nor Y. SetGraphics draws ONE straight segment, so a "
        "diagonal is not a wire EPLAN will treat as a connection. Move one "
        "device so the pins line up on an axis, or place an intermediate "
        "device - corner/T-node routing is not in this primitive layer."
        % (float(a["x"]), float(a["y"]), float(b["x"]), float(b["y"]))
    )


def resolve_pin_frame(raw, location, bbox, tolerance=0.51):
    """
    Decide whether a pin coordinate is already absolute or is an offset.

    EPLAN documents PinBase.Location as "the connection point's position
    relative to the symbol's insertion point", but the observed value is not
    consistent across placement types, and publishing an offset as an absolute
    page coordinate is the single most damaging thing this layer could do - it
    draws wires near the page origin that touch nothing while reporting success.

    So decide by EVIDENCE rather than by belief: whichever candidate falls
    inside the placement's own bounding box (grown by `tolerance`, since a pin
    sits exactly on the boundary) is the absolute one.

    Returns (point, frame) where frame is:
        "absolute"        raw was already page coordinates
        "relative"        raw was an offset; point is location + raw
        "unknown"         neither candidate fits, or there was nothing to
                          compare against. The caller MUST surface this rather
                          than pretending to a coordinate.
    """
    if not raw:
        return None, "unknown"
    try:
        rx, ry = float(raw["x"]), float(raw["y"])
    except (KeyError, TypeError, ValueError):
        return None, "unknown"

    if not bbox or location is None:
        return None, "unknown"

    try:
        lx, ly = float(location["x"]), float(location["y"])
    except (KeyError, TypeError, ValueError):
        return None, "unknown"

    try:
        x0 = min(float(p["x"]) for p in bbox) - tolerance
        x1 = max(float(p["x"]) for p in bbox) + tolerance
        y0 = min(float(p["y"]) for p in bbox) - tolerance
        y1 = max(float(p["y"]) for p in bbox) + tolerance
    except (KeyError, TypeError, ValueError):
        return None, "unknown"

    def inside(x, y):
        return x0 <= x <= x1 and y0 <= y <= y1

    if inside(rx, ry):
        return {"x": round(rx, 4), "y": round(ry, 4)}, "absolute"
    if inside(lx + rx, ly + ry):
        return {"x": round(lx + rx, 4), "y": round(ly + ry, 4)}, "relative"
    return None, "unknown"


def absolute_pins(placement):
    """
    Absolute page coordinates for every pin of one placement dict.

    Each entry is {"index", "designation", "raw", "point", "frame"}; "point" is
    None when the frame could not be established, and callers must treat that as
    "I do not know where this pin is", never as (0, 0).
    """
    out = []
    for pin in (placement or {}).get("pins") or []:
        point, frame = resolve_pin_frame(
            pin.get("raw"), placement.get("location"), placement.get("boundingBox")
        )
        entry = dict(pin)
        entry["point"] = point
        entry["frame"] = frame
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Diffing a page against an expectation
# ---------------------------------------------------------------------------

def diff_page(expected, actual, tolerance=COINCIDENCE_TOLERANCE_MM):
    """
    Compare an expected page state against one live_read_page returned.

    `expected` is a SUBSET written in live_read_page's own schema - which is the
    point: the read format doubles as the specification format, so "make the
    page look like this" is expressible without a second vocabulary, and a
    verification is just a re-read plus this function.

    Only keys present in `expected` are compared; anything else is ignored, so a
    caller can assert on placement count and one device's position without
    having to describe the whole page.

    Returns {"match": bool, "differences": [str, ...]}.
    """
    diffs = []

    exp_placements = expected.get("placements")
    act_placements = actual.get("placements") or []

    if "placementCount" in expected:
        want = expected["placementCount"]
        # Prefer the count the READER reported over the length of the list it
        # returned. Those differ whenever a read was truncated by `limit` or
        # narrowed by `types`, and comparing against the list length then
        # reports a mismatch that is an artefact of the read rather than a fact
        # about the page.
        got = actual.get("placementCount")
        if got is None:
            got = len(act_placements)
        if want != got:
            diffs.append("placementCount: expected %s, found %s" % (want, got))

    if exp_placements:
        for i, want in enumerate(exp_placements):
            match = _find_placement(want, act_placements, tolerance)
            if match is None:
                diffs.append(
                    "placement[%d]: nothing on the page matches %s" % (i, _describe(want))
                )
                continue
            for key in ("clrType", "name"):
                if key in want and want[key] != match.get(key):
                    diffs.append(
                        "placement[%d].%s: expected %r, found %r"
                        % (i, key, want[key], match.get(key))
                    )
            if "location" in want and not pins_coincide(
                want["location"], match.get("location"), tolerance
            ):
                diffs.append(
                    "placement[%d].location: expected %s, found %s"
                    % (i, want["location"], match.get("location"))
                )

    return {"match": not diffs, "differences": diffs}


def _describe(want):
    bits = []
    for key in ("clrType", "name", "handle"):
        if key in want:
            bits.append("%s=%r" % (key, want[key]))
    if "location" in want:
        bits.append("location=%s" % (want["location"],))
    return "{" + ", ".join(bits) + "}"


def _find_placement(want, actual_list, tolerance):
    """Best match by handle, else by type+location, else by type alone."""
    if "handle" in want:
        for got in actual_list:
            if got.get("handle") == want["handle"]:
                return got
        return None
    for got in actual_list:
        if "clrType" in want and got.get("clrType") != want["clrType"]:
            continue
        if "location" in want and not pins_coincide(
            want["location"], got.get("location"), tolerance
        ):
            continue
        if "name" in want and got.get("name") != want["name"]:
            continue
        return got
    return None
