"""
Probe which EPLAN actions are actually registered in a running installation.

`tools/data/official_actions_2027.json` and the GUI action map say which actions
EPLAN *documents*; this says which ones a given installation actually has. It
runs ActionManager.FindAction(name, silent=true) over every candidate name and
records the owning module for each hit.

Why it matters: an action name can appear in the docs or in MFTools.xml and
still not resolve here, because the owning module is not installed or not
covered by this licence. build_action_registry.py merges the output so
`action_catalog(available_only=True)` can filter to what this machine can run.

IMPORTANT - what a hit does and does not prove:
    resolved  -> the action is REGISTERED (its module is loaded).
    NOT resolved -> it is not registered: an unlicensed/uninstalled module, or
                 the name is a dialog id or a GED interaction name rather than
                 an action in its own right.
Resolving does NOT prove the action will EXECUTE. Module-level licensing is
enforced when the action runs, so a registered action can still refuse with a
"function could not be run" message. Treat this as a necessary-not-sufficient
availability check.

Requires a running EPLAN with remoting enabled.

Usage:
    python tools/probe_live_actions.py [--port 49152] [--version 2027]
                                       [--out tools/data/live_actions_<ver>.json]

No third-party dependencies beyond what the MCP server already needs.
"""

import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_ROOT = os.path.join(REPO_ROOT, "mcp_server")
sys.path.insert(0, MCP_ROOT)
sys.path.insert(0, os.path.join(MCP_ROOT, "api"))

DEFAULT_DOCS = os.path.join(REPO_ROOT, "tools", "data", "official_actions_2027.json")
DEFAULT_MFTOOLS = r"C:/Program Files/EPLAN/Platform/2027.0.1/Cfg/MFTools.xml"

# Probe in one C# round-trip rather than one per name: 1000+ separate script
# executions would take minutes and spam the message log.
PROBE_SCRIPT = r'''using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.Scripting;

public class ProbeLiveActions__ID__
{
    [Start]
    public void Run()
    {
        var results = new Dictionary<string, object>();
        var found = new Dictionary<string, string>();
        var missing = new List<string>();
        try
        {
            string[] names = File.ReadAllLines(@"__NAMES__");
            var am = new ActionManager();
            foreach (string raw in names)
            {
                string n = raw.Trim();
                if (n.Length == 0) continue;
                try
                {
                    // silent:true - otherwise every miss is written to the
                    // system message tree and buries real errors.
                    var a = am.FindAction(n, true);
                    if (a != null)
                    {
                        string mod = "";
                        try { mod = a.ModuleName; } catch { }
                        found[n] = mod;
                    }
                    else { missing.Add(n); }
                }
                catch (Exception ex) { missing.Add(n + " !ERR:" + ex.GetType().Name); }
            }
            results["success"] = true;
            results["found"] = found;
            results["missing"] = missing;
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


def candidate_names(docs_path, mftools_path):
    """Every action name worth probing: the documented ones plus the ones the
    local GUI action map mentions."""
    names = set()
    try:
        with open(docs_path, "r", encoding="utf-8") as f:
            names.update(json.load(f).keys())
    except Exception as e:
        print("WARNING: could not read {}: {}".format(docs_path, e), file=sys.stderr)

    if mftools_path and os.path.isfile(mftools_path):
        import html
        import xml.etree.ElementTree as ET
        with open(mftools_path, "r", encoding="utf-8-sig", errors="replace") as f:
            root = ET.parse(f).getroot()
        mod = root.find('./CAT[@name="STATION"]/MOD[@name="MFTools"]')
        if mod is not None:
            for section in ("UsedActions", "ActionCategory", "Dialogs", "SampleActions"):
                lev = mod.find('./LEV1[@name="{}"]'.format(section))
                if lev is None:
                    continue
                for val in lev.findall(".//Val"):
                    text = html.unescape((val.text or "")).strip()
                    if not text:
                        continue
                    token = text.split(";")[0].split()[0]
                    if re.fullmatch(r"[A-Za-z0-9_]+", token):
                        names.add(token)
    else:
        print("NOTE: {} not found; probing documented actions only."
              .format(mftools_path), file=sys.stderr)
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="49152")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--version", default=None,
                        help="EPLAN major version, e.g. 2027. Newest if omitted.")
    parser.add_argument("--docs", default=DEFAULT_DOCS)
    parser.add_argument("--mftools", default=DEFAULT_MFTOOLS)
    parser.add_argument("--out", default=None,
                        help="Default: tools/data/live_actions_<version>.json")
    args = parser.parse_args()

    from eplan_connection import get_manager  # noqa: E402  (needs sys.path above)

    names = candidate_names(args.docs, args.mftools)
    if not names:
        print("No candidate action names; nothing to probe.", file=sys.stderr)
        return 1
    print("Probing {} action names...".format(len(names)))

    manager = get_manager(args.version)
    conn = manager.connect(host=args.host, port=args.port)
    if not conn.get("success"):
        print("Could not connect to EPLAN: {}".format(conn.get("message")), file=sys.stderr)
        return 1

    from actions.scripted import _execute_script  # noqa: E402

    names_file = os.path.join(os.path.dirname(os.path.abspath(args.docs)),
                              "_probe_names.tmp")
    with open(names_file, "w", encoding="utf-8") as f:
        f.write("\n".join(names))
    try:
        # Note: {{RESULT_PATH}} is left intact - _execute_script substitutes it.
        script = (PROBE_SCRIPT
                  .replace("__ID__", "P")
                  .replace("__NAMES__", names_file.replace("\\", "/")))
        result = _execute_script(script, timeout=300.0)
    finally:
        try:
            os.remove(names_file)
        except OSError:
            pass

    inner = result.get("results") or {}
    if not inner.get("success"):
        print("Probe failed: {}".format(inner.get("error") or result), file=sys.stderr)
        return 1

    found = inner.get("found") or {}
    missing = inner.get("missing") or []
    version = manager.target_version or "unknown"
    out_path = args.out or os.path.join(
        REPO_ROOT, "tools", "data", "live_actions_{}.json".format(version))

    payload = {
        "_meta": {
            "eplan_version": version,
            "probe": "ActionManager.FindAction(name, silent=true)",
            "probed": len(found) + len(missing),
            "resolved": len(found),
            "unresolved": len(missing),
            "note": ("Point-in-time snapshot of ONE installation. 'resolved' means the "
                     "action is registered (module loaded); it does NOT prove the action "
                     "will execute, since module licensing is enforced at run time. "
                     "Regenerate with tools/probe_live_actions.py after an EPLAN version "
                     "or licence change."),
        },
        "resolved": dict(sorted(found.items())),
        "unresolved": sorted(missing),
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print("Wrote {}".format(out_path))
    print("  probed={} resolved={} unresolved={}"
          .format(payload["_meta"]["probed"], len(found), len(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
