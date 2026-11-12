"""
The `types` filter on live_read_page.

Why it exists: a real schematic page is mostly GRAPHICS. Measured on a
production project, one Circuit page held 1887 placements whose first 40 were
all PolyLine - so an unfiltered read exhausts its limit on geometry before it
reaches a single device, and a caller looking for devices concludes the page is
empty.

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


@pytest.fixture
def capture(monkeypatch):
    seen = {}

    def fake(script, timeout=30.0):
        seen["cs"] = script
        return {"success": True, "results": {"success": True}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


# ---------------------------------------------------------------------------
# The type filter on live_read_page
# ---------------------------------------------------------------------------

@pytest.fixture
def capture(monkeypatch):
    seen = {}

    def fake(script, timeout=30.0):
        seen["cs"] = script
        return {"success": True, "results": {"success": True}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


def test_read_page_without_types_filters_nothing(capture):
    S.live_read_page("P")
    assert "ReadPage(page, 200, true, null)" in capture["cs"]


def test_read_page_with_types_emits_a_csharp_array(capture):
    S.live_read_page("P", types=["Function"])
    assert 'new string[] { "Function" }' in capture["cs"]


def test_a_single_type_string_is_accepted(capture):
    S.live_read_page("P", types="Function")
    assert 'new string[] { "Function" }' in capture["cs"]


def test_type_names_are_escaped(capture):
    S.live_read_page("P", types=['Fun"ction'])
    assert 'Fun\\"ction' in capture["cs"]


def test_a_result_path_token_in_a_type_is_refused(capture):
    result = S.live_read_page("P", types=["{{RESULT_PATH}}"])
    assert result["success"] is False
    assert "cs" not in capture


def test_the_true_page_total_is_reported_alongside_the_filtered_count(capture):
    """
    A filtered read must never look like an empty page - that is exactly the
    confusion the filter exists to remove.
    """
    S.live_read_page("P", types=["Function"])
    cs = capture["cs"]
    assert 'd["placementCount"] = total;' in cs
    assert 'd["matched"] = matched;' in cs


def test_writes_report_their_page_after_unfiltered(capture):
    """A write's own proof should show everything it affected, not a subset."""
    S.live_place_symbol("P", "LIB", "SL", 1.0, 2.0)
    assert "ReadPage(page, 200, true, null)" in capture["cs"]
