"""
See and answer EPLAN's dialogs without going through EPLAN.

A modal prompt blocks every remoting call, so eplan_ping and
eplan_get_system_messages cannot report it. These two tools read the windows
straight from Windows instead, so they work while EPLAN is blocked and even
without a connection (they then look at every local EPLAN.exe).

Idea from the DGR-Engineering fork (api/actions/dialogs.py there); safe
buttons are recognised in any language (see ui_windows).
"""

import ui_windows
from eplan_connection import get_manager, eplan_pids, eplan_state


def _pids():
    """The connected EPLAN's PID when known and running, else every local EPLAN.exe.
    Empty for a remote connection: its windows are not on this machine."""
    manager = get_manager()
    if manager.connected:
        return manager._watch_pids()
    return set(eplan_pids())


def list_dialogs(include_main: bool = False) -> dict:
    """
    List EPLAN's open windows and dialogs, read from Windows (never waits on EPLAN).

    Use this when a call returns errorType EplanBlockedByDialog, EplanBusy or
    EplanActionTimeout, or eplan_ping times out: it shows the prompt EPLAN is
    waiting on. Works without a connection.

    Args:
        include_main: Also list EPLAN's main window (default False).

    Returns:
        windows: one per visible window - hwnd, pid, title, class, enabled,
            buttons [{text, id, safe}], text (the prompt's lines),
            has_progress, blocking (EPLAN is waiting on it) and
            suggested_button (least committal safe button, on blocking ones).
        blocking_count: how many windows EPLAN is waiting on.
        eplan_state: "not_responding" when Windows flags EPLAN Not Responding
            (frozen, or a heavy computation that may still finish),
            "responding", or "unknown".
        Answer one with eplan_click_dialog_button(hwnd, button, window_title).
    """
    pids = _pids()
    if not pids:
        return {"success": False, "errorType": "EplanNotFound",
                "error": "No local EPLAN.exe is running (or the connection is to "
                         "another machine, whose windows cannot be read from here).",
                "windows": []}
    windows = ui_windows.list_windows(pids, include_main=include_main)
    return {"success": True, "count": len(windows), "windows": windows,
            "blocking_count": sum(1 for w in windows if w["blocking"]),
            "eplan_state": eplan_state(pids)}


def click_dialog_button(hwnd: int, button: str, window_title: str,
                        allow_any_button: bool = False) -> dict:
    """
    Press one button on an EPLAN dialog, after checking it is still the same window.

    Take hwnd, the title and the button text from eplan_list_dialogs. The click is
    refused if the window has closed, changed title or is not EPLAN's. By
    default only safe buttons are pressed - OK, Cancel, Close, No or Skip, in
    any language (buttons with safe=true in eplan_list_dialogs).

    The interrupted EPLAN call's result is unknown: check the state afterwards
    (for example eplan_get_current_project) before carrying on.

    Args:
        hwnd: Window handle from eplan_list_dialogs.
        button: Button text as listed (case and the '&' marker are ignored).
        window_title: The window's title exactly as listed.
        allow_any_button: Allow a button that is not safe (for example Yes or
            Save). Only when the user asked for that button.

    Returns:
        success, hwnd, title, button, closed (the window went away within
        2 s). On refusal: errorType DialogNotFound, ButtonNotFound or
        ButtonNotAllowed, with error and next_step.
    """
    return ui_windows.click_button(hwnd, button, window_title, _pids(),
                                   allow_any=bool(allow_any_button))
