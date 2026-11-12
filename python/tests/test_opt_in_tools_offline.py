"""Tools that act outside project data are off unless a person lists them in EPLAN_MCP_ENABLE_TOOLS."""

import asyncio

import pytest

import server

CLEANUP = ("eplan_ui_dismiss_watch_stop", "eplan_scratch_symbols_restore",
           "eplan_scratch_symbols_purge", "eplan_scratch_symbols_status")


def _published(mode, monkeypatch, env):
    monkeypatch.setenv(server.OPT_IN_ENV, env)
    monkeypatch.delenv("EPLAN_MCP_EXTENSIONS", raising=False)
    app, registry, _ = server.build_app(mode)
    return {t.name for t in asyncio.run(app.list_tools())}, registry


def test_off_by_default_and_cleanup_stays(monkeypatch):
    names, registry = _published("full", monkeypatch, "")
    for tool in server.OPT_IN_TOOLS:
        assert tool not in names and tool not in registry
    for tool in CLEANUP:
        assert tool in names


def test_discovery_mode_cannot_call_a_disabled_tool(monkeypatch):
    _, registry = _published("discovery", monkeypatch, "")
    assert "eplan_ui_drive" not in registry
    assert registry.call("eplan_ui_drive", {"op": "list_windows"}).get("success") is not True


@pytest.mark.parametrize("env,on", [
    ("eplan_ui_drive", {"eplan_ui_drive"}),
    (" EPLAN_UI_DRIVE , eplan_addin_build ", {"eplan_ui_drive", "eplan_addin_build"}),
    ("all", set(server.OPT_IN_TOOLS)),
])
def test_listed_tools_come_back(monkeypatch, env, on):
    names, _ = _published("full", monkeypatch, env)
    assert {t for t in server.OPT_IN_TOOLS if t in names} == on
    assert set(server.disabled_opt_in_tools(env)) == set(server.OPT_IN_TOOLS) - on


def test_every_opt_in_tool_exists(monkeypatch):
    names, _ = _published("full", monkeypatch, "all")
    assert set(server.OPT_IN_TOOLS) <= names
