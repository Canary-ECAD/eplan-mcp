"""Offline tests for the tool contract (tool_annotations.py, tools.json).

Every published tool must say what it does: the four MCP annotations, set
explicitly, and the EPLAN facts under _meta["canary-ecad/eplan"]. Clients such
as Bochica decide from them whether to ask before a call, so a new tool
without them must fail here rather than reach a release.
"""

import asyncio
import json
import os
import subprocess
import sys

import pytest

from tool_annotations import FLAGS, META_KEY, TOOL_FLAGS, annotate, parse_flags

ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
FACTS = ("changesProject", "runsCode", "changesEplan")
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tools(mode):
    import server

    app, _, _ = server.build_app(mode)
    return asyncio.run(app.list_tools())


@pytest.fixture(scope="module", params=["full", "discovery"])
def tools(request, monkeypatch_module):
    monkeypatch_module.delenv("EPLAN_MCP_EXTENSIONS", raising=False)
    return _tools(request.param)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_every_tool_has_all_four_annotations(tools):
    missing = [t.name for t in tools
               if t.annotations is None
               or any(getattr(t.annotations, key) is None for key in ANNOTATIONS)]
    assert missing == [], "add these tools to TOOL_FLAGS in tool_annotations.py"


def test_every_tool_has_the_eplan_facts(tools):
    missing = [t.name for t in tools
               if not isinstance((t.meta or {}).get(META_KEY), dict)
               or any(not isinstance(t.meta[META_KEY].get(k), bool) for k in FACTS)]
    assert missing == []


def test_the_facts_reach_the_wire_as_meta(tools):
    # MCP serialises Tool.meta as "_meta"; that is the key other clients read.
    wire = tools[0].model_dump(by_alias=True, exclude_none=True)
    assert META_KEY in wire["_meta"]


def test_no_tool_in_the_table_is_stale():
    known = {t.name for t in _tools("full")} | {t.name for t in _tools("discovery")}
    assert sorted(set(TOOL_FLAGS) - known) == []


def test_every_flag_string_parses():
    for name, flags in TOOL_FLAGS.items():
        assert parse_flags(flags) <= FLAGS, name


def test_read_tools_change_nothing(tools):
    for tool in tools:
        if tool.annotations.readOnlyHint:
            facts = tool.meta[META_KEY]
            assert not tool.annotations.destructiveHint, tool.name
            assert not any(facts[k] for k in FACTS), tool.name


def test_only_the_data_portal_tools_talk_to_the_outside_world(tools):
    # They reach the Data Portal through EPLAN's own sign-in; everything else is local.
    # In discovery mode eplan_tools_call can run them, so it carries the flag too.
    names = {t.name for t in tools}
    expected = (
        ["eplan_tools_call"]
        if "eplan_tools_call" in names
        else ["eplan_dataportal_add_to_download_list", "eplan_dataportal_search_count"]
    )
    assert sorted(t.name for t in tools if t.annotations.openWorldHint) == expected


@pytest.mark.parametrize("flags", ["read project", "read destructive", "write", "read code"])
def test_contradictory_or_unknown_flags_are_rejected(flags):
    with pytest.raises(ValueError):
        parse_flags(flags)


def test_project_argument_comes_from_the_signature():
    def demo(page: str, project_name: str = None):
        pass

    _, meta = annotate("demo", demo, table={"demo": "project"})
    assert meta[META_KEY] == {"changesProject": True, "runsCode": False,
                              "changesEplan": False, "projectArgument": "project_name"}


def test_an_unknown_tool_gets_nothing():
    assert annotate("eplan_not_a_tool") == (None, None)


@pytest.mark.parametrize("name,expected", [
    ("eplan_get_current_project", {"readOnlyHint": True, "destructiveHint": False}),
    ("eplan_export_pdf_project", {"readOnlyHint": False, "destructiveHint": False}),
    ("eplan_renumber_devices", {"readOnlyHint": False, "destructiveHint": False}),
    ("eplan_delete_device_list", {"readOnlyHint": False, "destructiveHint": True}),
])
def test_examples(name, expected):
    annotations, meta = annotate(name)
    assert {k: getattr(annotations, k) for k in expected} == expected
    assert META_KEY in meta


def test_scripts_and_actions_run_code():
    for name in ("eplan_execute_script", "eplan_action_run", "eplan_execute_raw_action",
                 "eplan_run_project_action", "eplan_register_addon"):
        assert annotate(name)[1][META_KEY]["runsCode"] is True, name


def test_extension_modules_can_state_their_facts(tmp_path, monkeypatch):
    import server

    (tmp_path / "site_tools.py").write_text(
        "__all__ = ['site_read', 'site_write']\n"
        "TOOL_FLAGS = {'site_read': 'read'}\n"
        "def site_read() -> dict:\n    return {}\n"
        "def site_write() -> dict:\n    return {}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EPLAN_MCP_EXTENSIONS", str(tmp_path))
    app, _, _ = server.build_app("full")
    by_name = {t.name: t for t in asyncio.run(app.list_tools())}
    assert by_name["eplan_site_read"].annotations.readOnlyHint is True
    assert by_name["eplan_site_write"].annotations is None


def test_tools_json_is_up_to_date():
    result = subprocess.run(
        [sys.executable, os.path.join(SERVER_ROOT, "tools", "dump_tools.py"), "--check"],
        capture_output=True, text=True, env={**os.environ, "EPLAN_MCP_EXTENSIONS": ""},
    )
    assert result.returncode == 0, result.stderr


def test_release_notes_flag_a_tool_that_became_read_only(tmp_path):
    sys.path.insert(0, os.path.join(SERVER_ROOT, "tools"))
    try:
        import release_notes
    finally:
        sys.path.pop(0)
    write = {"name": "eplan_x", "annotations": {"readOnlyHint": False},
             "facts": {"changesProject": True}}
    read = {"name": "eplan_x", "annotations": {"readOnlyHint": True},
            "facts": {"changesProject": False}}
    new = {"name": "eplan_new", "annotations": {"readOnlyHint": True}, "facts": {}}
    text = release_notes.notes({"eplan_x": write, "eplan_gone": write},
                               {"eplan_x": read, "eplan_new": new})
    assert "**Warning:** `eplan_x` used to change something and is now read-only" in text
    assert "### Added" in text and "`eplan_new`" in text
    assert "### Removed" in text and "`eplan_gone`" in text
    assert "readOnlyHint false → true" in text
    assert release_notes.notes(None, {"a": new}).startswith("Tool contract: 1 tools")


def test_tools_json_matches_the_table():
    with open(os.path.join(SERVER_ROOT, "tools.json"), encoding="utf-8") as f:
        published = json.load(f)
    assert {t["name"] for t in published["tools"]} <= set(TOOL_FLAGS)
