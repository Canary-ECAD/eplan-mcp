"""
UI Automation for EPLAN and add-in WinForms dialogs, driven out of process.

Thin Python front end over scripts/UiDrive.ps1, a PowerShell UIA driver:

    ui_drive               - the general entry point (op + args -> JSON)
    ui_dismiss_watch_start - arm a background modal dismisser
    ui_dismiss_watch_stop  - stop it and read what it clicked

WHY IT SHELLS OUT. A MODAL dialog blocks eplan_execute_raw_action, so whoever awaits the action
cannot also drive the dialog. Every call here is a separate OS process, which is what makes the
arm-then-invoke pattern work:

    1. ui_dismiss_watch_start(rules=[...])   <- BEFORE, always
    2. eplan_execute_raw_action("...")       <- blocks until the dialog is dismissed
    3. ui_dismiss_watch_stop(watch_id)       <- read the evidence

Arming AFTER the invoke never gets a turn. For a MODELESS dialog the action returns at once and
ui_drive("wait_window", ...) afterwards is enough.

Dialog presets (named rule sets) come from extensions via eplan_mcp.ext.register_dialog_preset;
this module ships none.
"""

import json
import os
import re
import subprocess
import tempfile
import uuid

DRIVER_PS1 = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts", "UiDrive.ps1")

OPS = ("list_windows", "wait_window", "dump", "set", "type", "click", "read",
       "grid", "dismiss_watch", "main_window", "keys", "right_click")

# name -> [{"title_regex", "button_name", ...}]
_DIALOG_PRESETS = {}

# Window lookups are limited to EPLAN's own process unless the caller names another ("" = any).
DEFAULT_PROCESS = "EPLAN"

# UiDrive.ps1 makes watch ids as [guid]::NewGuid().ToString('N').Substring(0, 12).
_WATCH_ID = re.compile(r"[0-9a-f]{12}")


def _scope_to_eplan(op: str, payload: dict) -> dict:
    """Default the process filter to EPLAN wherever the caller set none, so a title regex never
    matches (and clicks in) another application's window. An hwnd or pid is already exact."""
    payload = dict(payload)
    if op in ("list_windows", "wait_window"):
        payload.setdefault("process", DEFAULT_PROCESS)
    window = payload.get("window")
    if isinstance(window, str) and not re.fullmatch(r"\s*\d+(\.\d+)?\s*", window):
        # A bare caption, as UiDrive.ps1 would read it (escaped, so matched literally).
        window = {"title_regex": re.escape(window)}
    if isinstance(window, dict) and not window.get("hwnd") and not window.get("pid"):
        window = dict(window)
        window.setdefault("process", DEFAULT_PROCESS)
    if window is not None:
        payload["window"] = window
    return payload


def _check_rules(rules):
    for r in rules:
        if not isinstance(r, dict) or "title_regex" not in r or "button_name" not in r:
            return "Each rule needs both title_regex and button_name; got %r" % (r,)
    return None


def register_preset(name: str, rules: list) -> None:
    """Register (or replace) a named dismiss-watch rule set."""
    rules = list(rules or [])
    err = _check_rules(rules)
    if err:
        raise ValueError(err)
    _DIALOG_PRESETS[name] = rules


def _args_path(payload: dict) -> str:
    """Write op arguments to a UTF-8 file. A file, not -ArgsJson: powershell.exe splits its own
    command line before the param binder runs, so inline JSON with a space arrives truncated."""
    d = os.path.join(tempfile.gettempdir(), "eplan_ui_args")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "args_%s.json" % uuid.uuid4().hex[:10])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload or {}, f)
    return p


def _run(op: str, payload: dict, timeout: float, driver: str = None) -> dict:
    driver = driver or DRIVER_PS1
    if "watch_id" in payload and not (isinstance(payload["watch_id"], str)
                                      and _WATCH_ID.fullmatch(payload["watch_id"])):
        # It becomes part of file paths in UiDrive.ps1: every entry point is checked here.
        return {"success": False, "op": op,
                "error": "watch_id must be the 12 lowercase hex characters "
                         "ui_dismiss_watch_start returned; got %r" % (payload["watch_id"],)}
    if not os.path.exists(driver):
        return {"success": False, "error": "Driver not found: %s" % driver}
    argf = _args_path(payload)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", driver, "-Op", op, "-ArgsFile", argf]
    try:
        return _call(op, cmd, timeout)
    finally:
        try:
            os.remove(argf)
        except OSError:
            pass


def _call(op: str, cmd: list, timeout: float) -> dict:
    try:
        # encoding/errors are load-bearing: captions carry Unicode the cp1252 default reader
        # raises on, which kills the capture thread and hands back stdout=None.
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "op": op,
                "error": "Driver exceeded the host timeout of %ss. Every driver op is itself "
                         "bounded - a host-level timeout means the PowerShell process hung, not "
                         "that a wait elapsed." % timeout}
    except Exception as e:
        return {"success": False, "op": op, "error": str(e)}

    out = (proc.stdout or "").strip()
    try:
        result = json.loads(out) if out else {}
    except Exception as e:
        return {"success": False, "op": op, "error": "Driver emitted non-JSON: %s" % e,
                "exit_code": proc.returncode, "stdout": out[-2000:],
                "stderr": (proc.stderr or "")[-2000:]}
    if not isinstance(result, dict):
        return {"success": False, "op": op,
                "error": "Driver emitted a %s, not an object" % type(result).__name__,
                "stdout": out[-2000:]}
    result.setdefault("success", False)
    result.setdefault("op", op)
    if not result.get("success"):
        if proc.stderr:
            result.setdefault("stderr", proc.stderr[-1500:])
    return result


def ui_drive(op: str, args: dict = None, timeout_s: float = 180) -> dict:
    """
    Drive a WinForms dialog (EPLAN's or an add-in's) via UI Automation, out of process.
    May click, type and send keys - it is not read-only. Always returns a dict with "success".

    OPS AND THEIR args:

      list_windows  {title_regex?, process?, include_invisible?}
          -> {count, windows:[{hwnd,title,class,pid,process,enabled,topmost,owned}]}
          Discovery, and the way to assert the NEGATIVE (no dialog appeared).

      wait_window   {title_regex, timeout_s?=20, poll_ms?=200, process?, class_regex?, raise?=true}
          -> {hwnd, runtime_id, title, class, pid, enabled, topmost, owned, rect, waited_s}
          On timeout: {success:false, timed_out:true, visible_titles:[...]}.

      dump          {window, max_nodes?=800}
          -> {window, node_count, truncated, controls:[{depth,control_type,name,automation_id,
              class,value,enabled,is_offscreen,keyboard_focusable,rect,patterns,runtime_id}]}
          BUILD EVERY SELECTOR FROM A DUMP. Do not guess names.

      set           {window, selector, value}   -> ValuePattern.SetValue (no keystrokes)
      type          {window, selector, text, raw?=false, clear_first?=true, per_key_ms?=0}
                                                -> REAL KEYSTROKES
      click         {window, selector, allow_disabled?=false, settle_ms?=200}
                    (CheckBoxes fall through to TogglePattern)
      read          {window, selector}          -> {name, text, value, control}; assert on "text"
      grid          {window, selector?}         -> {headers, rows, row_count}
      main_window   {process?="EPLAN", class_regex?="^Afx", force_enable?=false}
      right_click   {window, fx?=0.5, fy?=0.5, settle_ms?=500}  real mouse right-click
      keys          {window, keys, raw?=true, settle_ms?=300}
          Window-level keystrokes with no control selector - the way to reach EPLAN's GED page
          view, which rejects SetFocus.

    WINDOW SPEC: {"hwnd": 12345} (stable, preferred) or
      {"title_regex": "...", "class_regex"?: "...", "pid"?: N, "process"?: "..."}.
      Lookups start at the desktop root, so owner-less dialogs behind EPLAN are found.

    PROCESS SCOPE: list_windows, wait_window and every window spec without hwnd or pid match
      only EPLAN's own windows (process "EPLAN") unless args set "process" - another process
      name, or "" for every process. Keep that in mind when list_windows asserts "no dialog".

    SELECTOR: {"by": "automationId"|"name"|"class"|"index", "value": "...", "type"?: "Button"|...}
      "value" is a REGEX - anchor it (^...$) or "Close" also matches "Close All".

    EPLAN's ribbon is not exposed to UIA: dispatch the action with eplan_execute_raw_action and
    drive the dialog it opens.

    Args:
        op: One of list_windows, wait_window, dump, set, type, click, read, grid, dismiss_watch,
            main_window, keys, right_click.
        args: Op arguments (see above).
        timeout_s: Host-side ceiling on the PowerShell process. Keep it above any timeout_s
            inside args.
    """
    if op not in OPS:
        return {"success": False,
                "error": "Unknown op %r. Choose from: %s" % (op, ", ".join(OPS))}
    return _run(op, _scope_to_eplan(op, args or {}), timeout_s)


def ui_dismiss_watch_start(rules: list = None, timeout_s: float = 300,
                           preset: str = None) -> dict:
    """
    Arm a background watcher that clicks a named button when a matching window appears. ARM IT
    BEFORE INVOKING A MODAL ACTION - never after. The watcher is a detached process: it keeps
    polling across the whole blocking invoke and stops itself after timeout_s.

    What it clicked is evidence: a test that expects no dialog fails on a non-empty "dismissed"
    list from ui_dismiss_watch_stop. An unexpected modal with no rule hangs the run instead of
    failing it, so prefer a preset that covers every known caption.

    Args:
        rules: [{"title_regex": "...", "button_name": "...", "process"?: "..."}]. Both are
            regexes (anchor them); button_name matches Button controls by name. Each window is
            acted on at most once. A rule watches EPLAN's windows unless it names a process.
        timeout_s: Self-termination deadline for the watcher (default 300).
        preset: Name of a rule set an extension registered. Your rules are matched FIRST, so a
            preset never overrides a deliberate choice.

    Returns:
        {"success": True, "watch_id": "...", "pid": N, "log": "...path..."}. Keep watch_id.
    """
    rules = list(rules or [])
    if preset:
        if preset not in _DIALOG_PRESETS:
            return {"success": False,
                    "error": "unknown preset %r; known: %s"
                             % (preset, ", ".join(sorted(_DIALOG_PRESETS)) or "none")}
        rules = rules + _DIALOG_PRESETS[preset]
    if not rules:
        return {"success": False, "error": "rules is required: [{title_regex, button_name}, ...]"}
    err = _check_rules(rules)
    if err:
        return {"success": False, "error": err}
    rules = [r if r.get("process") else dict(r, process=DEFAULT_PROCESS) for r in rules]
    # Starting only spawns the detached watcher, but on a CPU-starved machine the PowerShell host
    # alone has taken over 60 s to come up.
    return _run("dismiss_watch", {"mode": "start", "rules": rules, "timeout_s": timeout_s},
                timeout=180)


def ui_dismiss_watch_stop(watch_id: str, status_only: bool = False) -> dict:
    """
    Stop a dismiss watcher (or peek at it) and return everything it clicked. Call it in the
    teardown of EVERY test that armed one, failed ones included - a leftover watcher keeps
    clicking in later tests. Safe on an already-exited watcher.

    Args:
        watch_id: From ui_dismiss_watch_start.
        status_only: True leaves the watcher running; the default stops it.

    Returns:
        {"success": True, "count": N, "still_running": bool,
         "dismissed": [{at, hwnd, title, class, rule, button, result}]}
    """
    return _run("dismiss_watch", {"mode": "status" if status_only else "stop",
                                  "watch_id": watch_id}, timeout=180)
