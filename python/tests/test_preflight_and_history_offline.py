"""Pre-flight dialog refusal, frozen-vs-busy awareness, and the dialog learning log.

Offline: the client is a stub whose ExecuteAction waits on an Event, and
_blocking_dialogs / _responding are monkeypatched. No EPLAN, no windows.
"""
import json
import os
import sys
import threading
import time

import pytest

import eplan_connection
import ui_windows
from eplan_connection import EPLANConnectionManager, dialog_history
from api.actions import dialogs

DIALOG = {"hwnd": 4242, "pid": 99, "title": "Project master data", "class": "#32770",
          "buttons": ["Yes", "No"], "text": ["Master data differs.", "Sync?"],
          "blocking": True, "modal": True}


class _Client:
    SynchronousMode = False

    def __init__(self):
        self.release = threading.Event()
        self.calls = []

    def ExecuteAction(self, action):
        self.calls.append(action)
        self.release.wait(10)


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(eplan_connection, "ACTION_TIMEOUT_S", 0.6)
    monkeypatch.setattr(eplan_connection, "DIALOG_CHECK_S", 0.1)
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [])
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: True)
    monkeypatch.setattr(eplan_connection, "eplan_pids", lambda: pytest.fail("no tasklist"))
    monkeypatch.setattr(eplan_connection, "pid_alive", lambda pid: pid == 99)
    m = EPLANConnectionManager()
    m.connected, m.pid, m.client = True, 99, _Client()
    yield m
    m.client.release.set()


def _events(tmp_path):
    path = tmp_path / "dialogs.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] \
        if path.exists() else []


# --- 1. pre-flight -----------------------------------------------------------

def test_preflight_refuses_without_sending(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [DIALOG])
    result = mgr.execute_action("XPrjActionProjectOpen /Project:x")
    assert mgr.client.calls == []
    assert result["errorType"] == "EplanBlockedByDialog" and "timed_out" not in result
    assert result["error"] == ("EPLAN already has dialog 'Project master data' open "
                               "(buttons: Yes, No); this call was not sent.")
    assert "button='No'" in result["next_step"] and "retry this call" in result["next_step"]
    assert mgr._inflight is None
    [seen] = _events(tmp_path)
    assert (seen["event"], seen["phase"]) == ("seen", "preflight")
    assert seen["action"] == "XPrjActionProjectOpen /Project:x"


def test_preflight_ignores_a_dialog_that_is_closing(mgr, monkeypatch):
    found = iter([[DIALOG]])
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: next(found, []))
    mgr.client.release.set()
    assert mgr.execute_action("next")["success"] is True


def test_failfast_off_skips_preflight_but_still_samples_and_records(mgr, monkeypatch, tmp_path):
    monkeypatch.setenv("EPLAN_MCP_DIALOG_FAILFAST", "0")
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [DIALOG])
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: False)
    threading.Timer(1.7, mgr.client.release.set).start()
    result = mgr.execute_action("gatedAction", timeout=5)
    assert result["success"] is True and mgr.client.calls == ["gatedAction"]
    assert result["not_responding_s"] >= 1 and "not responding" in result["hang_note"]
    events = _events(tmp_path)
    assert len(events) == 1 and events[0]["phase"] == "during"   # once per call, not per tick


# --- 2. frozen vs busy -------------------------------------------------------

def test_success_without_a_hang_has_no_extra_fields(mgr):
    mgr.client.release.set()
    result = mgr.execute_action("fast")
    assert "not_responding_s" not in result and "hang_note" not in result


def test_not_responding_is_attached_on_the_wrapped_path(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: False)
    monkeypatch.setattr(eplan_connection, "ACTION_TIMEOUT_S", 5)
    script, rp = tmp_path / "exec_action_x.cs", tmp_path / "res.json"
    script.write_text("// stub", encoding="utf-8")

    def run(action):
        time.sleep(1.4)
        rp.write_text('{"success": true}', encoding="utf-8")
    mgr.client.ExecuteAction = run
    result = mgr._run_generated_script("realAction", str(script), str(rp), time.time())
    assert result["success"] is True and result["not_responding_s"] >= 1
    assert "hang_note" in result


@pytest.mark.parametrize("responding, state, words", [
    (False, "not_responding", "frozen or computing heavily"),
    (True, "responding", "responsive but still working"),
    (None, "unknown", None),
])
def test_timeout_reports_eplan_state(mgr, monkeypatch, responding, state, words):
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: responding)
    result = mgr.execute_action("slowAction")
    assert result["errorType"] == "EplanActionTimeout" and result["eplan_state"] == state
    assert words is None or words in result["error"]


def test_busy_and_ping_report_eplan_state(mgr, monkeypatch):
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: False)
    mgr._inflight, mgr._inflight_since = "slowAction", time.monotonic()
    busy = mgr.execute_action("next")
    assert busy["eplan_state"] == "not_responding" and "Not Responding" in busy["error"]
    mgr.client.Ping = lambda: mgr.client.release.wait(10)
    ping = mgr.ping(timeout_seconds=0.1)
    assert ping["eplan_state"] == "not_responding" and "Not Responding" in ping["message"]


def test_responding_is_none_without_a_main_window(monkeypatch):
    monkeypatch.setattr(ui_windows, "_top", lambda u, pids: [])
    monkeypatch.setattr(ui_windows, "_user32", lambda: object())
    assert ui_windows.responding({1}) is None


def test_responding_is_none_when_win32_is_unavailable(monkeypatch):
    def boom():
        raise OSError("no user32")
    monkeypatch.setattr(ui_windows, "_user32", boom)
    assert ui_windows.responding({1}) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_responding_smoke_on_own_process():
    assert ui_windows.responding({os.getpid()}) is None     # python.exe has no Afx window


def test_list_dialogs_reports_eplan_state(monkeypatch):
    monkeypatch.setattr(dialogs, "_pids", lambda: {99})
    monkeypatch.setattr(dialogs.ui_windows, "list_windows", lambda pids, include_main: [])
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: False)
    assert dialogs.list_dialogs()["eplan_state"] == "not_responding"


# --- 3. dialog learning log ---------------------------------------------------

def _click(monkeypatch, button, success=True, title="Project master data"):
    monkeypatch.setattr(dialogs, "_pids", lambda: {99})
    monkeypatch.setattr(dialogs.ui_windows, "click_button",
                        lambda *a, **k: {"success": success, "closed": success})
    return dialogs.click_dialog_button(4242, button, title)


def test_clicks_are_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    _click(monkeypatch, "&No")
    [e] = _events(tmp_path)
    assert (e["event"], e["title"], e["button"], e["success"], e["allow_any"]) == \
        ("clicked", "Project master data", "No", True, False)


def test_history_aggregates_and_learns_only_past_the_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    rec = eplan_connection.record_dialog
    rec({"event": "seen", "title": "Project master data", "action": "ProjectOpen /P:x"})
    rec({"event": "seen", "title": "Project master data", "action": "ProjectOpen /P:y"})
    _click(monkeypatch, "No")
    assert dialog_history()["Project master data"]["learned_button"] is None   # 1 click
    _click(monkeypatch, "No")
    _click(monkeypatch, "Yes", success=False)          # refused clicks do not count
    row = dialogs.dialog_history("master")["dialogs"][0]
    assert row["times_seen"] == 2 and row["triggered_by"] == {"ProjectOpen": 2}
    assert row["clicks"] == {"No": 2} and row["learned_button"] == "No"
    _click(monkeypatch, "Cancel")                     # 2 of 3 = 67% < 70%
    assert dialog_history()["Project master data"]["learned_button"] is None
    assert dialogs.dialog_history("nothing like it")["count"] == 0


def test_next_step_uses_a_learned_safe_button(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    for _ in range(3):
        _click(monkeypatch, "Cancel", title="Save?")
    step = EPLANConnectionManager._dialog_next_step(
        {"hwnd": 1, "title": "Save?", "buttons": ["Yes", "No", "Cancel"]})
    assert "button='Cancel'" in step and "answered 'Cancel' 3 times before" in step


def test_next_step_never_suggests_a_learned_unsafe_button(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    for _ in range(2):
        _click(monkeypatch, "Yes", title="Save?")
    step = EPLANConnectionManager._dialog_next_step(
        {"hwnd": 1, "title": "Save?", "buttons": ["Yes", "No"]})
    assert "button='No'" in step and "button='Yes'" not in step
    assert "allow_any_button=True" in step and "'Yes' answered it 2 times" in step


def test_recorder_never_raises_on_an_unwritable_dir(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(blocker / "logs"))
    eplan_connection.record_dialog({"event": "seen", "title": "t"})
    assert dialog_history() == {}


# --- 4. review fixes ------------------------------------------------------------

def test_overlapping_call_gets_busy_instead_of_queueing(mgr):
    first = threading.Thread(target=mgr.execute_action, args=("longExport",), kwargs={"timeout": 5})
    first.start()
    time.sleep(0.2)
    started = time.monotonic()
    busy = mgr.execute_action("next")
    assert time.monotonic() - started < 1.0      # the lock wait is DIALOG_CHECK_S
    assert busy["errorType"] == "EplanBusy" and "longExport" in busy["error"]
    assert mgr.client.calls == ["longExport"]
    mgr.client.release.set()
    first.join(5)


def test_preflight_lets_a_modeless_dialog_through(mgr, monkeypatch):
    modeless = dict(DIALOG, modal=False)
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [modeless])
    mgr.client.release.set()
    assert mgr.execute_action("fast")["success"] is True


def test_retries_against_one_dialog_record_it_once(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [DIALOG])
    for _ in range(3):
        assert mgr.execute_action("retry")["errorType"] == "EplanBlockedByDialog"
    assert len(_events(tmp_path)) == 1


def test_failfast_off_timeout_names_the_dialog(mgr, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_DIALOG_FAILFAST", "0")
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [DIALOG])
    result = mgr.execute_action("gatedAction")
    assert result["errorType"] == "EplanBlockedByDialog" and result["timed_out"]
    assert result["dialogs"] == [DIALOG] and "no blocking dialog" not in result["error"]


def test_learned_answer_is_mentioned_not_substituted(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    for _ in range(2):
        _click(monkeypatch, "No", title="EPLAN")
    step = EPLANConnectionManager._dialog_next_step(
        {"hwnd": 1, "title": "EPLAN", "buttons": ["Yes", "No", "Cancel"]})
    assert "button='Cancel'" in step and "'No' answered it 2 times" in step
    assert "user confirms" in step


def test_clicks_that_did_not_close_do_not_teach(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    for _ in range(2):
        eplan_connection.record_dialog({"event": "clicked", "title": "t", "button": "OK",
                                        "success": True, "closed": False})
    assert dialog_history()["t"]["clicks"] == {}


def test_history_reads_only_appended_complete_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    eplan_connection.record_dialog({"event": "seen", "title": "t", "action": "A"})
    assert dialog_history()["t"]["times_seen"] == 1
    with open(tmp_path / "dialogs.jsonl", "a", encoding="utf-8") as f:
        f.write('{"event": "seen", "title": "t"')            # half-written
    assert dialog_history()["t"]["times_seen"] == 1
    with open(tmp_path / "dialogs.jsonl", "a", encoding="utf-8") as f:
        f.write(', "action": "B"}\n')
    assert dialog_history()["t"]["times_seen"] == 2
