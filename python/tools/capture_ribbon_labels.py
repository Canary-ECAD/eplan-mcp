"""
Capture the ribbon button labels of a running EPLAN and map them to actions.

Why this exists: people look for the words on the button. An engineer searches
for "Coordinate input" or "Page macro", not `GedEditGuiPosDialogShow` or
`XPageMacroAction`. Without this, searching the action catalog only works if you
already know EPLAN's internal action names - which defeats the point.

EPLAN does not hand this over directly. `RibbonCommand.ActionCommandLine` is
documented as "available only from a custom command" and is empty for built-in
buttons, so the label and the action have to be joined through the button's
numeric command id, which `<install>/Cfg/MFTools.xml` also keys on. This script
walks the live ribbon for (command id -> label), and build_action_registry.py
joins that against the command index to produce, per action, the labels and
ribbon paths a human would recognise.

CUSTOM COMMANDS ARE SKIPPED ON PURPOSE. Any tab or command flagged IsCustom
comes from a locally installed add-in, so its label could carry a company or
project name. Only stock EPLAN buttons are written out, which keeps the
generated file publishable.

Requires a running EPLAN with remoting enabled.

Usage:
    python tools/capture_ribbon_labels.py [--version 2027] [--port 49152]
                                          [--out tools/data/ribbon_labels_<ver>.json]

No third-party dependencies beyond what the MCP server already needs.
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_ROOT = os.path.join(REPO_ROOT, "mcp_server")
sys.path.insert(0, MCP_ROOT)
sys.path.insert(0, os.path.join(MCP_ROOT, "api"))

# The walk is defensive at every level: one tab, group or command that throws
# must not abort the rest of the ribbon. It writes its own JSON file rather than
# returning the tree, because the full ribbon is ~147KB.
CAPTURE_SCRIPT = r'''using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.Gui;
using Eplan.EplApi.Scripting;

public class CaptureRibbonLabels
{
    [Start]
    public void Run()
    {
        var results = new Dictionary<string, object>();
        var rows = new List<Dictionary<string, object>>();
        int tabs = 0, customSkipped = 0;
        try
        {
            using (var bar = new RibbonBar())
            {
                foreach (var tab in bar.Tabs)
                {
                    tabs++;
                    string tabName = "";
                    bool tabCustom = false;
                    try { tabName = tab.Name; } catch { }
                    try { tabCustom = tab.IsCustom; } catch { }
                    if (tabCustom) { customSkipped++; continue; }
                    try
                    {
                        foreach (var grp in tab.CommandGroups)
                        {
                            string grpName = "";
                            try { grpName = grp.Name; } catch { }
                            try
                            {
                                foreach (var kv in grp.Commands)
                                {
                                    try
                                    {
                                        var cmd = kv.Value;
                                        bool c = false;
                                        try { c = cmd.IsCustom; } catch { }
                                        if (c) { customSkipped++; continue; }
                                        var row = new Dictionary<string, object>();
                                        row["id"] = kv.Key.ToString();
                                        row["tab"] = tabName;
                                        row["group"] = grpName;
                                        try { row["text"] = cmd.Text; } catch { row["text"] = ""; }
                                        try { row["description"] = cmd.Description; } catch { }
                                        rows.Add(row);
                                    }
                                    catch { }
                                }
                            }
                            catch { }
                        }
                    }
                    catch { }
                }
            }
            results["success"] = true;
            results["tabs"] = tabs;
            results["custom_skipped"] = customSkipped;
            results["commands"] = rows.Count;
            File.WriteAllText(@"__ROWS__",
                Newtonsoft.Json.JsonConvert.SerializeObject(rows));
        }
        catch (Exception ex)
        {
            results["success"] = false;
            results["error"] = ex.Message;
        }
        File.WriteAllText(@"{{RESULT_PATH}}",
            Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented));
    }
}
'''


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="49152")
    parser.add_argument("--version", default=None,
                        help="EPLAN major version, e.g. 2027. Newest if omitted.")
    parser.add_argument("--out", default=None,
                        help="Default: tools/data/ribbon_labels_<version>.json")
    args = parser.parse_args()

    from eplan_connection import get_manager  # noqa: E402  (needs sys.path above)

    manager = get_manager(args.version)
    conn = manager.connect(host=args.host, port=args.port)
    if not conn.get("success"):
        print("Could not connect to EPLAN: {}".format(conn.get("message")),
              file=sys.stderr)
        return 1

    from actions.scripted import _execute_script  # noqa: E402

    rows_path = os.path.join(REPO_ROOT, "tools", "data", "_ribbon_rows.tmp.json")
    os.makedirs(os.path.dirname(rows_path), exist_ok=True)
    # {{RESULT_PATH}} is left intact - _execute_script substitutes it.
    script = CAPTURE_SCRIPT.replace("__ROWS__", rows_path.replace("\\", "/"))
    result = _execute_script(script, timeout=180.0)

    inner = result.get("results") or {}
    if not inner.get("success"):
        print("Capture failed: {}".format(inner.get("error") or result), file=sys.stderr)
        return 1

    try:
        with open(rows_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
    finally:
        try:
            os.remove(rows_path)
        except OSError:
            pass

    version = manager.target_version or "unknown"
    out_path = args.out or os.path.join(
        REPO_ROOT, "tools", "data", "ribbon_labels_{}.json".format(version))

    # Keyed by command id, which is what MFTools.xml/UsedActions is keyed on.
    by_id = {}
    for r in rows:
        cid = str(r.get("id") or "")
        text = (r.get("text") or "").strip()
        if not cid or not text:
            continue
        by_id.setdefault(cid, {
            "text": text,
            "tab": r.get("tab") or "",
            "group": r.get("group") or "",
        })

    payload = {
        "_meta": {
            "eplan_version": version,
            "source": "Eplan.EplApi.Gui.RibbonBar walk of a running installation",
            "tabs": inner.get("tabs"),
            "commands": len(by_id),
            "custom_skipped": inner.get("custom_skipped"),
            "note": ("Stock EPLAN buttons only - tabs and commands flagged IsCustom "
                     "are skipped so locally installed add-in labels never land in "
                     "this file. Keyed by ribbon command id, the same id "
                     "MFTools.xml/UsedActions uses, so build_action_registry.py can "
                     "join labels onto actions. Regenerate with "
                     "tools/capture_ribbon_labels.py."),
        },
        "commands": dict(sorted(by_id.items(), key=lambda kv: int(kv[0])
                                if kv[0].isdigit() else 0)),
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print("Wrote {}".format(out_path))
    print("  tabs={} commands={} custom_skipped={}".format(
        inner.get("tabs"), len(by_id), inner.get("custom_skipped")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
