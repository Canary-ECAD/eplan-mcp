"""Library scripts as tools, and the script host's MCP resources."""
import asyncio
import json
import os

from mcp.server.fastmcp import FastMCP

from mcp_server import server
import script_tools
from api.actions import scripthost
from tool_registry import ToolRegistry


def _lib(tmp_path, monkeypatch, prefix="acme_"):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "count.cs").write_text(
        "// @tool count_pages\n// @desc Count pages.\n// @arg page string optional Page filter\n"
        "// @arg limit int required Max pages\nreturn 1;", encoding="utf-8")
    (lib / "fix.cs").write_text("// @tool fix_things\n// @writes true\nreturn 1;", encoding="utf-8")
    (lib / "_template.cs").write_text("// @tool not_me\n", encoding="utf-8")
    monkeypatch.setattr(scripthost, "_extra_script_dirs", {})
    monkeypatch.setattr(scripthost, "_dir_prefix", {})
    scripthost.register_script_dir(str(lib), prefix=prefix)
    return lib


def test_scripts_are_indexed_but_not_published_by_default(tmp_path, monkeypatch):
    _lib(tmp_path, monkeypatch)
    monkeypatch.delenv("EPLAN_MCP_SCRIPT_TOOLS", raising=False)
    app, reg = FastMCP("t"), ToolRegistry()
    names = script_tools.register(app, reg, "discovery", server.register_actions)
    assert "acme_count_pages" in reg.hidden_names()           # searchable in discovery mode
    assert "acme_count_pages" in names and "acme_fix_things" in names and "acme_not_me" not in names
    assert "acme_count_pages" not in app._tool_manager._tools
    assert "eplan_project_info" in names                      # the public library is there too


def test_published_tools_mirror_the_header(tmp_path, monkeypatch):
    _lib(tmp_path, monkeypatch)
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_TOOLS", "publish")
    app, reg = FastMCP("t"), ToolRegistry()
    script_tools.register(app, reg, "full", server.register_actions)
    count = app._tool_manager._tools["acme_count_pages"]
    props = count.parameters["properties"]
    assert set(props) >= {"page", "limit", "project", "dry_run"}
    assert "limit" in count.parameters.get("required", [])
    assert count.annotations.readOnlyHint is False            # no @writes line: may write
    assert app._tool_manager._tools["acme_fix_things"].annotations.readOnlyHint is False


def test_read_only_needs_an_explicit_writes_false_and_no_unsafe(tmp_path, monkeypatch):
    lib = _lib(tmp_path, monkeypatch)
    (lib / "ro.cs").write_text("// @tool ro\n// @writes false\nreturn 1;", encoding="utf-8")
    (lib / "ro_unsafe.cs").write_text("// @tool ro_unsafe\n// @writes false\n// @unsafe\nreturn 1;",
                                      encoding="utf-8")
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_TOOLS", "publish")
    app, reg = FastMCP("t"), ToolRegistry()
    script_tools.register(app, reg, "full", server.register_actions)
    tools = app._tool_manager._tools
    assert tools["acme_ro"].annotations.readOnlyHint is True
    unsafe = tools["acme_ro_unsafe"].annotations
    assert unsafe.readOnlyHint is False and unsafe.destructiveHint is True


def test_a_bad_script_is_skipped_not_fatal(tmp_path, monkeypatch, capsys):
    lib = _lib(tmp_path, monkeypatch)
    (lib / "binary.cs").write_bytes(b"// @tool binary\n\xff\xfe")
    (lib / "badarg.cs").write_text("// @tool badarg\n// @arg 1x string\nreturn 1;", encoding="utf-8")
    (lib / "dup.cs").write_text("// @tool dup\n// @arg a string\n// @arg a int\nreturn 1;",
                                encoding="utf-8")
    (lib / "clash.cs").write_text("// @tool clash\n// @arg project string\nreturn 1;", encoding="utf-8")
    (lib / "under.cs").write_text("// @tool under\n// @arg _x string\nreturn 1;", encoding="utf-8")
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_TOOLS", "publish")
    app, reg = FastMCP("t"), ToolRegistry()
    names = script_tools.register(app, reg, "full", server.register_actions)
    assert "acme_count_pages" in names
    for bad in ("acme_binary", "acme_badarg", "acme_dup", "acme_clash", "acme_under"):
        assert bad not in names
    err = capsys.readouterr()
    assert "binary.cs" in err.err and "clash.cs" in err.err and "reserved" in err.err
    assert "skipping" not in err.out


def test_published_tool_calls_script_run_with_the_args(tmp_path, monkeypatch):
    lib = _lib(tmp_path, monkeypatch)
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_TOOLS", "publish")
    seen = {}
    monkeypatch.setattr(scripthost, "script_run", lambda **kw: seen.update(kw) or {"ok": True})
    app, reg = FastMCP("t"), ToolRegistry()
    script_tools.register(app, reg, "full", server.register_actions)
    out = asyncio.run(app.call_tool("acme_count_pages", {"limit": 3, "project": "x.elk"}))
    assert seen["script"] == os.path.join(str(lib), "count.cs")
    assert seen["args"] == {"limit": 3} and seen["project"] == "x.elk"


def test_a_script_never_shadows_a_real_tool(tmp_path, monkeypatch):
    lib = _lib(tmp_path, monkeypatch, prefix="eplan_")
    (lib / "ping.cs").write_text("// @tool ping\nreturn 1;", encoding="utf-8")
    monkeypatch.setenv("EPLAN_MCP_EXTENSIONS", "")
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_TOOLS", "publish")
    app, _, _ = server.build_app(mode="full")
    assert app._tool_manager._tools["eplan_ping"].fn.__module__ != "script_tools"


def test_resources(tmp_path, monkeypatch):
    _lib(tmp_path, monkeypatch)
    monkeypatch.setattr(scripthost, "RUNS_DIR", str(tmp_path / "runs"))
    run = tmp_path / "runs" / "20261110" / "abc123"
    run.mkdir(parents=True)
    (run / "result.json").write_text('{"ok": true}', encoding="utf-8")
    app = FastMCP("t")
    uris = script_tools.register_resources(app)
    assert "eplan-help://scripting-guide" in uris

    def read(uri):
        contents = asyncio.run(app.read_resource(uri))
        return contents[0].content if hasattr(contents[0], "content") else contents[0].text

    assert "fix_things" in read("eplan-script://library/fix_things")
    assert json.loads(read("eplan-script://runs/abc123/result"))["ok"] is True
    assert "ctx.Budget.Check()" in read("eplan-help://scripting-guide")


def test_run_file_reader_rejects_path_tricks(tmp_path, monkeypatch):
    monkeypatch.setattr(scripthost, "RUNS_DIR", str(tmp_path))
    for bad in ("../x", "a/b", "..", "c:x"):
        try:
            scripthost.read_run_file(bad, "result.json")
        except ValueError:
            continue
        raise AssertionError("accepted " + bad)


# The public library's own tools: names, guards in the schema, dry-run default and hints.
PUBLIC_TOOLS = {
    # name: (writes, required args)
    "text_placements": (False, {"page"}),
    "text_set_height": (True, {"page", "handle"}),
    "text_set_box": (True, {"page", "handle"}),
    "text_create": (True, {"page", "text", "x", "y"}),
    "line_styles": (False, {"page"}),
    "line_styles_set": (True, {"page", "x0", "y0", "x1", "y1", "limit"}),
    "function_move": (True, {"page", "moves"}),
    "function_remove": (True, {"page", "names", "symbol_prefix"}),
    "macrobox_snapshot": (False, set()),
    "macrobox_restore": (True, {"snapshot", "limit"}),
    "parts_snapshot": (False, set()),
    "parts_restore": (True, {"snapshot", "limit"}),
}


def _public_tools(monkeypatch):
    monkeypatch.setattr(scripthost, "_extra_script_dirs", {})
    monkeypatch.setattr(scripthost, "_dir_prefix", {})
    monkeypatch.setenv("EPLAN_MCP_EXTENSIONS", "")
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_TOOLS", "publish")
    app, reg = FastMCP("t"), ToolRegistry()
    names = script_tools.register(app, reg, "full", server.register_actions)
    return app, names


def test_every_public_library_tool_is_published(monkeypatch):
    app, names = _public_tools(monkeypatch)
    tools = app._tool_manager._tools
    for name in PUBLIC_TOOLS:
        assert "eplan_" + name in names, name           # never silently skipped or shadowed
    for old in ("textfit_snapshot", "textfit_set_height", "textfit_set_box", "graphic_pens",
                "macrobox_survey"):
        assert "eplan_" + old not in tools


def test_public_write_tools_default_to_dry_run_and_require_their_scope(monkeypatch):
    app, _ = _public_tools(monkeypatch)
    tools = app._tool_manager._tools
    for name, (writes, required) in PUBLIC_TOOLS.items():
        tool = tools["eplan_" + name]
        props = tool.parameters["properties"]
        assert props["dry_run"].get("default") is writes, name
        assert required <= set(tool.parameters.get("required", [])), name
        if writes:
            assert tool.annotations.readOnlyHint is False, name  # may write: never auto-approved
            assert tool.meta["canary-ecad/eplan"]["changesProject"] is True, name
            assert "dry_run: True (default)" in tool.description
        else:
            assert tool.annotations.readOnlyHint is True, name


def test_public_write_tool_sends_dry_run_unless_told_otherwise(monkeypatch):
    app, _ = _public_tools(monkeypatch)
    seen = []
    monkeypatch.setattr(scripthost, "script_run", lambda **kw: seen.append(kw) or {"ok": True})
    asyncio.run(app.call_tool("eplan_function_remove", {"page": "1", "names": ["A"], "symbol_prefix": "X"}))
    asyncio.run(app.call_tool("eplan_function_remove", {"page": "1", "names": ["A"], "symbol_prefix": "X",
                                                        "dry_run": False}))
    asyncio.run(app.call_tool("eplan_text_placements", {"page": "1"}))
    assert [kw["dry_run"] for kw in seen] == [True, False, False]


def test_public_descriptions_are_written_for_any_user():
    public = os.path.normcase(os.path.join(scripthost.DOTNET_DIR, "scripts"))
    for _prefix, path, header in script_tools.library():
        if os.path.normcase(os.path.dirname(path)) != public:
            continue
        text = (header.get("desc") or "").lower()
        for word in ("measure", "probe", "to see how", "textfit", "#19017"):
            assert word not in text, (path, word)


def test_public_tools_state_their_refusal_rules(monkeypatch):
    """The rules a caller cannot guess reach the tool description: a partial area is refused, a
    variant text's height is refused, parts go back by id, and empty text is not placed."""
    app, _ = _public_tools(monkeypatch)
    tools = app._tool_manager._tools
    assert "all four of x0, y0, x1, y1" in tools["eplan_line_styles"].description
    assert "always refused" in tools["eplan_text_set_height"].description
    assert "by object id" in tools["eplan_parts_restore"].description
    assert "not empty" in tools["eplan_text_create"].description
