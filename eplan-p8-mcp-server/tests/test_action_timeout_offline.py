"""ExecuteAction is bounded: by a deadline, and by a dialog EPLAN stops at.

Before this, a modal prompt inside an action blocked client.ExecuteAction - and
with it the whole MCP server - until a human answered it. Now the call returns
a typed failure (EplanBlockedByDialog / EplanActionTimeout / EplanBusy) with a
next_step, and a call EPLAN is still stuck in costs one thread, not one per
retry.

Offline: a fake remoting client, and the Win32 window reads replaced.
"""
import threading
import time

import pytest

import eplan_connection as ec
from eplan_connection import EPLANConnectionManager


class FakeClient:
    """ExecuteAction / Ping block until `release` is set (when `block`)."""

    def __init__(self, block=False, error=None):
        self.block = block
        self.error = error
        self.release = threading.Event()
        self.calls = []
        self.SynchronousMode = False

    def ExecuteAction(self, action):
        self.calls.append(action)
        if self.error:
            raise self.error
        if self.block:
            self.release.wait(10)

    def Ping(self):
        if self.block:
            self.release.wait(10)
        return True


DIALOG = {"hwnd": 4242, "pid": 100, "title": "Projekt-Stammdaten", "class": "#32770",
          "enabled": True, "is_main": False, "blocking": True,
          "buttons": [{"text": "Ja", "id": 6, "safe": False},
                      {"text": "Nein", "id": 7, "safe": True}],
          "text": ["Stammdaten abgleichen?"], "has_progress": False,
          "suggested_button": "Nein"}


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("EPLAN_MCP_ACTION_TIMEOUT", "5")
    monkeypatch.setattr(ec, "DIALOG_CHECK_S", 0.05)
    monkeypatch.setattr(ec, "eplan_pids", lambda: [100])
    monkeypatch.setattr(ec, "_top_hwnds", lambda pids: set())
    monkeypatch.setattr(ec, "_list_windows", lambda pids, new_since=None: [])
    monkeypatch.setattr(ec, "eplan_state", lambda pids: "responding")
    m = EPLANConnectionManager()
    m.connected = True
    m.host = "localhost"
    m.pid = 100
    clients = []

    def use(client):
        m.client = client
        clients.append(client)
        return m

    yield use
    for c in clients:
        c.release.set()


def test_a_completed_call_succeeds_as_before(manager):
    m = manager(FakeClient())
    result = m.execute_action("XPrjActionProjectClose")
    assert result["success"] is True
    assert m.client.SynchronousMode is True


def test_an_eplan_exception_still_reports_as_a_failure(manager):
    m = manager(FakeClient(error=RuntimeError("boom")))
    result = m.execute_action("XPrjActionProjectClose")
    assert result["success"] is False
    assert "boom" in result["message"]


def test_a_dialog_ends_the_call_with_a_typed_failure(manager, monkeypatch):
    monkeypatch.setattr(ec, "_list_windows", lambda pids, new_since=None: [DIALOG])
    m = manager(FakeClient(block=True))
    start = time.monotonic()
    result = m.execute_action("XPrjActionProjectOpen")
    assert time.monotonic() - start < 3, "should not wait for the deadline"
    assert result["success"] is False
    assert result["errorType"] == "EplanBlockedByDialog"
    assert result["timed_out"] is True
    assert result["dialogs"][0]["title"] == "Projekt-Stammdaten"
    # The suggestion names the safe button in EPLAN's own language.
    assert "button='Nein'" in result["next_step"]
    assert "window_title='Projekt-Stammdaten'" in result["next_step"]


def test_a_dialog_has_to_be_seen_twice(manager, monkeypatch):
    """One that flashes up and closes again must not end the call."""
    seen = {"n": 0}

    def flash(pids, new_since=None):
        seen["n"] += 1
        return [DIALOG] if seen["n"] == 1 else []

    monkeypatch.setattr(ec, "_list_windows", flash)
    client = FakeClient(block=True)
    m = manager(client)
    threading.Timer(0.4, client.release.set).start()
    result = m.execute_action("XPrjActionProjectOpen")
    assert result["success"] is True


def test_no_dialog_means_the_deadline_applies(manager, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_ACTION_TIMEOUT", "0.3")
    m = manager(FakeClient(block=True))
    result = m.execute_action("XPrjActionProjectOpen")
    assert result["errorType"] == "EplanActionTimeout"
    assert result["timed_out"] is True
    assert result["eplan_state"] == "responding"
    assert "EPLAN_MCP_ACTION_TIMEOUT" in result["next_step"]


def test_while_a_call_is_stuck_later_calls_are_not_sent(manager, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_ACTION_TIMEOUT", "0.3")
    client = FakeClient(block=True)
    m = manager(client)
    m.execute_action("XPrjActionProjectOpen")
    threads = threading.active_count()

    result = m.execute_action("XPrjActionProjectClose")
    assert result["errorType"] == "EplanBusy"
    assert result["in_flight_action"] == "XPrjActionProjectOpen"
    assert client.calls == ["XPrjActionProjectOpen"], "the second call reached EPLAN"
    assert threading.active_count() == threads, "a retry must not add a thread"

    ping = m.ping()
    assert ping["alive"] is False and ping["errorType"] == "EplanBusy"

    # Once EPLAN finishes the abandoned call, calls go through again.
    client.block = False
    client.release.set()
    deadline = time.monotonic() + 3
    while m._stuck["thread"].is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert m.execute_action("XPrjActionProjectClose")["success"] is True
    assert m._stuck is None


def test_a_timed_out_ping_lists_the_dialog(manager, monkeypatch):
    monkeypatch.setattr(ec, "_list_windows", lambda pids, new_since=None: [DIALOG])
    m = manager(FakeClient(block=True))
    result = m.ping(timeout_seconds=0.2)
    assert result["timed_out"] is True
    assert result["dialogs"][0]["hwnd"] == 4242
    assert "eplan_click_dialog_button" in result["next_step"]


def test_the_scripted_path_passes_the_typed_failure_on(manager, monkeypatch):
    monkeypatch.setattr(ec, "_list_windows", lambda pids, new_since=None: [DIALOG])
    monkeypatch.setattr(ec, "prepare_script", lambda content, version: content)
    m = manager(FakeClient(block=True))
    result = m.execute_action('XPrjActionProjectOpen /Project:"C:\\p.elk"', quiet_mode=True)
    assert result["errorType"] == "EplanBlockedByDialog"
    assert result["action"].startswith("XPrjActionProjectOpen"), \
        "reported under the wrapped action, not ExecuteScript"
    assert "executor" not in result


def test_typed_failures_only_use_declared_fields(manager, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_ACTION_TIMEOUT", "0.2")
    m = manager(FakeClient(block=True))
    timeout = m.execute_action("A")
    busy = m.execute_action("B")
    declared = set(ec.RESULT_FIELD_NAMES)
    for result in (timeout, busy):
        assert set(result) <= declared, set(result) - declared


@pytest.mark.parametrize("raw, expected", [
    (None, 600.0), ("", 600.0), ("120", 120.0), ("2.5", 2.5),
    ("ten minutes", 600.0), ("0", 600.0), ("-5", 600.0),
])
def test_a_bad_timeout_setting_never_stops_the_server(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("EPLAN_MCP_ACTION_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("EPLAN_MCP_ACTION_TIMEOUT", raw)
    assert ec.action_timeout_s() == expected


def test_a_remote_connection_scans_no_local_windows(manager):
    m = manager(FakeClient())
    m.host = "10.0.0.5"
    assert m._watch_pids() == set()


def test_a_stale_pid_is_not_watched(manager, monkeypatch):
    m = manager(FakeClient())
    m.pid = 999                     # EPLAN restarted outside the MCP
    assert m._watch_pids() == {100}
