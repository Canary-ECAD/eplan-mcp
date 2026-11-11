"""New-window detection during a call, learned titles, and owner-disabled modals.

Offline: the client is a stub, _eplan_windows / _blocking_dialogs / ui_windows._enum
are faked. No EPLAN, no windows.
"""
import json
import threading

import pytest

import eplan_connection
import ui_windows
from eplan_connection import EPLANConnectionManager

_REAL_BLOCKING = eplan_connection._blocking_dialogs
PICKER = {"hwnd": 777, "pid": 99, "title": "Create Rotated Variant Dialog",
          "class": "WindowsForms10.Window.8.app", "owner": 1, "enabled": True,
          "is_main": False, "buttons": ["OK", "Cancel"], "text": [], "has_progress": False,
          "blocking": False, "modal": False, "owner_disabled": True, "foreground": False}


class _Client:
    SynchronousMode = False

    def __init__(self, on_send=None):
        self.release = threading.Event()
        self.on_send = on_send

    def ExecuteAction(self, action):
        if self.on_send:
            self.on_send()
        self.release.wait(10)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("EPLAN_MCP_NEW_WINDOW_GRACE", "0.3")
    monkeypatch.setattr(eplan_connection, "ACTION_TIMEOUT_S", 3)
    monkeypatch.setattr(eplan_connection, "DIALOG_CHECK_S", 0.1)
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", lambda pids, windows=None: [])
    monkeypatch.setattr(eplan_connection, "_responding", lambda pids: True)
    monkeypatch.setattr(eplan_connection, "pid_alive", lambda pid: pid == 99)
    state = {"windows": []}
    monkeypatch.setattr(eplan_connection, "_eplan_windows",
                        lambda pids, full=False, new_since=None: list(state["windows"]))
    monkeypatch.setattr(eplan_connection, "_eplan_hwnds",
                        lambda pids: {w["hwnd"] for w in state["windows"]})
    m = EPLANConnectionManager()
    m.connected, m.pid = True, 99
    m.client = _Client(lambda: state.update(windows=[PICKER]))
    state["mgr"] = m
    yield state
    m.client.release.set()


def _events(tmp_path):
    path = tmp_path / "dialogs.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] \
        if path.exists() else []


def _finish_after(env, s):
    threading.Timer(s, env["mgr"].client.release.set).start()


def test_new_window_past_grace_aborts_as_suspected(env, tmp_path):
    result = env["mgr"].execute_action("XSymbolActionCreateVariant")
    assert result["errorType"] == "EplanBlockedByDialog" and result["timed_out"]
    assert result["error"] == (
        "A new EPLAN window 'Create Rotated Variant Dialog' (buttons: OK, Cancel) appeared "
        "0s into the action and is still open; EPLAN has not finished, so it is probably "
        "waiting on it.")
    assert "button='Cancel'" in result["next_step"]
    assert "EPLAN_MCP_NEW_WINDOW_GRACE" in result["next_step"]
    assert result["dialogs"][0]["suspected"] is True
    [seen] = _events(tmp_path)
    assert (seen["event"], seen["phase"], seen["title"]) == (
        "suspected", "new_window", PICKER["title"])
    # A suspect is not a sighting: it must not teach the fast path.
    assert eplan_connection.dialog_history()[PICKER["title"]]["times_seen"] == 0


def test_window_open_before_the_call_is_ignored(env):
    env["windows"] = [PICKER]
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True


def test_window_that_closes_before_grace_is_ignored(env):
    threading.Timer(0.15, lambda: env.update(windows=[])).start()
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True


def test_progress_box_is_ignored(env):
    box = {**PICKER, "title": "Generating", "buttons": ["Cancel"], "has_progress": True}
    env["mgr"].client.on_send = lambda: env.update(windows=[box])
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True


def test_failfast_off_never_aborts_but_records(env, monkeypatch, tmp_path):
    monkeypatch.setenv("EPLAN_MCP_DIALOG_FAILFAST", "0")
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True
    assert [e["phase"] for e in _events(tmp_path)] == ["new_window"]


def test_grace_env_controls_the_wait(env, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_NEW_WINDOW_GRACE", "5")
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True


def _history(tmp_path, title, clicks=2):
    with open(tmp_path / "dialogs.jsonl", "w", encoding="utf-8") as f:
        for e in [{"event": "seen", "phase": "during", "title": title}] + [
                {"event": "clicked", "title": title, "button": "Cancel",
                 "success": True, "closed": True}] * clicks:
            f.write(json.dumps(e) + "\n")


def test_learned_title_takes_the_fast_path(env, monkeypatch, tmp_path):
    monkeypatch.delenv("EPLAN_MCP_NEW_WINDOW_GRACE")      # 20s: grace cannot fire
    _history(tmp_path, PICKER["title"])
    result = env["mgr"].execute_action("x")
    assert result["error"].startswith("EPLAN is waiting on dialog 'Create Rotated Variant")
    assert "suspected" not in result["dialogs"][0]


@pytest.mark.parametrize("window, clicks", [
    ({}, 1),                                                # one dismissal teaches nothing
    ({"title": ""}, 2),                                     # untitled is never learned
    ({"buttons": ["Cancel"], "has_progress": True}, 2),     # a progress box never blocks
])
def test_not_learned_stays_off_the_fast_path(env, monkeypatch, tmp_path, window, clicks):
    monkeypatch.delenv("EPLAN_MCP_NEW_WINDOW_GRACE")
    w = {**PICKER, **window}
    _history(tmp_path, w["title"], clicks)
    env["mgr"].client.on_send = lambda: env.update(windows=[w])
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True


def test_status_form_is_not_suspected(env):
    # Form.Show(): owner stays enabled, not in the foreground, EPLAN keeps working.
    form = {**PICKER, "title": "Processing 12/340", "owner_disabled": False}
    env["mgr"].client.on_send = lambda: env.update(windows=[form])
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True


def test_foreground_window_is_suspected(env):
    fg = {**PICKER, "owner_disabled": False, "foreground": True}
    env["mgr"].client.on_send = lambda: env.update(windows=[fg])
    assert env["mgr"].execute_action("x")["dialogs"][0]["suspected"] is True


def test_window_reported_blocking_is_not_reported_again(env, monkeypatch, tmp_path):
    hits = iter([[], [PICKER]])                  # preflight, then one in-call tick
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs",
                        lambda pids, windows=None: next(hits, []))
    _finish_after(env, 0.8)
    assert env["mgr"].execute_action("x")["success"] is True
    assert [e["phase"] for e in _events(tmp_path)] == ["during"]


def test_grace_survives_a_disabled_tick(env):
    state = {"pids": {99}, "before": set(), "new": {}, "decided": set(), "full": {},
             "start": 0.0}
    env["mgr"]._new_windows(state, [PICKER], [], 1.0, "x")
    env["mgr"]._new_windows(state, [{**PICKER, "enabled": False}], [], 1.1, "x")
    assert state["new"][777] == 1.0


def test_hidden_owner_disabled_makes_it_modal(monkeypatch):
    class U:
        IsWindow = staticmethod(lambda h: h == 42)
        IsWindowEnabled = staticmethod(lambda h: False)
        GetForegroundWindow = staticmethod(lambda: 0)
    monkeypatch.setattr(ui_windows, "_user32", lambda: U)
    monkeypatch.setattr(ui_windows, "_enum", lambda pids, *a: [
        {"hwnd": 9, "pid": 99, "title": "Prompt", "class": "#32770", "owner": 42,
         "enabled": True, "children": [(5, "Button", "OK")]}])
    (w,) = ui_windows.list_windows({99})
    assert w["owner_disabled"] is True and w["modal"] is True


def test_owner_disabled_modal_refuses_preflight(env, monkeypatch):
    # Live 2026-10-10: "Open project" (#32770) owned by a floating BCGPMiniFrame;
    # the owner was disabled, the main window stayed enabled.
    def raw(hwnd, cls, enabled, owner=0, children=()):
        return {"hwnd": hwnd, "pid": 99, "title": "Open project" if cls == "#32770" else "",
                "class": cls, "owner": owner, "enabled": enabled, "children": list(children)}
    monkeypatch.setattr(ui_windows, "_enum", lambda pids, *a: [
        raw(1, "AfxMDIFrame140u", True),
        raw(7, "BCGPMiniFrame:400000:8", False),
        raw(9, "#32770", True, owner=7, children=((5, "Button", "&Open"), (6, "Button", "Cancel")))])
    (w,) = [w for w in ui_windows.list_windows({99}) if w["class"] == "#32770"]
    assert w["modal"] is True
    monkeypatch.setattr(eplan_connection, "_blocking_dialogs", _REAL_BLOCKING)
    result = env["mgr"].execute_action("XPrjActionProjectOpen")
    assert result["errorType"] == "EplanBlockedByDialog" and "timed_out" not in result
    assert "'Open project'" in result["error"] and "not sent" in result["error"]
