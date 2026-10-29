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
"""

import json
import uuid

from ._base import cs_escape
from .scripted import _execute_script

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
            if (act == null) throw new Exception("Action %ACTION% is not available: the Data Portal add-in is not loaded or not licensed.");
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


def _run(action: str, params: dict, timeout: float = 60.0) -> dict:
    sets = "\n".join(
        f'            ctx.AddParameter("{cs_escape(k)}", "{cs_escape(str(v))}");' for k, v in params.items())
    script = (_SCRIPT.replace("%ID%", uuid.uuid4().hex[:8]).replace("%ACTION%", action)
              .replace("%SETS%", sets))
    raw = _execute_script(script, timeout=timeout)
    return raw.get("results", raw) if isinstance(raw, dict) else {"success": False, "error": str(raw)}


def dataportal_add_to_download_list(parts: list) -> dict:
    """
    Queue parts in the Data Portal download list of the EPLAN session. NEEDS THE USER.

    Queuing does not import anything. The user must open Data Portal inside
    EPLAN, go to the download list and download it; only then do the parts
    (with their macros, pictures and datasheets) reach the parts database. So
    after calling this ALWAYS tell the user, in plain words, exactly that, and
    which part numbers to download. Do not wait silently: the session is blocked
    on them. Pass on the "userAction" field of the result.

    Data Portal skips parts that already exist in the parts database, so never
    create a placeholder part record for something you intend to import.

    Args:
        parts: list of {"part_number": "SIE.5SL6316-7", "dataportal_id": "454767"}.
            dataportal_id is the number after "id-" in the part's Data Portal web
            address (dataportal.eplan.com/part-details/<mfr>/<part>/id-<number>).
            It is required; the action refuses a part number on its own.

    Returns:
        {"success", "executed", "queued": [...], "userAction": "<what to tell the user>"}.
        executed=false with success=true usually means a part was already in
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
    res = _run("EDPCloudAddPartsToBasketAction", params)
    queued = [p["part_number"] for p in parts]
    res["queued"] = queued
    res["userAction"] = (
        "ACTION NEEDED IN EPLAN: open Data Portal in EPLAN, go to the download list and download it "
        "so these parts are imported: " + ", ".join(queued) + ". Tell me when it is done.")
    if res.get("success") and not res.get("executed"):
        res["note"] = ("EPLAN reported executed=false: the parts were probably already in the download list "
                       "(the user can still download it), or a dataportal_id is wrong.")
    return res


def dataportal_search_count(search: str) -> dict:
    """
    Count Data Portal hits for a search term, using the EPLAN session's Data Portal sign-in.

    Read-only. Useful to check that a part number exists on Data Portal before
    asking the user to download it.

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
