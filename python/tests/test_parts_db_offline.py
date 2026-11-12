"""
Generated-C# assertions for the parts-database tools.

Both tools were completely non-functional and BOTH failed silently:

  parts_db_query    returned a list of empty dicts with success:true, because it
                    looked every property up on `part.Properties` - where none
                    of its own default property names exist.
  parts_db_get_part could only ever return "Timeout waiting for script results",
                    first because it referenced a member MDPart does not have
                    (CS1061 - a compile error reaches the caller only as a
                    timeout), and then because it put live EPLAN objects into the
                    dictionary that gets JSON-serialised at the end of the script.

Neither failure mode is visible from the Python side, which is why these tests
assert on the generated C# text instead. They run with EPLAN closed.
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

from api.actions import scripted  # noqa: E402


@pytest.fixture
def capture(monkeypatch):
    """Capture the C# a tool generates, without executing anything."""
    seen = {}

    def fake(script, timeout=30.0):
        seen["cs"] = script
        seen["timeout"] = timeout
        return {"success": True, "results": {}}

    monkeypatch.setattr(scripted, "_execute_script", fake)
    return seen


# ---------------------------------------------------------------------------
# parts_db_get_part
# ---------------------------------------------------------------------------

def test_get_part_does_not_reference_the_nonexistent_producttopgroup(capture):
    """
    MDPart has no `ProductTopGroup`. Reflecting over MDPart on 2027.0.1 lists
    `ProductTopGroup GenericProductGroup` - the TYPE is ProductTopGroup, the
    MEMBER is GenericProductGroup. Referencing the type name as a member gave
    CS1061 and the tool never ran.
    """
    scripted.parts_db_get_part("X")
    cs = capture["cs"]
    assert "part.ProductTopGroup" not in cs, (
        "MDPart.ProductTopGroup does not exist; this is the CS1061 that made "
        "the tool return only timeouts"
    )
    assert "part.GenericProductGroup" in cs


def test_get_part_stringifies_every_value_before_serialising(capture):
    """
    props.ARTICLE_* returns MDPropertyValue - a live EPLAN object. Putting one
    in the results dictionary sends JsonConvert.SerializeObject walking a native
    object graph, and the script never finishes writing its result file.
    """
    scripted.parts_db_get_part("X")
    cs = capture["cs"]
    raw = re.findall(r"props\.(ARTICLE_\w+)\s*\?\?", cs)
    assert not raw, (
        "these ARTICLE_* values reach the results dict as EPLAN objects rather "
        "than strings, which hangs the JSON serialiser: %s" % raw
    )
    for member in ("ARTICLE_PARTNR", "ARTICLE_DESCR1", "ARTICLE_MANUFACTURER"):
        assert "Str(props.%s)" % member in cs, (
            "%s must be flattened with Str() before it is stored" % member
        )


def test_get_part_defines_the_str_helper_it_uses(capture):
    scripted.parts_db_get_part("X")
    cs = capture["cs"]
    assert "static string Str(object value)" in cs


def test_get_part_escapes_the_part_number(capture):
    scripted.parts_db_get_part('weird" \\ value')
    cs = capture["cs"]
    assert 'weird\\" \\\\ value' in cs, "part_number must go through cs_escape"


def test_get_part_reports_not_found_rather_than_erroring(capture):
    scripted.parts_db_get_part("X")
    cs = capture["cs"]
    assert '"found"' in cs.replace("[", "").replace("]", "") or "found" in cs


# ---------------------------------------------------------------------------
# parts_db_query
# ---------------------------------------------------------------------------

def test_query_does_not_look_defaults_up_on_the_property_list(capture):
    """
    The regression: `part.Properties.GetType().GetProperty("PartNr")` returns
    null, because PartNr is a member of MDPart, not of
    MDPartsDatabaseItemPropertyList. The old code turned that null into "",
    so every part came back as an empty dict with success:true.
    """
    scripted.parts_db_query(limit=5)
    cs = capture["cs"]
    assert "part.Properties.GetType().GetProperty(propName)" not in cs, (
        "resolving caller property names against part.Properties alone is the "
        "bug that produced empty dicts"
    )
    assert "ReadPartProperty(part, propName)" in cs


def test_query_resolves_against_mdpart_first_then_the_property_list(capture):
    scripted.parts_db_query(limit=5)
    cs = capture["cs"]
    assert "FindUnambiguous(typeof(MDPart), propName)" in cs
    assert "FindUnambiguous(pl.GetType(), articleName)" in cs


def test_query_uses_a_declaredonly_walk_to_dodge_ambiguousmatch(capture):
    """
    MDPart declares `Properties` twice and ARTICLE_PARTNR has a plain and an
    indexed form, so GetProperty(name) throws AmbiguousMatchException. The walk
    must ask for the non-indexed declaration, one level at a time.
    """
    scripted.parts_db_query(limit=5)
    cs = capture["cs"]
    assert "BindingFlags.DeclaredOnly" in cs
    assert "Type.EmptyTypes" in cs


def test_query_maps_friendly_names_to_article_fields(capture):
    scripted.parts_db_query(limit=5)
    cs = capture["cs"]
    for friendly, article in (
        ("Description1", "ARTICLE_DESCR1"),
        ("Manufacturer", "ARTICLE_MANUFACTURER"),
        ("OrderNr", "ARTICLE_ORDERNR"),
    ):
        assert 'm["%s"] = "%s";' % (friendly, article) in cs


def test_query_reports_an_unknown_property_instead_of_blanking_it(capture):
    scripted.parts_db_query(limit=5)
    cs = capture["cs"]
    assert "MissingMemberException" in cs, (
        "an unresolvable property name must say so - a silent empty string is "
        "indistinguishable from a part that genuinely has no value"
    )
    assert '"<error: "' in cs


def test_query_limit_must_be_an_integer():
    """limit is interpolated outside a string literal, so it is code."""
    bad = scripted.parts_db_query(limit="5; DROP")
    assert bad["success"] is False
    assert "limit" in bad["error"].lower()


def test_query_rejects_a_non_identifier_filter_property():
    bad = scripted.parts_db_query(filter_property="a b", filter_value="x")
    assert bad["success"] is False


def test_query_filter_value_is_escaped(capture):
    scripted.parts_db_query(filter_property="PartNr", filter_value='x" || true')
    cs = capture["cs"]
    assert 'x\\" || true' in cs


def test_query_declares_reflection_namespace(capture):
    """The helper uses PropertyInfo/BindingFlags, so the using must be there."""
    scripted.parts_db_query(limit=1)
    assert "using System.Reflection;" in capture["cs"]
