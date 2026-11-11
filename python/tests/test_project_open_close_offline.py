"""Offline tests for project open/close hardening (project.py, fixtures.py,
lifecycle.app_restart). A fake manager answers selectionset with whatever
project the test says has focus, so the real pre-checks and post-open/close
verification run without EPLAN."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.actions import fixtures, lifecycle, project


class FakeEplan:
    """Records actions; ProjectOpen focuses `opens_to`, close clears focus."""

    def __init__(self, focused="", opens_to=None, close_clears=True):
        self.focused = focused
        self.opens_to = opens_to
        self.close_clears = close_clears
        self.actions = []

    def execute_action(self, action):
        self.actions.append(action)
        if action.startswith("selectionset"):
            return {"success": True, "parameters": {"PROJECT": self.focused}}
        if action.startswith("ProjectOpen"):
            self.focused = self.opens_to or ""
            return {"success": True}
        if action == "XPrjActionProjectClose":
            if self.close_clears:
                self.focused = ""
            return {"success": True}
        raise AssertionError(f"unexpected action {action}")

    def sent(self, prefix):
        return [a for a in self.actions if a.startswith(prefix)]


@pytest.fixture
def eplan(monkeypatch):
    fake = FakeEplan()
    for mod in (project, fixtures, lifecycle):
        monkeypatch.setattr(mod, "_get_connected_manager", lambda: (fake, None))
    return fake


@pytest.fixture
def elk(tmp_path):
    path = tmp_path / "Demo.elk"
    path.write_text("link")
    return str(path)


# ---------------------------------------------------------------------------
# open_project
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path, mode, needle", [
    ("missing", None, "not found"),
    ("wrong_ext", None, "expected .elk"),
    ("packed", None, "packed project archive"),
    ("ok", "Sideways", "open_mode"),
])
def test_open_prechecks_never_reach_eplan(eplan, tmp_path, elk, path, mode, needle):
    target = {"missing": str(tmp_path / "Nope.elk"),
              "wrong_ext": str(tmp_path / "Demo.txt"),
              "packed": str(tmp_path / "Demo.elp"),
              "ok": elk}[path]
    result = project.open_project(target, open_mode=mode)
    assert result["success"] is False
    assert needle in result["error"] and result["next_step"]
    assert eplan.actions == []


def test_open_accepts_write_protected_link(eplan, tmp_path):
    els = tmp_path / "Backup.els"
    els.write_text("link")
    eplan.opens_to = str(els)
    assert project.open_project(str(els))["success"] is True


def test_open_already_focused_refuses_a_different_mode(eplan, elk):
    eplan.focused = elk
    result = project.open_project(elk, open_mode="ReadOnly")
    assert result["success"] is False and "eplan_close_project" in result["next_step"]
    assert eplan.sent("ProjectOpen") == []


def test_open_eplan_exception_type_is_not_a_typed_failure(eplan, elk):
    # selectionset with no project open can throw; that is not a C2 failure.
    eplan.opens_to = elk
    real = eplan.execute_action

    def execute(a):
        if a.startswith("selectionset") and not eplan.focused:
            return {"success": False, "errorType": "Eplan.EplApi.Base.BaseException",
                    "error": "no project"}
        return real(a)
    eplan.execute_action = execute
    result = project.open_project(elk)
    assert result["success"] and result["verified"]
    assert len(eplan.sent("ProjectOpen")) == 1


def test_open_failure_with_project_already_focused_is_success(eplan, elk):
    real = eplan.execute_action

    def execute(a):
        if a.startswith("ProjectOpen"):
            eplan.focused = elk          # EPLAN refused, but it is open and now focused
            return {"success": False, "eplanMessages": ["Project is already open"]}
        return real(a)
    eplan.execute_action = execute
    result = project.open_project(elk)
    assert result["success"] and result["verified"]


def test_open_failure_without_focus_gets_a_next_step(eplan, elk):
    real = eplan.execute_action
    eplan.execute_action = lambda a: ({"success": False} if a.startswith("ProjectOpen")
                                      else real(a))
    result = project.open_project(elk)
    assert result["success"] is False and "click into it" in result["next_step"]


def test_open_mode_is_case_insensitive(eplan, elk):
    eplan.opens_to = elk
    result = project.open_project(elk, open_mode="readonly")
    assert result["success"] and result["verified"]
    assert "/OpenMode:ReadOnly" in eplan.sent("ProjectOpen")[0]


def test_open_path_variables_skip_file_checks(eplan):
    eplan.opens_to = r"C:\Projects\Demo.elk"
    result = project.open_project("$(MD_PROJECTS)\\Demo.elk")
    assert result["success"] is True
    assert "verified" not in result
    assert len(eplan.sent("ProjectOpen")) == 1


def test_open_already_focused_skips_project_open(eplan, elk):
    eplan.focused = elk
    result = project.open_project(elk)
    assert result["success"] and result["verified"]
    assert eplan.sent("ProjectOpen") == []


def test_open_success_with_wrong_focus_is_failure(eplan, elk, tmp_path):
    eplan.opens_to = str(tmp_path / "Other.elk")
    result = project.open_project(elk)
    assert result["success"] is False and result["verified"] is False
    assert "Other.elk" in result["error"] and result["next_step"]


def test_open_typed_error_passes_through_unchanged(eplan, elk):
    typed = {"success": False, "errorType": "EplanBlockedByDialog", "error": "x",
             "message": "x", "next_step": "click", "timed_out": True}
    eplan.execute_action = lambda a: (
        {"success": True, "parameters": {"PROJECT": ""}} if a.startswith("selectionset")
        else dict(typed))
    assert project.open_project(elk) == typed


# ---------------------------------------------------------------------------
# close_project
# ---------------------------------------------------------------------------

def test_close_with_nothing_open(eplan):
    result = project.close_project()
    assert result["success"] is False and result["errorType"] == "NoProjectOpen"
    assert eplan.sent("XPrjActionProjectClose") == []


def test_close_refuses_wrong_focused_project(eplan, elk, tmp_path):
    eplan.focused = str(tmp_path / "Real.elk")
    result = project.close_project(expected_project=elk)
    assert result["success"] is False and result["errorType"] == "WrongProjectFocused"
    assert "Real.elk" in result["error"]
    assert eplan.sent("XPrjActionProjectClose") == []


def test_close_verified(eplan, elk):
    eplan.focused = elk
    result = project.close_project(expected_project=elk)
    assert result["success"] and result["verified"]
    assert result["closed_project"] == elk


def _selectionset_fails(eplan, error_type):
    real = eplan.execute_action

    def execute(a):
        if a.startswith("selectionset") and (error_type != "after" or not eplan.focused):
            return {"success": False, "errorType": "Eplan.EplApi.Base.BaseException",
                    "error": "selectionset threw"}
        return real(a)
    eplan.execute_action = execute


def test_close_with_unreadable_focus_is_not_no_project(eplan, elk):
    eplan.focused = elk
    _selectionset_fails(eplan, "always")
    result = project.close_project()
    assert result["errorType"] == "FocusUnknown" and "selectionset threw" in result["error"]
    assert eplan.sent("XPrjActionProjectClose") == []


def test_close_last_project_verified_when_selectionset_then_throws(eplan, elk):
    eplan.focused = elk
    _selectionset_fails(eplan, "after")
    result = project.close_project(expected_project=elk)
    assert result["success"] and result["verified"]


def test_discard_keeps_files_when_focus_unknown(eplan, clone):
    eplan.focused = clone
    _selectionset_fails(eplan, "always")
    result = fixtures.scratch_project_discard(clone)
    assert result["success"] is False and result["errorType"] == "FocusUnknown"
    assert "close_first=False" in result["next_step"]
    assert os.path.exists(clone)


def test_discard_refuses_the_scratch_root_itself(eplan, clone, monkeypatch):
    root = fixtures.SCRATCH_ROOT
    os.mkdir(root + ".edb")                      # sibling OUTSIDE the root
    rmtree = Mock()
    monkeypatch.setattr(fixtures.shutil, "rmtree", rmtree)
    result = fixtures.scratch_project_discard(root, close_first=False)
    assert result["success"] is False and "Refusing" in result["error"]
    rmtree.assert_not_called()


def test_close_still_focused_is_failure(eplan, elk):
    eplan.focused, eplan.close_clears = elk, False
    result = project.close_project()
    assert result["success"] is False and result["verified"] is False


# ---------------------------------------------------------------------------
# _same_path
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="8.3 names are Windows-only")
def test_same_path_short_and_long_forms(tmp_path):
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    target = tmp_path / "A Long Project Name.elk"
    target.write_text("link")
    ctypes.windll.kernel32.GetShortPathNameW(str(target), buf, 1024)
    short = buf.value
    ctypes.windll.kernel32.GetLongPathNameW(str(target), buf, 1024)
    long_ = buf.value
    if short.lower() == long_.lower():
        pytest.skip("8.3 short names disabled on this volume")
    assert project._same_path(short, long_)
    assert not project._same_path(short, str(tmp_path / "Other.elk"))


# ---------------------------------------------------------------------------
# scratch_project_discard
# ---------------------------------------------------------------------------

@pytest.fixture
def clone(tmp_path, monkeypatch):
    root = tmp_path / "scratch"
    root.mkdir()
    monkeypatch.setattr(fixtures, "SCRATCH_ROOT", str(root))
    elk_path = root / "Clone.elk"
    elk_path.write_text("link")
    (root / "Clone.edb").mkdir()
    (root / "Clone.edb" / "data.bin").write_bytes(b"\x00")
    return str(elk_path)


def test_discard_keeps_files_when_close_fails(eplan, clone, tmp_path):
    eplan.focused = str(tmp_path / "Real.elk")
    result = fixtures.scratch_project_discard(clone)
    assert result["success"] is False and result["errorType"] == "WrongProjectFocused"
    assert "close_first=False" in result["next_step"]
    assert os.path.exists(clone) and os.path.isdir(clone[:-4] + ".edb")


def test_discard_closes_then_deletes_edb_first(eplan, clone, monkeypatch):
    eplan.focused = clone
    order = []
    monkeypatch.setattr(fixtures.shutil, "rmtree", lambda p, **kw: order.append(p))
    monkeypatch.setattr(fixtures.os, "remove", lambda p: order.append(p))
    result = fixtures.scratch_project_discard(clone)
    assert result["success"] is True and result["closed_in_eplan"]["verified"]
    assert [os.path.splitext(p)[1] for p in order] == [".edb", ".elk"]


def test_discard_proceeds_when_nothing_open(eplan, clone):
    result = fixtures.scratch_project_discard(clone)
    assert result["success"] is True
    assert not os.path.exists(clone)


def test_discard_retries_locked_edb_and_keeps_elk(eplan, clone, monkeypatch):
    rmtree = Mock(side_effect=PermissionError("locked"))
    monkeypatch.setattr(fixtures.shutil, "rmtree", rmtree)
    monkeypatch.setattr(fixtures.time, "sleep", lambda s: None)
    result = fixtures.scratch_project_discard(clone)
    assert result["success"] is False and result["next_step"]
    assert rmtree.call_count == 5
    assert os.path.exists(clone), ".elk must survive a failed .edb delete"


# ---------------------------------------------------------------------------
# app_restart
# ---------------------------------------------------------------------------

def test_restart_closes_before_shutdown_and_reopens(eplan, elk, monkeypatch):
    eplan.focused = elk
    eplan.opens_to = elk
    order = []
    real_execute = eplan.execute_action
    eplan.execute_action = lambda a: (order.append(a), real_execute(a))[1]
    monkeypatch.setattr(lifecycle, "app_shutdown",
                        lambda force: (order.append("shutdown"), {"success": True})[1])
    monkeypatch.setattr(lifecycle, "app_launch", Mock(return_value={"success": True}))
    result = lifecycle.app_restart()
    assert result["success"] is True
    assert order.index("XPrjActionProjectClose") < order.index("shutdown")
    assert result["steps"]["close"]["verified"]
    assert result["steps"]["reopen"]["verified"]


def test_restart_failed_close_is_not_fatal(eplan, elk, monkeypatch):
    eplan.focused, eplan.close_clears = elk, False  # close "succeeds" but focus stays
    monkeypatch.setattr(lifecycle, "app_shutdown", lambda force: {"success": True})
    monkeypatch.setattr(lifecycle, "app_launch", Mock(return_value={"success": True}))
    result = lifecycle.app_restart()
    assert result["steps"]["close"]["success"] is False
    assert result["success"] is True  # still focused after "relaunch" -> open skipped


def test_restart_stops_when_close_is_blocked_by_a_dialog(eplan, elk, monkeypatch):
    eplan.focused = elk
    real = eplan.execute_action
    eplan.execute_action = lambda a: (
        {"success": False, "errorType": "EplanBlockedByDialog", "error": "dialog",
         "next_step": "eplan_click_dialog_button(...)"}
        if a == "XPrjActionProjectClose" else real(a))
    shutdown = Mock(return_value={"success": True})
    monkeypatch.setattr(lifecycle, "app_shutdown", shutdown)
    result = lifecycle.app_restart(force=True)
    assert result["success"] is False
    assert result["next_step"] == "eplan_click_dialog_button(...)"
    shutdown.assert_not_called()


def test_restart_with_unreadable_focus_says_so(eplan, monkeypatch):
    busy = {"success": False, "errorType": "EplanBusy", "error": "busy", "next_step": "x"}
    eplan.execute_action = lambda a: dict(busy)
    monkeypatch.setattr(lifecycle, "app_shutdown", lambda force: {"success": True})
    monkeypatch.setattr(lifecycle, "app_launch", Mock(return_value={"success": True}))
    result = lifecycle.app_restart()
    assert result["steps"]["previous_project_error"]["errorType"] == "EplanBusy"
    assert "EplanBusy" in result["steps"]["reopen"]["note"]
    assert "eplan_open_project" in result["steps"]["reopen"]["note"]


def test_restart_notes_nothing_to_reopen(eplan, monkeypatch):
    monkeypatch.setattr(lifecycle, "app_shutdown", lambda force: {"success": True})
    monkeypatch.setattr(lifecycle, "app_launch", Mock(return_value={"success": True}))
    result = lifecycle.app_restart()
    assert result["success"] is True
    assert "nothing to reopen" in result["steps"]["reopen"]["note"]
    assert eplan.sent("XPrjActionProjectClose") == []
