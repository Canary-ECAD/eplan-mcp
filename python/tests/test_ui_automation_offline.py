"""UI Automation front end (api/actions/ui_automation.py). Offline: PowerShell is mocked."""
import json
import os
import subprocess
import types

import pytest

from api.actions import ui_automation as ui
from eplan_mcp import ext


@pytest.fixture
def ps(monkeypatch):
    calls = []
    reply = {"stdout": '{"success": true, "watch_id": "0123456789ab"}', "rc": 0}

    def run(cmd, **kw):
        args_file = cmd[cmd.index("-ArgsFile") + 1]
        with open(args_file, encoding="utf-8") as f:
            calls.append({"cmd": cmd, "args": json.load(f), "kw": kw, "file": args_file})
        return types.SimpleNamespace(returncode=reply["rc"], stdout=reply["stdout"], stderr="")
    monkeypatch.setattr(ui.subprocess, "run", run)
    monkeypatch.setattr(ui, "_DIALOG_PRESETS", {})
    return calls, reply


def test_driver_script_ships_with_the_server():
    assert os.path.isfile(ui.DRIVER_PS1)
    with open(ui.DRIVER_PS1, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"   # Windows PowerShell 5.1 reads BOM-less as ANSI


def test_unknown_op_is_refused_without_spawning(ps):
    r = ui.ui_drive("explode")
    assert not r["success"] and "list_windows" in r["error"] and not ps[0]


def test_drive_passes_args_through_a_file(ps):
    calls, reply = ps
    reply["stdout"] = '{"success": true, "count": 0, "windows": []}'
    r = ui.ui_drive("list_windows", {"title_regex": "^A & B$"})
    assert r["success"] and r["op"] == "list_windows"
    assert calls[0]["args"] == {"title_regex": "^A & B$", "process": "EPLAN"}
    assert calls[0]["cmd"][calls[0]["cmd"].index("-File") + 1] == ui.DRIVER_PS1
    assert calls[0]["kw"]["encoding"] == "utf-8"
    assert not os.path.exists(calls[0]["file"])      # the per-call args file is deleted


def test_window_lookups_default_to_eplan(ps):
    calls, _ = ps
    ui.ui_drive("list_windows", {"process": ""})               # explicit: every process
    assert calls[-1]["args"] == {"process": ""}
    ui.ui_drive("click", {"window": {"title_regex": "^Save$"}, "selector": {}})
    assert calls[-1]["args"]["window"] == {"title_regex": "^Save$", "process": "EPLAN"}
    ui.ui_drive("click", {"window": "Save as", "selector": {}})
    assert calls[-1]["args"]["window"]["process"] == "EPLAN"
    ui.ui_drive("click", {"window": {"hwnd": 5}, "selector": {}})
    assert calls[-1]["args"]["window"] == {"hwnd": 5}
    ui.ui_drive("dump", {"window": "123"})
    assert calls[-1]["args"]["window"] == "123"


def test_non_json_output_is_reported_not_raised(ps):
    ps[1]["stdout"] = "garbage"
    r = ui.ui_drive("dump", {"window": {"hwnd": 1}})
    assert not r["success"] and "non-JSON" in r["error"]


def test_host_timeout_is_reported(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(ui.subprocess, "run", boom)
    r = ui.ui_drive("list_windows", timeout_s=1)
    assert not r["success"] and "host timeout" in r["error"]


def test_watch_start_puts_caller_rules_before_the_preset(ps):
    calls, _ = ps
    ext.register_dialog_preset("p", [{"title_regex": "^X$", "button_name": "^OK$"}])
    mine = {"title_regex": "^X$", "button_name": "^Cancel$"}
    r = ui.ui_dismiss_watch_start(rules=[mine], preset="p", timeout_s=30)
    assert r["success"]
    sent = calls[0]["args"]
    assert sent["mode"] == "start" and sent["timeout_s"] == 30
    assert sent["rules"][0] == dict(mine, process="EPLAN") and sent["rules"][1]["button_name"] == "^OK$"


def test_watch_start_validates(ps):
    assert "unknown preset" in ui.ui_dismiss_watch_start(preset="none")["error"]
    assert "rules is required" in ui.ui_dismiss_watch_start()["error"]
    assert "title_regex" in ui.ui_dismiss_watch_start(rules=[{"title_regex": "x"}])["error"]
    with pytest.raises(ValueError):
        ext.register_dialog_preset("bad", [{"button_name": "OK"}])
    assert not ps[0]


def test_watch_stop(ps):
    calls, _ = ps
    for bad in ("", "abc", "0123456789AB", "0123456789ab'; rm", None):
        assert "12 lowercase hex" in ui.ui_dismiss_watch_stop(bad)["error"]
    assert not calls
    ui.ui_dismiss_watch_stop("0123456789ab", status_only=True)
    assert calls[-1]["args"] == {"mode": "status", "watch_id": "0123456789ab"}
    ui.ui_dismiss_watch_stop("0123456789ab")
    assert calls[-1]["args"]["mode"] == "stop"


def test_ui_drive_is_not_marked_read_only():
    from tool_annotations import annotate
    annotations, _ = annotate("eplan_ui_drive", ui.ui_drive)
    assert annotations.readOnlyHint is False and annotations.destructiveHint is True


def test_watch_id_is_checked_through_ui_drive_too(ps):
    calls, _ = ps
    r = ui.ui_drive("dismiss_watch", {"mode": "stop", "watch_id": "..\\x"})
    assert not r["success"] and "12 lowercase hex" in r["error"] and not calls
