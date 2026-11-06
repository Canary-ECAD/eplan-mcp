"""
The Data Portal tools build the add-in's actions correctly, without EPLAN.

The parameter rules were measured on EPLAN 2026.0.3 (see the module docstring):
PARTNR<i> and PARTID<i> are both required and indexes start at 1. These tests
check the script that is sent, and that a queue result always tells the
assistant to ask the user to download the list in EPLAN.

The queue action runs from a timer after the script returns, because on
2025.0.3 it opens the Data Portal window and does not return until that window
is closed. The fakes here stand in for both halves: _execute_script for the
script, and a written "done" file for the action reporting back.
"""

import json
import os
import re
import time

import pytest

import eplan_connection
from api.actions import dataportal

PART = {"part_number": "DEMO.CT-100", "dataportal_id": "11"}
EDP = {"hwnd": 501, "title": "EDP", "is_main": False, "main_disabled": True, "owner_disabled": False}


def _done_path(script):
    match = re.search(r'File\.WriteAllText\("([^"]+)\.started"', script)
    assert match, "the queue script must write a .started marker next to its result"
    return match.group(1).replace("\\\\", "\\")


def _report(script, result):
    with open(_done_path(script), "w", encoding="utf-8") as f:
        json.dump(result, f)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(dataportal, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(dataportal, "_pending", {})
    monkeypatch.setattr(eplan_connection, "WINDOW_HINTS", {})
    monkeypatch.setattr(dataportal, "QUEUE_WAIT_S", 2.0)
    monkeypatch.setattr(dataportal, "QUEUE_WINDOW_CHECK_S", 0.01)
    monkeypatch.setattr(dataportal, "_eplan_pids", lambda: {42})
    monkeypatch.setattr(dataportal, "_top_hwnds", lambda pids: {100})
    windows = []
    monkeypatch.setattr(dataportal, "_windows", lambda pids: list(windows))
    return windows


@pytest.fixture
def eplan(monkeypatch):
    """EPLAN as on 2026: the script dispatches, the action reports back at once."""
    scripts = []
    answer = {"success": True, "executed": True, "context": {"result": "7"}}

    def fake(script, timeout=30.0):
        scripts.append(script)
        if "DataPortalQueue_" in script:
            _report(script, answer)
            return {"success": True, "results": {"success": True, "dispatched": True}}
        return {"success": True, "results": dict(answer)}

    monkeypatch.setattr(dataportal, "_execute_script", fake)
    return scripts


@pytest.fixture
def eplan_2025(monkeypatch, isolated):
    """EPLAN as on 2025: the script dispatches, the action opens the EDP window
    and does not report back while it is open."""
    scripts = []

    def fake(script, timeout=30.0):
        scripts.append(script)
        isolated.append(dict(EDP))
        return {"success": True, "results": {"success": True, "dispatched": True}}

    monkeypatch.setattr(dataportal, "_execute_script", fake)
    return scripts


def test_queue_sends_numbered_part_and_id_pairs_from_one(eplan):
    result = dataportal.dataportal_add_to_download_list([
        {"part_number": "DEMO.CT-100", "dataportal_id": "11"},
        {"part_number": "DEMO.CT-200", "dataportal_id": 12},
    ])
    script = eplan[0]
    assert 'ctx.AddParameter("PARTNR1", "DEMO.CT-100");' in script
    assert 'ctx.AddParameter("PARTID1", "11");' in script
    assert 'ctx.AddParameter("PARTNR2", "DEMO.CT-200");' in script
    assert 'ctx.AddParameter("PARTID2", "12");' in script
    assert "PARTNR0" not in script
    assert "EDPCloudAddPartsToBasketAction" in script
    assert result["queued"] == ["DEMO.CT-100", "DEMO.CT-200"]
    assert result["status"] == "done"
    assert result["executed"] is True
    assert "download" in result["userAction"].lower()
    assert "DEMO.CT-200" in result["userAction"]


def test_the_queue_action_runs_from_a_timer_not_inside_the_script(eplan):
    dataportal.dataportal_add_to_download_list([PART])
    script = eplan[0]
    run, later = script.split("static void RunAction", 1)
    # Run only checks the action and starts the timer; Execute is in RunAction.
    assert "act.Execute(ctx)" not in run
    assert "act.Execute(ctx)" in later
    assert "System.Windows.Forms.Timer" in run and "timer.Start();" in run
    assert 'results["dispatched"] = true;' in run
    # C# 5: the script engine of 2026 rejects newer syntax.
    assert "?." not in script and '$"' not in script


def test_queue_reports_the_action_result_and_cleans_up(eplan, tmp_path):
    result = dataportal.dataportal_add_to_download_list([PART])
    assert result["success"] is True and result["executed"] is True
    assert not list(tmp_path.iterdir())
    assert dataportal._pending == {}


def test_queue_refuses_a_part_without_a_numeric_id(eplan):
    result = dataportal.dataportal_add_to_download_list([{"part_number": "DEMO.CT-100"}])
    assert result["success"] is False
    assert not eplan
    result = dataportal.dataportal_add_to_download_list([{"part_number": "X", "dataportal_id": "id-11"}])
    assert result["success"] is False
    assert dataportal.dataportal_add_to_download_list([])["success"] is False


def test_queue_explains_executed_false(monkeypatch):
    def fake(script, timeout=30.0):
        _report(script, {"success": True, "executed": False})
        return {"success": True, "results": {"success": True, "dispatched": True}}

    monkeypatch.setattr(dataportal, "_execute_script", fake)
    result = dataportal.dataportal_add_to_download_list([{"part_number": "A", "dataportal_id": "1"}])
    assert "already in the download list" in result["note"]
    assert result["userAction"]


def test_queue_passes_on_a_failed_script(monkeypatch):
    monkeypatch.setattr(dataportal, "_execute_script", lambda script, timeout=30.0: {
        "success": False, "error": "Action EDPCloudAddPartsToBasketAction is not available",
        "results": {"success": False, "error": "Action EDPCloudAddPartsToBasketAction is not available"}})
    result = dataportal.dataportal_add_to_download_list([PART])
    assert result["success"] is False
    assert "not available" in result["error"]
    assert dataportal._pending == {}


def test_queue_returns_quickly_when_the_dataportal_window_holds_the_action(eplan_2025):
    started = time.monotonic()
    result = dataportal.dataportal_add_to_download_list([PART])
    assert time.monotonic() - started < 1.5
    assert result["success"] is True
    assert result["status"] == "dataportal_window_open"
    assert result["executed"] is None
    assert result["dataportal_window"] == {"hwnd": 501, "title": "EDP"}
    assert result["eplanWaitsOnWindow"] is True
    assert "not known yet" in result["message"]
    assert "Do not queue them again" in result["message"]
    assert "window is open" in result["userAction"]
    assert "DEMO.CT-100" in result["userAction"]
    assert "close the window" in result["userAction"]


def test_while_the_window_is_open_a_new_request_is_not_sent(eplan_2025):
    dataportal.dataportal_add_to_download_list([PART])
    result = dataportal.dataportal_add_to_download_list([{"part_number": "DEMO.CT-200", "dataportal_id": "12"}])
    assert len(eplan_2025) == 1
    assert result["success"] is False
    assert result["errorType"] == "DataPortalWindowOpen"
    assert result["queued"] == []
    assert "DEMO.CT-100" in result["userAction"] and "DEMO.CT-200" in result["userAction"]


def test_the_next_call_reports_the_earlier_verdict(monkeypatch, eplan_2025, isolated):
    dataportal.dataportal_add_to_download_list([PART])
    # The user closes the window; the action reports back.
    isolated.clear()
    _report(eplan_2025[0], {"success": True, "executed": True, "context": {}})

    def fake(script, timeout=30.0):
        _report(script, {"success": True, "executed": True})
        return {"success": True, "results": {"success": True, "dispatched": True}}

    monkeypatch.setattr(dataportal, "_execute_script", fake)
    result = dataportal.dataportal_add_to_download_list([{"part_number": "DEMO.CT-200", "dataportal_id": "12"}])
    assert result["status"] == "done"
    assert result["earlierResults"] == [{"parts": ["DEMO.CT-100"], "success": True, "executed": True}]
    assert dataportal._pending == {}


def test_a_call_blocked_by_the_dataportal_window_says_what_to_do(eplan_2025, isolated):
    dataportal.dataportal_add_to_download_list([PART])
    step = eplan_connection.EPLANConnectionManager._dialog_next_step(
        {"hwnd": 501, "title": "EDP", "suggested_button": None})
    assert "Data Portal window" in step
    assert "DEMO.CT-100" in step
    assert "Do not click" in step
    # Another window with the same hwnd (reused) gets the generic step.
    other = eplan_connection.EPLANConnectionManager._dialog_next_step(
        {"hwnd": 501, "title": "Something else", "suggested_button": None})
    assert "Data Portal" not in other
    # Once the window is gone the hint goes too.
    isolated.clear()
    dataportal._still_open({42})
    assert eplan_connection.WINDOW_HINTS == {}


def test_result_files_left_by_a_stopped_server_are_swept(eplan, tmp_path):
    old, fresh = tmp_path / "dataportal_old.json", tmp_path / "dataportal_new.json"
    other = tmp_path / "result_keep.json"
    for f in (old, fresh, other):
        f.write_text("{}")
    a_week_ago = time.time() - 7 * 86400
    os.utime(old, (a_week_ago, a_week_ago))
    os.utime(other, (a_week_ago, a_week_ago))
    dataportal.dataportal_add_to_download_list([PART])
    assert not old.exists()
    assert fresh.exists() and other.exists()


def test_a_window_that_was_already_open_is_not_taken_for_the_dataportal(monkeypatch, isolated):
    isolated.append(dict(EDP, hwnd=100, title="Some earlier window"))
    monkeypatch.setattr(dataportal, "QUEUE_WAIT_S", 0.1)
    monkeypatch.setattr(dataportal, "_execute_script", lambda script, timeout=30.0: {
        "success": True, "results": {"success": True, "dispatched": True}})
    result = dataportal.dataportal_add_to_download_list([PART])
    assert result["status"] == "pending"
    assert result["executed"] is None
    assert result["started"] is False
    assert "not known" in result["message"]
    assert "Do not queue them again" in result["message"]


def test_part_numbers_are_escaped_for_csharp(eplan):
    dataportal.dataportal_add_to_download_list([{"part_number": 'A"); Evil(); ("', "dataportal_id": "1"}])
    assert 'ctx.AddParameter("PARTNR1", "A\\"); Evil(); (\\"");' in eplan[0]


def test_search_count_reads_the_result(eplan):
    result = dataportal.dataportal_search_count("CT-100")
    assert result["count"] == 7
    assert 'ctx.AddParameter("search", "CT-100");' in eplan[0]
    assert "EDPCloudGetSearchCountAction" in eplan[0]
