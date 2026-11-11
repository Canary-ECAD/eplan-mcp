"""Offline tests for the server's EPLAN_MCP_EXTENSIONS loader: extension
modules must register their tools with their own prefix, and a broken
extension must be skipped without preventing the server from loading."""

import asyncio

import pytest


@pytest.fixture(scope="module")
def server():
    import server as srv
    return srv


def _tool_names(srv):
    loop = asyncio.new_event_loop()
    try:
        return {t.name for t in loop.run_until_complete(srv.mcp.list_tools())}
    finally:
        loop.close()


def test_load_extensions_registers_prefixed_tools(server, tmp_path):
    (tmp_path / "good_ext.py").write_text(
        'TOOL_PREFIX = "tst_"\n'
        '__all__ = ["ping_ext"]\n'
        'def ping_ext() -> dict:\n'
        '    """Extension loader test tool."""\n'
        '    return {"success": True}\n'
    )
    loaded = server.load_extensions(str(tmp_path))
    assert len(loaded) == 1
    assert loaded[0]["prefix"] == "tst_"
    assert loaded[0]["tools"] == ["ping_ext"]
    assert "tst_ping_ext" in _tool_names(server)


def test_broken_extension_is_skipped(server, tmp_path, capsys):
    (tmp_path / "broken_ext.py").write_text("raise RuntimeError('boom')\n")
    (tmp_path / "ok_ext.py").write_text(
        'TOOL_PREFIX = "tst2_"\n'
        '__all__ = ["ok_tool"]\n'
        'def ok_tool() -> dict:\n'
        '    """Still loads."""\n'
        '    return {"success": True}\n'
    )
    loaded = server.load_extensions(str(tmp_path))
    assert [e["module"] for e in loaded] == ["ok_ext.py"]
    assert "tst2_ok_tool" in _tool_names(server)
    err = capsys.readouterr().err
    assert "broken_ext.py failed to load" in err


def test_module_without_all_is_skipped(server, tmp_path):
    (tmp_path / "noall_ext.py").write_text("def hidden():\n    return 1\n")
    assert server.load_extensions(str(tmp_path)) == []


def test_missing_dir_is_skipped(server, tmp_path):
    assert server.load_extensions(str(tmp_path / "does_not_exist")) == []


def test_underscore_files_ignored(server, tmp_path):
    (tmp_path / "_private.py").write_text("raise RuntimeError('must not import')\n")
    assert server.load_extensions(str(tmp_path)) == []
