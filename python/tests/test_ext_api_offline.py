"""The extension API (eplan_mcp.ext) is the only contract private extension packs depend on."""
import json
import os

from mcp.server.fastmcp import FastMCP

from mcp_server import server
from eplan_mcp import ext
from api.actions import scripthost
from tool_registry import ToolRegistry


def test_compatible_ranges():
    assert ext.compatible(None)                                  # undeclared = written for v1
    assert ext.compatible((1, 3))
    assert ext.compatible(ext.EXT_API_VERSION)
    assert not ext.compatible((ext.EXT_API_VERSION + 1, ext.EXT_API_VERSION + 2))


def _load(tmp_path, body):
    (tmp_path / "pack.py").write_text(body, encoding="utf-8")
    app, reg = FastMCP("t"), ToolRegistry()
    loaded = server.load_extensions(str(tmp_path), app=app, registry=reg, mode="full")
    return loaded, app


def test_extension_on_this_api_version_loads(tmp_path):
    loaded, app = _load(tmp_path, 'TOOL_PREFIX = "acme_"\nEXT_API = (1, 1)\n__all__ = ["hello"]\n'
                                  'def hello() -> dict:\n    """Say hi."""\n    return {"ok": True}\n')
    assert [x["module"] for x in loaded] == ["pack.py"]
    assert "acme_hello" in app._tool_manager._tools


def test_extension_for_another_api_version_is_refused(tmp_path, capsys):
    loaded, app = _load(tmp_path, 'EXT_API = (99, 99)\n__all__ = ["hello"]\n'
                                  'def hello() -> dict:\n    return {}\n')
    assert loaded == []
    assert "needs extension API" in capsys.readouterr().err


def test_registered_script_dir_brings_its_helpers(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "thing.cs").write_text("// @tool thing\nreturn 1;", encoding="utf-8")
    helper = tmp_path / "Helpers.cs"
    helper.write_text("public static class H {}", encoding="utf-8")
    monkeypatch.setattr(scripthost, "_extra_script_dirs", {})
    ext.register_script_dir(str(lib), helpers=[str(helper)])
    path, _ = scripthost._resolve_script("thing")
    assert scripthost._helpers_for(path) == [os.path.abspath(str(helper))]


def test_run_action_refuses_plainly_without_a_connection(monkeypatch):
    import api.actions._base as base
    monkeypatch.setattr(base, "_get_connected_manager",
                        lambda: (None, {"success": False, "message": "Not connected to EPLAN."}))
    try:
        ext.run_action("Anything")
    except RuntimeError as e:
        assert "Not connected" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
