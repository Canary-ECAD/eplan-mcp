"""
live_verify_page, live_set_device_tag, and the substitution bug they exposed.

The substitution tests are the important ones. Placeholder filling used to be a
CHAIN of .replace() calls, so a value inserted by an early step was still
visible to a later one. Found live: a page named "+TAGTEST/610" was substituted
for PAGENAME, then the TAG substitution rewrote "TAGTEST" INSIDE it, emitting
`+"-K1"TEST/610` and a CS0103 - which reaches the caller only as a timeout.

That was latent across the whole module, not just the new tools: a library named
"SNAP" or a page named "TOP" would have done the same to live_place_symbol.

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
    seen = {"scripts": []}

    def fake(script, timeout=30.0):
        seen["scripts"].append(script)
        seen["cs"] = script
        return {"success": True, "results": {"success": True}}

    monkeypatch.setattr(S, "_execute_script", fake)
    return seen


# ---------------------------------------------------------------------------
# _fill: one pass, word boundaries
# ---------------------------------------------------------------------------

def test_a_value_containing_another_token_name_is_not_re_substituted():
    """THE bug: a page called '+TAGTEST/610' had TAGTEST rewritten by TAG."""
    out = S._fill("page=PAGENAME tag=TAG", PAGENAME='"+TAGTEST/610"', TAG='"-K1"')
    assert out == 'page="+TAGTEST/610" tag="-K1"'
    assert "TEST/610" in out and '"-K1"TEST' not in out


def test_order_does_not_matter():
    a = S._fill("A=AA B=BB", AA="1", BB="2")
    b = S._fill("A=AA B=BB", BB="2", AA="1")
    assert a == b == "A=1 B=2"


def test_a_short_token_does_not_match_inside_a_longer_one():
    """LIB is a prefix of LIBNAME; AX and AY are two characters."""
    out = S._fill("x=LIB y=LIBNAME", LIB='"a"', LIBNAME='"b"')
    assert out == 'x="a" y="b"'


def test_a_token_is_not_matched_inside_an_identifier():
    out = S._fill("var TOPOLOGY; v=TOP;", TOP="7")
    assert "TOPOLOGY" in out and "v=7;" in out


def test_a_value_that_is_exactly_a_token_name_is_left_alone():
    """A library genuinely called 'LIB' must survive."""
    out = S._fill("lib=LIB sym=SYM", LIB='"LIB"', SYM='"S"')
    assert out == 'lib="LIB" sym="S"'


def test_supplying_a_token_the_template_lacks_is_an_error():
    with pytest.raises(RuntimeError) as exc:
        S._fill("only PAGENAME here", PAGENAME='"p"', NOSUCH="x")
    assert "NOSUCH" in str(exc.value)


def test_filling_nothing_returns_the_template():
    assert S._fill("unchanged") == "unchanged"


@pytest.mark.parametrize("hostile", [
    "+TAGTEST/610", "SNAPSHOT", "TOP", "LIBRARY", "MY-HANDLE-PAGE", "XVALUE",
])
def test_a_hostile_page_name_survives_every_writer(hostile, capture):
    """
    Each of these contains a token name. Before the fix at least one writer
    would have corrupted them into uncompilable C#.
    """
    S.live_read_page(hostile)
    assert '"%s"' % hostile in capture["cs"]
    S.live_place_symbol(hostile, "LIB", "SL", 1.0, 2.0)
    assert '"%s"' % hostile in capture["cs"]
    S.live_remove_placement(hostile, handle="h")
    assert '"%s"' % hostile in capture["cs"]


def test_a_hostile_library_name_survives_place_symbol(capture):
    S.live_place_symbol("P", "SNAP", "TOP", 1.0, 2.0)
    cs = capture["cs"]
    assert '"SNAP"' in cs and '"TOP"' in cs


# ---------------------------------------------------------------------------
# live_verify_page
# ---------------------------------------------------------------------------

def test_verify_refuses_an_empty_expectation(capture):
    """An empty expectation would pass trivially and teach nothing."""
    out = S.live_verify_page("P", {})
    assert out["success"] is False
    assert "trivially pass" in out["error"]
    assert not capture["scripts"]


def test_verify_refuses_a_non_dict_expectation(capture):
    out = S.live_verify_page("P", ["not", "a", "dict"])
    assert out["success"] is False
    assert not capture["scripts"]


def test_verify_reads_without_pins_and_does_not_write(capture):
    S.live_verify_page("P", {"placementCount": 1})
    cs = capture["cs"]
    assert "GuardScratch(project," not in cs, "a verify must never write"
    assert "ReadPage(page," in cs


def _read_result(monkeypatch, payload):
    monkeypatch.setattr(S, "_execute_script",
                        lambda script, timeout=30.0: {"success": True,
                                                      "results": payload})


def test_verify_reports_a_match(monkeypatch):
    _read_result(monkeypatch, {"success": True, "page": "+P/1",
                               "placementCount": 2, "placements": []})
    out = S.live_verify_page("P", {"placementCount": 2})
    assert out["match"] is True and out["differences"] == []


def test_verify_names_what_differs(monkeypatch):
    _read_result(monkeypatch, {"success": True, "page": "+P/1",
                               "placementCount": 2, "placements": []})
    out = S.live_verify_page("P", {"placementCount": 5})
    assert out["match"] is False
    assert "expected 5" in out["differences"][0] and "found 2" in out["differences"][0]


def test_verify_returns_the_page_state_it_compared_against(monkeypatch):
    _read_result(monkeypatch, {"success": True, "placementCount": 0,
                               "placements": []})
    out = S.live_verify_page("P", {"placementCount": 0})
    assert "page_state" in out, "the caller should not need a second call"


def test_verify_warns_when_the_read_was_truncated(monkeypatch):
    """A truncated read can turn a present placement into a false 'missing'."""
    _read_result(monkeypatch, {"success": True, "placementCount": 900,
                               "returned": 100, "truncated": True,
                               "placements": []})
    out = S.live_verify_page("P", {"placementCount": 900})
    assert "caution" in out and "truncated" in out["caution"]


def test_verify_passes_a_failed_read_straight_through(monkeypatch):
    monkeypatch.setattr(S, "_execute_script",
                        lambda script, timeout=30.0: {"success": False,
                                                      "message": "no such page"})
    out = S.live_verify_page("P", {"placementCount": 1})
    assert out["success"] is False


# ---------------------------------------------------------------------------
# live_set_device_tag
# ---------------------------------------------------------------------------

def test_set_tag_guards_the_project_by_default(capture):
    S.live_set_device_tag("P", "h", "-K1")
    assert "GuardScratch(project, false," in capture["cs"]


def test_set_tag_honours_the_override(capture):
    S.live_set_device_tag("P", "h", "-K1", allow_real_project=True)
    assert "GuardScratch(project, true," in capture["cs"]


def test_set_tag_refuses_a_duplicate_by_default(capture):
    """
    A tag already in use MERGES devices. Correct for a coil and its contacts,
    a silent rewire when a tag is reused by accident.
    """
    S.live_set_device_tag("P", "h", "-K1")
    assert "bool allowMerge = false;" in capture["cs"]


def test_set_tag_can_opt_into_the_merge(capture):
    S.live_set_device_tag("P", "h", "-K1", allow_merge=True)
    assert "bool allowMerge = true;" in capture["cs"]


def test_set_tag_only_accepts_a_function(capture):
    S.live_set_device_tag("P", "h", "-K1")
    assert 'target.GetType().Name != "Function"' in capture["cs"]


def test_set_tag_reads_the_stored_name_back(capture):
    """Structure settings reformat tags - measured, '-K1' stored as '+-K1'."""
    S.live_set_device_tag("P", "h", "-K1")
    assert 'results["name"] = PropText(target, "Name");' in capture["cs"]


def test_set_tag_reports_which_write_route_fired(capture):
    S.live_set_device_tag("P", "h", "-K1")
    assert 'results["route"] = route;' in capture["cs"]


def test_set_tag_notes_a_reformatted_tag(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True,
        "results": {"success": True, "name": "+-K1", "route": "Function.Name"},
    })
    out = S.live_set_device_tag("P", "h", "-K1")
    assert out["requestedTag"] == "-K1"
    assert "note" in out and "+-K1" in out["note"]


def test_set_tag_says_nothing_when_the_tag_stuck_verbatim(monkeypatch):
    monkeypatch.setattr(S, "_execute_script", lambda script, timeout=30.0: {
        "success": True, "results": {"success": True, "name": "-K1"},
    })
    assert "note" not in S.live_set_device_tag("P", "h", "-K1")


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_set_tag_requires_a_tag(bad, capture):
    out = S.live_set_device_tag("P", "h", bad)
    assert out["success"] is False
    assert not capture["scripts"]


def test_set_tag_refuses_a_result_path_token(capture):
    out = S.live_set_device_tag("P", "h", "{{RESULT_PATH}}")
    assert out["success"] is False
    assert not capture["scripts"]


def test_set_tag_escapes_a_quote(capture):
    S.live_set_device_tag("P", "h", 'K"1')
    assert 'K\\"1' in capture["cs"]


def test_set_tag_reports_devices_only_in_page_after(capture):
    """A page_after full of polylines would bury the thing that changed."""
    S.live_set_device_tag("P", "h", "-K1")
    assert 'new string[] { "Function" }' in capture["cs"]
