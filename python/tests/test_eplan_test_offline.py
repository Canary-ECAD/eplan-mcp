"""
eplan_test() - Audit #42 item 10.

The default path used to build a script whose body was
`MessageBox.Show(...)` and execute it through the RAW manager, blocking this
server (SynchronousMode = True inside ExecuteAction) until a human clicked OK
in the EPLAN window - a Windows dialog, not an EPLAN one, so QuietMode could
never have suppressed it. This pins the new default: a non-interactive
round-trip through scripted._execute_script, with the old dialog kept only
behind an explicit show_dialog=True.

No EPLAN needed - _get_connected_manager / _execute_script are stubbed.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(os.path.dirname(HERE), "mcp_server")
for p in (MCP, os.path.join(MCP, "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

import server  # noqa: E402
from api.actions import scripted  # noqa: E402


@pytest.fixture
def connected(monkeypatch):
    manager = SimpleNamespace(connected=True, execute_action=None)
    monkeypatch.setattr(server, "get_manager", lambda: manager)
    return manager


def test_default_never_touches_execute_action_or_messagebox(connected, monkeypatch):
    """The blocking path must be unreachable unless explicitly asked for."""
    calls = []
    connected.execute_action = lambda *a, **kw: calls.append((a, kw)) or {"success": True}
    monkeypatch.setattr(scripted, "_execute_script",
                        lambda script, timeout=30.0: {
                            "success": True,
                            "results": {"success": True, "message": "MCP Connection OK"},
                        })
    result = json.loads(server.eplan_test())
    assert result["success"] is True
    assert calls == [], "the blocking manager.execute_action path was reached"


def test_default_script_never_mentions_messagebox(connected, monkeypatch):
    seen = {}

    def fake_execute_script(script, timeout=30.0):
        seen["script"] = script
        return {"success": True, "results": {"success": True, "message": "ok"}}

    monkeypatch.setattr(scripted, "_execute_script", fake_execute_script)
    server.eplan_test()
    assert "MessageBox" not in seen["script"]
    assert "{{RESULT_PATH}}" in seen["script"]


def test_default_reports_script_failure_not_a_bare_true(connected, monkeypatch):
    monkeypatch.setattr(scripted, "_execute_script",
                        lambda script, timeout=30.0: {
                            "success": False, "error": "boom",
                        })
    result = json.loads(server.eplan_test())
    assert result["success"] is False
    assert "boom" in result["message"]


def test_not_connected_short_circuits_before_any_script(monkeypatch):
    monkeypatch.setattr(server, "get_manager", lambda: SimpleNamespace(connected=False))
    result = json.loads(server.eplan_test())
    assert result["success"] is False
    assert "Not connected" in result["message"]


def test_show_dialog_true_still_uses_the_old_blocking_path(connected):
    """The escape hatch is preserved for whoever explicitly wants it."""
    seen = {}

    def fake_execute_action(action_string):
        seen["action"] = action_string
        return {"success": True}

    connected.execute_action = fake_execute_action
    result = json.loads(server.eplan_test(show_dialog=True))
    assert result["success"] is True
    assert seen["action"].startswith("ExecuteScript ")
