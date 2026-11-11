"""
EPLAN Data Portal (integrated) actions.

EPLAN's Data Portal add-in (Eplan.EplCoreAddin.EDPCloud) registers actions that
run against the Data Portal session EPLAN itself is signed in to:

    EDPCloudAddPartsToBasketAction   PARTNR1..n + PARTID1..n -> the user's download list
    EDPCloudGetSearchCountAction     search -> "result" (hit count)

The download itself is a modal dialog in EPLAN (ModalDataPortalDownloadListView,
"StartDownload"), so it cannot be scripted. Queuing parts is therefore only half
of an import: the user has to open Data Portal in EPLAN and download the list.
Every result here says so in "userAction", and the caller must pass that on to
the user, because nothing else tells them that the session is waiting on them.

Measured on EPLAN 2026.0.3:
- PARTID is required. PARTNR alone returns executed=false. The id is Data
  Portal's own number, the last segment of a part's web address
  (dataportal.eplan.com/part-details/<manufacturer>/<part>/id-<PARTID>).
- Indexes start at 1. PARTNR0/PARTID0 returns executed=false.
- A part that is already in the download list returns executed=false.
- On download, Data Portal skips parts whose number already exists in the parts
  database, so do not create a placeholder record before importing a part.

Measured on EPLAN 2025.0.3: EDPCloudAddPartsToBasketAction is registered (module
Eplan.EplCoreAddin.EDPCloud); EDPCloudGetSearchCountAction is not, so the count
tool only works from 2026 on. Checking whether a part exists works on any version
through the Data Portal's public web API (POST /partscheck).

Also on 2025.0.3: EDPCloudAddPartsToBasketAction queues the part, then opens
EPLAN's Data Portal window ("EDP"), and its Execute does not return until the
user closes that window. Called inside the script, that held ExecuteScript: the
script never wrote its result and the tool hung until the client dropped the
connection, although the part was in the download list. On 2026 the action
returns normally.

So the queue script does not call the action itself. It checks that the action
exists, starts a WinForms timer on EPLAN's UI thread and returns at once; the
timer runs the action after ExecuteScript is done and writes the action's
result to a file of its own (and a ".started" marker when it begins). Python
then waits up to QUEUE_WAIT_S for that file:

- it appears (2026): the result is reported as before;
- a new EPLAN window stays open instead (2025): the tool returns within a few
  seconds with status "dataportal_window_open". The parts were handed to the
  Data Portal, but whether they reached the download list is only known when
  the window closes, so the user is told to check the list there before
  anything is queued again. The action's own verdict is reported by the next
  call of the tool, under "earlierResults";
- neither: status "pending", with what is known.

While that window is still open, a new queue request is refused without
calling EPLAN, with the same instruction: EPLAN would only hold it too.

Measured on 2025.0.3 with this design: the tool returned in 3.6 s; the window
is a #32770 dialog titled "EDP" that disables EPLAN's main window; eplan_ping
still answered, while any other EPLAN call came back EplanBlockedByDialog
after about 4 s. So the window is registered in eplan_connection.WINDOW_HINTS,
and those calls tell the caller to have the user finish in the window instead
of asking which button to press. After the user closed it, the action wrote
executed=true and EPLAN answered normally again.
"""

import json
import os
import time
import uuid

from ._base import cs_escape, get_manager
from .scripted import RESULTS_DIR, _execute_script

_SCRIPT = r'''using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.Scripting;

public class DataPortal_%ID%
{
    [Start]
    public void Run()
    {
        var results = new Dictionary<string, object>();
        try
        {
            var ctx = new ActionCallingContext();
%SETS%
            Eplan.EplApi.ApplicationFramework.Action act = new ActionManager().FindAction("%ACTION%");
            if (act == null) throw new Exception("Action %ACTION% is not available in this EPLAN: the Data Portal add-in is not loaded or not licensed, or this EPLAN version doesn't have it.");
            results["executed"] = act.Execute(ctx);
            var outp = new Dictionary<string, string>();
            foreach (string k in ctx.GetParameters()) { string v = ""; ctx.GetParameter(k, ref v); outp[k] = v; }
            results["context"] = outp;
            results["success"] = true;
        }
        catch (Exception ex) { results["success"] = false; results["error"] = ex.Message; }
        File.WriteAllText(@"{{RESULT_PATH}}", Newtonsoft.Json.JsonConvert.SerializeObject(results));
    }
}
'''

# The queue action runs from a timer once ExecuteScript has returned, so a
# window it opens cannot hold the script (see the module docstring). C# 5,
# like every generated script.
_QUEUE_SCRIPT = r'''using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.Scripting;

public class DataPortalQueue_%ID%
{
    // Keeps the timer alive until it fires.
    static System.Windows.Forms.Timer _timer;

    [Start]
    public void Run()
    {
        var results = new Dictionary<string, object>();
        try
        {
            var ctx = new ActionCallingContext();
%SETS%
            Eplan.EplApi.ApplicationFramework.Action act = new ActionManager().FindAction("%ACTION%");
            if (act == null) throw new Exception("Action %ACTION% is not available in this EPLAN: the Data Portal add-in is not loaded or not licensed, or this EPLAN version doesn't have it.");
            var timer = new System.Windows.Forms.Timer();
            timer.Interval = 300;
            timer.Tick += delegate(object sender, EventArgs e)
            {
                timer.Stop();
                timer.Dispose();
                _timer = null;
                RunAction(act, ctx);
            };
            _timer = timer;
            timer.Start();
            results["dispatched"] = true;
            results["success"] = true;
        }
        catch (Exception ex) { results["success"] = false; results["error"] = ex.Message; }
        File.WriteAllText(@"{{RESULT_PATH}}", Newtonsoft.Json.JsonConvert.SerializeObject(results));
    }

    static void RunAction(Eplan.EplApi.ApplicationFramework.Action act, ActionCallingContext ctx)
    {
        var results = new Dictionary<string, object>();
        try
        {
            File.WriteAllText("%DONE%.started", "");
            results["executed"] = act.Execute(ctx);
            var outp = new Dictionary<string, string>();
            foreach (string k in ctx.GetParameters()) { string v = ""; ctx.GetParameter(k, ref v); outp[k] = v; }
            results["context"] = outp;
            results["success"] = true;
        }
        catch (Exception ex) { results["success"] = false; results["error"] = ex.Message; }
        try { File.WriteAllText("%DONE%", Newtonsoft.Json.JsonConvert.SerializeObject(results)); }
        catch (Exception) { }
    }
}
'''

# How long the queue tool waits for the action to report back. On 2026 it
# returns at once; on 2025 a window is seen within about two checks.
QUEUE_WAIT_S = 8.0
# How often EPLAN's windows are checked while waiting. A window has to be seen
# on two checks in a row, so one that flashes up and closes does not count.
QUEUE_WINDOW_CHECK_S = 1.0
# ExecuteScript itself only starts a timer.
QUEUE_SCRIPT_TIMEOUT_S = 30.0

# Queue requests whose action has not reported back yet:
# done-file path -> {"parts": [...], "window": {"hwnd", "title"} or None}.
_pending = {}


def _sets(params: dict) -> str:
    return "\n".join(
        f'            ctx.AddParameter("{cs_escape(k)}", "{cs_escape(str(v))}");' for k, v in params.items())


def _run(action: str, params: dict, timeout: float = 60.0) -> dict:
    script = (_SCRIPT.replace("%ID%", uuid.uuid4().hex[:8]).replace("%ACTION%", action)
              .replace("%SETS%", _sets(params)))
    raw = _execute_script(script, timeout=timeout)
    return raw.get("results", raw) if isinstance(raw, dict) else {"success": False, "error": str(raw)}


# Thin wrappers over the window helpers, so tests can replace them. They read
# Windows, not EPLAN, so they work while EPLAN waits on a window. Never raise.

def _eplan_pids() -> set:
    """The EPLAN.exe processes behind the connection (none for a remote host)."""
    try:
        return set(get_manager()._watch_pids())
    except Exception:
        return set()


def _top_hwnds(pids) -> set:
    try:
        from eplan_connection import _top_hwnds as top_hwnds
        return top_hwnds(pids) if pids else set()
    except Exception:
        return set()


def _windows(pids) -> list:
    try:
        from eplan_connection import _list_windows
        return _list_windows(pids) if pids else []
    except Exception:
        return []


def _read_json(path):
    """The JSON object in `path`, or None while it is missing or half written."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _remove(*paths):
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _window_hints():
    from eplan_connection import WINDOW_HINTS
    return WINDOW_HINTS


def _hint_for(parts: list) -> str:
    """What a call blocked by the Data Portal window should do (eplan_connection.WINDOW_HINTS)."""
    return ("This is EPLAN's Data Portal window, opened by eplan_dataportal_add_to_download_list; "
            "EPLAN takes no commands until it is closed. Do not click its buttons: ask the user to "
            "check its download list for " + ", ".join(parts) + ", download it and close the window. "
            "Then retry this call: its result is unknown.")


def _forget(done: str):
    """Drop a pending request, its files and its window hint."""
    entry = _pending.pop(done, None) or {}
    window = entry.get("window")
    if window:
        _window_hints().pop((window["hwnd"], window["title"]), None)
    _remove(done, done + ".started")


def _sweep_stale(max_age_s: float = 86400.0):
    """Remove result files a stopped server left behind (an action that reported
    back after the process that waited for it had gone)."""
    try:
        names = os.listdir(RESULTS_DIR)
    except OSError:
        return
    now = time.time()
    for name in names:
        path = os.path.join(RESULTS_DIR, name)
        base = path[:-len(".started")] if name.endswith(".started") else path
        if not name.startswith("dataportal_") or base in _pending:
            continue
        try:
            if now - os.path.getmtime(path) > max_age_s:
                os.remove(path)
        except OSError:
            pass


def _collect_finished() -> list:
    """The verdicts of earlier queue requests whose action has reported back since."""
    finished = []
    for done, entry in list(_pending.items()):
        res = _read_json(done)
        if res is None:
            continue
        _forget(done)
        item = {"parts": entry["parts"], "success": res.get("success"), "executed": res.get("executed")}
        if res.get("error"):
            item["error"] = res["error"]
        finished.append(item)
    return finished


def _still_open(pids):
    """(window, parts) of an earlier request whose Data Portal window is still open, else None."""
    pending = [e for e in _pending.values() if e.get("window")]
    if not pending:
        return None
    open_now = {(w.get("hwnd"), w.get("title", "")) for w in _windows(pids)}
    found = None
    for entry in pending:
        window = entry["window"]
        if (window["hwnd"], window["title"]) in open_now:
            found = found or (window, entry["parts"])
        else:
            # Closed: its hint must not follow a reused hwnd. The request stays
            # pending until its action reports back.
            _window_hints().pop((window["hwnd"], window["title"]), None)
    return found


def _queue(params: dict, parts: list) -> dict:
    """Run the queue action so that a window it opens cannot hold the call."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    _sweep_stale()
    done = os.path.join(RESULTS_DIR, f"dataportal_{uuid.uuid4().hex[:12]}.json")
    pids = _eplan_pids()
    before = _top_hwnds(pids)
    script = (_QUEUE_SCRIPT.replace("%ID%", uuid.uuid4().hex[:8])
              .replace("%ACTION%", "EDPCloudAddPartsToBasketAction")
              .replace("%SETS%", _sets(params)).replace("%DONE%", cs_escape(done)))
    raw = _execute_script(script, timeout=QUEUE_SCRIPT_TIMEOUT_S)
    res = raw.get("results", raw) if isinstance(raw, dict) else {"success": False, "error": str(raw)}
    if not res.get("success") or not res.get("dispatched"):
        return res
    _pending[done] = {"parts": parts, "window": None}

    deadline = time.monotonic() + QUEUE_WAIT_S
    next_check = time.monotonic() + QUEUE_WINDOW_CHECK_S
    seen = set()
    while True:
        finished = _read_json(done)
        if finished is not None:
            _forget(done)
            return finished
        now = time.monotonic()
        if now >= next_check:
            next_check = now + QUEUE_WINDOW_CHECK_S
            new = [w for w in _windows(pids) if w.get("hwnd") not in before and not w.get("is_main")]
            confirmed = [w for w in new if w["hwnd"] in seen]
            seen = {w["hwnd"] for w in new}
            if confirmed:
                w = confirmed[0]
                window = {"hwnd": w["hwnd"], "title": w.get("title", "")}
                _pending[done]["window"] = window
                _window_hints()[(window["hwnd"], window["title"])] = _hint_for(parts)
                return {"success": True, "executed": None, "status": "dataportal_window_open",
                        "dataportal_window": window,
                        "eplanWaitsOnWindow": bool(w.get("main_disabled") or w.get("owner_disabled"))}
        if now >= deadline:
            return {"success": True, "executed": None, "status": "pending",
                    "started": os.path.exists(done + ".started")}
        time.sleep(0.1)


def dataportal_add_to_download_list(parts: list) -> dict:
    """
    Queue parts in the Data Portal download list of the EPLAN session. NEEDS THE USER.

    Queuing does not import anything. The user must open Data Portal inside
    EPLAN, go to the download list and download it; only then do the parts
    (with their macros, pictures and datasheets) reach the parts database. So
    after calling this ALWAYS tell the user, in plain words, exactly that, and
    which part numbers to download. Do not wait silently: the session is blocked
    on them. Pass on the "userAction" field of the result.

    Some EPLAN versions (2025) open their Data Portal window while queuing and
    only finish once the user closes it. Then status is "dataportal_window_open"
    and executed is null: the parts were handed to the Data Portal, but it is
    not known yet whether they reached the download list. Do NOT call this
    again for them: ask the user to check the download list in that window,
    download it and close the window. A call made while that window is still
    open is refused. The next call reports the earlier verdict in
    "earlierResults".

    Data Portal skips parts that already exist in the parts database, so never
    create a placeholder part record for something you intend to import.

    Args:
        parts: list of {"part_number": "SIE.5SL6316-7", "dataportal_id": "454767"}.
            dataportal_id is the number after "id-" in the part's Data Portal web
            address (dataportal.eplan.com/part-details/<mfr>/<part>/id-<number>).
            It is required; the action refuses a part number on its own.

    Returns:
        {"success", "executed", "status", "queued": [...], "userAction": "<what to tell the user>"}.
        status: "done" (executed is EPLAN's verdict), "dataportal_window_open"
        (with "dataportal_window") or "pending" (executed null in both).
        executed=false with status "done" usually means a part was already in
        the download list, or a dataportal_id is wrong.
    """
    if not parts:
        return {"success": False, "error": "No parts given."}
    params = {}
    for i, p in enumerate(parts, 1):
        pn, pid = (p.get("part_number") or "").strip(), str(p.get("dataportal_id") or "").strip()
        if not pn or not pid.isdigit():
            return {"success": False, "error": f"Part {i} needs part_number and a numeric dataportal_id: {p!r}"}
        params[f"PARTNR{i}"] = pn
        params[f"PARTID{i}"] = pid
    queued = [p["part_number"].strip() for p in parts]

    earlier = _collect_finished()
    pids = _eplan_pids()
    still_open = _still_open(pids)
    if still_open:
        window, waiting = still_open
        res = {
            "success": False, "errorType": "DataPortalWindowOpen", "executed": None,
            "dataportal_window": window, "queued": [],
            "error": (f"EPLAN's Data Portal window ({window['title']!r}) from an earlier request is "
                      "still open, so nothing was sent: EPLAN would only hold this request too."),
            "userAction": (
                "ACTION NEEDED IN EPLAN: the Data Portal window is still open. Check its download "
                "list for " + ", ".join(waiting) + ", download it and close the window. Then I can "
                "queue " + ", ".join(queued) + ". Tell me when it is done."),
        }
        if earlier:
            res["earlierResults"] = earlier
        return res

    res = _queue(params, queued)
    if earlier:
        res["earlierResults"] = earlier
    res["queued"] = queued
    if not res.get("success"):
        return res
    status = res.setdefault("status", "done")
    if status == "dataportal_window_open":
        title = res["dataportal_window"]["title"] or "Data Portal"
        res["message"] = (
            f"EPLAN opened its Data Portal window ({title!r}) while queuing and finishes the request "
            "only when that window is closed, so it is not known yet whether the parts reached the "
            "download list. Do not queue them again.")
        if res.get("eplanWaitsOnWindow"):
            res["message"] += " EPLAN takes no other commands until the window is closed."
        res["userAction"] = (
            "ACTION NEEDED IN EPLAN: the Data Portal window is open. Check that its download list has "
            + ", ".join(queued) + " (add them there if not), download the list, then close the "
            "window. Tell me when it is done.")
        return res
    if status == "pending":
        res["message"] = (
            "EPLAN has not finished the request yet and opened no window that could be seen, so it is "
            "not known whether the parts reached the download list. Do not queue them again; "
            "eplan_list_dialogs shows whether EPLAN is waiting on something.")
    res["userAction"] = (
        "ACTION NEEDED IN EPLAN: open Data Portal in EPLAN, go to the download list and download it "
        "so these parts are imported: " + ", ".join(queued) + ". Tell me when it is done.")
    if status == "done" and not res.get("executed"):
        res["note"] = ("EPLAN reported executed=false: the parts were probably already in the download list "
                       "(the user can still download it), or a dataportal_id is wrong.")
    return res


def dataportal_search_count(search: str) -> dict:
    """
    Count Data Portal hits for a search term, using the EPLAN session's Data Portal sign-in.

    Read-only. Useful to check that a part number exists on Data Portal before
    asking the user to download it. EPLAN 2026 and later: 2025 doesn't register
    this action, and the result then says it is not available.

    Args:
        search: Search text, e.g. "TDR-480-24" or a full part number "MWP.TDR-480-24".

    Returns:
        {"success", "executed", "count"} with count as an integer when EPLAN returned one.
    """
    res = _run("EDPCloudGetSearchCountAction", {"search": search})
    try:
        res["count"] = int((res.get("context") or {}).get("result"))
    except (TypeError, ValueError):
        res["count"] = None
    return res
