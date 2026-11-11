"""
Build the unified EPLAN action registry.

Unions three sources into a single JSON file:

  1. tools/data/official_actions_2027.json
       The 100 officially documented EPLAN 2027 actions (name, description,
       doc_url, parameter table) scraped from eplan.help.
  2. <EPLAN install>/Cfg/MFTools.xml
       The live install's GUI action map. Four sections are read:
         UsedActions    - ~1025 GUI command ids -> full action command lines
         ActionCategory - 43 rights-management categories
         SampleActions  - templated command lines with '?' placeholders
         Dialogs        - dialog-opening actions
       This source is OPTIONAL: on a machine without EPLAN installed the
       script prints a warning and still produces a registry (with empty
       "gui" blocks).
  3. mcp_server/api/actions/*.py
       The actions currently wrapped as MCP tools, discovered by parsing the
       "Action: <Name>" line out of each wrapper docstring (same approach as
       tools/validate_actions.py).

Output: mcp_server/api/actions/data/action_registry.json

The output is byte-stable across runs (sorted keys, sorted lists, no
timestamp) so it can be committed and diffed.

Usage:
    python tools/build_action_registry.py [--mftools <path>] [--out <path>]

No third-party dependencies (stdlib only).
"""

import argparse
import ast
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DOCS = os.path.join(REPO_ROOT, "tools", "data", "official_actions_2027.json")
ACTIONS_DIR = os.path.join(REPO_ROOT, "mcp_server", "api", "actions")
DEFAULT_OUT = os.path.join(ACTIONS_DIR, "data", "action_registry.json")
DEFAULT_MFTOOLS = r"C:/Program Files/EPLAN/Platform/2027.0.1/Cfg/MFTools.xml"
DEFAULT_LIVE = os.path.join(REPO_ROOT, "tools", "data", "live_actions_2027.json")
DEFAULT_LABELS = os.path.join(REPO_ROOT, "tools", "data", "ribbon_labels_2027.json")

# Same regex tools/validate_actions.py uses to read the wrapper docstrings.
ACTION_RE = re.compile(r"Action:\s*([A-Za-z0-9_]+)")
# Leading token of an MFTools command line, e.g. "XEGActionInsertSymRef /..."
CMD_NAME_RE = re.compile(r"^([A-Za-z0-9_]+)")
# /KEY:value | /KEY value | /KEY  -- must be preceded by whitespace so that
# path fragments such as C:/Temp/x cannot be mistaken for a parameter.
CMD_PARAM_RE = re.compile(r"(?<!\S)/([A-Za-z0-9_]+)")
QUOTED_RE = re.compile(r'"[^"]*"')
VERSION_RE = re.compile(r"\d{4}(?:\.\d+)*")

MFTOOLS_XPATH = './CAT[@name="STATION"]/MOD[@name="MFTools"]'


# --------------------------------------------------------------------------
# entry helpers
# --------------------------------------------------------------------------

def _new_entry(name):
    return {
        "name": name,
        "description": "",
        "documented": False,
        "doc_url": None,
        "params": [],
        "gui": {"command_ids": [], "categories": [], "examples": [],
                # Human-facing button text and where it sits in the ribbon,
                # joined in from a live capture. This is what makes an action
                # findable by the words someone would actually use.
                "labels": [], "ribbon_paths": []},
        "wrapped_by": [],
        "origin": set(),
        # Filled from the live ActionManager.FindAction probe when available:
        # True  = registered in the probed installation (module loaded + licensed)
        # False = not registered there (unlicensed module, or the name is a
        #         dialog id / GED interaction name rather than an action)
        # None  = never probed
        "live_resolved": None,
        "module_name": None,
        # transient bookkeeping, removed by finalize()
        "_param_index": {},          # lowercased name -> params[] index
        "_command_ids": set(),
        "_categories": set(),
        "_examples": set(),
        "_labels": set(),
        "_ribbon_paths": set(),
    }


def load_live_probe(path, registry):
    """
    Stamp entries with the result of the live ActionManager.FindAction probe.

    Optional input: the probe is a point-in-time snapshot of ONE installation,
    so a missing file just leaves live_resolved None everywhere rather than
    failing the build.
    """
    stats = {"found": False, "resolved": 0, "unresolved": 0, "unknown_names": 0}
    if not path or not os.path.isfile(path):
        if path:
            print("NOTE: live probe {} not found; live_resolved left null "
                  "(pass --live to point at one).".format(path), file=sys.stderr)
        return stats
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    stats["found"] = True
    for name, module in (data.get("resolved") or {}).items():
        entry = registry.get(name)
        if entry is None:
            stats["unknown_names"] += 1
            continue
        entry["live_resolved"] = True
        entry["module_name"] = module or None
        stats["resolved"] += 1
    for raw in data.get("unresolved") or []:
        entry = registry.get(str(raw).split(" ")[0])
        if entry is None:
            stats["unknown_names"] += 1
            continue
        entry["live_resolved"] = False
        stats["unresolved"] += 1
    return stats


def load_ribbon_labels(path, registry):
    """
    Attach ribbon button text to the actions those buttons run.

    People search for the words on the button - "Coordinate input", "Page
    macro" - not for GedEditGuiPosDialogShow. EPLAN will not hand over that
    mapping directly (RibbonCommand.ActionCommandLine is empty for built-in
    buttons), so tools/capture_ribbon_labels.py records command id -> label from
    a live session and this joins it on through the same command ids MFTools.xml
    uses.

    Optional input: without it every entry simply keeps empty labels.
    """
    stats = {"found": False, "labelled_actions": 0, "labels": 0, "unmatched_ids": 0}
    if not path or not os.path.isfile(path):
        return stats
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    stats["found"] = True

    # command id -> action, inverted from what the registry already knows
    by_id = {}
    for name, entry in registry.items():
        for cid in entry["_command_ids"]:
            by_id.setdefault(str(cid), name)

    for cid, info in (data.get("commands") or {}).items():
        action = by_id.get(str(cid))
        if action is None:
            stats["unmatched_ids"] += 1
            continue
        entry = registry[action]
        text = (info.get("text") or "").strip()
        tab = (info.get("tab") or "").strip()
        group = (info.get("group") or "").strip()
        if text:
            entry["_labels"].add(text)
            stats["labels"] += 1
        if tab or group:
            entry["_ribbon_paths"].add((tab + " > " + group).strip(" >"))
    stats["labelled_actions"] = sum(1 for e in registry.values() if e["_labels"])
    return stats


def _get(registry, name):
    entry = registry.get(name)
    if entry is None:
        entry = registry[name] = _new_entry(name)
    return entry


def _add_param(entry, name, description, source, collisions):
    """Add a parameter, de-duplicating case-insensitively (docs win)."""
    key = name.lower()
    idx = entry["_param_index"].get(key)
    if idx is not None:
        existing = entry["params"][idx]
        if existing["name"] != name:
            collisions.append((entry["name"], existing["name"], name))
        if source == "docs" and existing["source"] != "docs":
            # Documented casing/description is authoritative.
            existing.update({"name": name, "description": description, "source": "docs"})
        return
    entry["_param_index"][key] = len(entry["params"])
    entry["params"].append({"name": name, "description": description, "source": source})


def _sort_key_numeric(value):
    """Sort ids numerically when they are numeric, else lexically, stably."""
    return (0, int(value), "") if value.isdigit() else (1, 0, value)


# --------------------------------------------------------------------------
# source 1: official docs
# --------------------------------------------------------------------------

def load_docs(path, registry, collisions):
    with open(path, "r", encoding="utf-8") as f:
        docs = json.load(f)
    for name, info in docs.items():
        entry = _get(registry, name)
        entry["description"] = html.unescape(info.get("description") or "")
        entry["documented"] = True
        entry["doc_url"] = info.get("doc_url") or None
        if info.get("doc_error"):
            entry["doc_error"] = info["doc_error"]
        for p in info.get("params") or []:
            _add_param(entry, p["name"], html.unescape(p.get("description") or ""),
                       "docs", collisions)
        entry["origin"].add("docs")
    return len(docs)


# --------------------------------------------------------------------------
# source 2: MFTools.xml
# --------------------------------------------------------------------------

def _ingest_command_line(registry, collisions, raw, origin, command_id=None,
                         as_example=True):
    """Parse one 'ActionName /P1:x /P2:y' command line into the registry."""
    text = html.unescape((raw or "")).strip()
    if not text:
        return None
    m = CMD_NAME_RE.match(text)
    if not m:
        return None
    name = m.group(1)
    entry = _get(registry, name)
    entry["origin"].add(origin)
    if command_id:
        entry["_command_ids"].add(str(command_id))
    rest = QUOTED_RE.sub('""', text[m.end():])
    for key in CMD_PARAM_RE.findall(rest):
        _add_param(entry, key, "", "observed", collisions)
    if as_example and len(text) > len(name):
        entry["_examples"].add(text)
    return entry


def load_mftools(path, registry, collisions):
    """Read the four MFTools sections. Returns a stats dict (never raises)."""
    stats = {"found": False, "command_index": {},
             "used_actions": 0, "categories": 0,
             "sample_actions": 0, "dialogs": 0}
    # NOTE: used_actions / sample_actions / dialogs count DISTINCT action names
    # contributed by that section; categories counts distinct category ids.
    if not path or not os.path.isfile(path):
        print(
            "WARNING: MFTools.xml not found at {}\n"
            "         GUI command ids / categories / examples will be empty.\n"
            "         Pass --mftools <path> to point at a local EPLAN install."
            .format(path),
            file=sys.stderr,
        )
        return stats

    with open(path, "r", encoding="utf-8-sig") as f:
        root = ET.parse(f).getroot()
    mod = root.find(MFTOOLS_XPATH)
    if mod is None:
        print("WARNING: {} has no STATION/MFTools section; skipping.".format(path),
              file=sys.stderr)
        return stats
    stats["found"] = True

    def section(name):
        return mod.find('./LEV1[@name="{}"]'.format(name))

    # -- UsedActions: <Setting name="<cmdId>"><Val>command line</Val>
    lev = section("UsedActions")
    if lev is not None:
        names = set()
        for setting in lev.findall(".//Setting"):
            cmd_id = setting.get("name")
            for val in setting.findall("./Val"):
                entry = _ingest_command_line(
                    registry, collisions, val.text, "used_actions", cmd_id)
                if entry is not None:
                    names.add(entry["name"])
                    # Reverse map: GUI command id -> the action command line
                    # behind that button. This is the ONLY way to resolve a
                    # built-in ribbon button to an action, because
                    # RibbonCommand.ActionCommandLine is populated for custom
                    # commands only (verified live: built-ins return "").
                    # ribbon_catalog() joins its live command ids against this.
                    if cmd_id and cmd_id not in stats["command_index"]:
                        stats["command_index"][cmd_id] = {
                            "action": entry["name"],
                            "command_line": " ".join((val.text or "").split()),
                        }
        stats["used_actions"] = len(names)

    # -- ActionCategory: <Setting name="<catId>"><Val>Action[;cmdId]</Val>
    lev = section("ActionCategory")
    if lev is not None:
        cats = set()
        for setting in lev.findall(".//Setting"):
            cat_id = setting.get("name")
            cats.add(cat_id)
            for val in setting.findall("./Val"):
                name, _, cmd_id = html.unescape((val.text or "").strip()).partition(";")
                name = name.strip()
                if not name:
                    continue
                entry = _get(registry, name)
                entry["origin"].add("action_category")
                entry["_categories"].add(str(cat_id))
                if cmd_id.strip():
                    entry["_command_ids"].add(cmd_id.strip())
        stats["categories"] = len(cats)

    # -- SampleActions: templated command lines with '?' placeholders
    lev = section("SampleActions")
    if lev is not None:
        names = set()
        for setting in lev.findall(".//Setting"):
            for val in setting.findall("./Val"):
                entry = _ingest_command_line(
                    registry, collisions, val.text, "sample_actions")
                if entry is not None:
                    names.add(entry["name"])
        stats["sample_actions"] = len(names)

    # -- Dialogs: <Val>Action[;cmdId]</Val>
    lev = section("Dialogs")
    if lev is not None:
        names = set()
        for setting in lev.findall(".//Setting"):
            for val in setting.findall("./Val"):
                name, _, cmd_id = html.unescape((val.text or "").strip()).partition(";")
                name = name.strip()
                if not name:
                    continue
                entry = _get(registry, name)
                entry["origin"].add("dialogs")
                if cmd_id.strip():
                    entry["_command_ids"].add(cmd_id.strip())
                names.add(name)
        stats["dialogs"] = len(names)

    return stats


# --------------------------------------------------------------------------
# source 3: the wrappers themselves
# --------------------------------------------------------------------------

def load_wrappers(actions_dir, registry):
    """Map 'Action: <Name>' docstrings to their module.function."""
    count = 0
    for fname in sorted(os.listdir(actions_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(actions_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            m = ACTION_RE.search(ast.get_docstring(node) or "")
            if not m:
                continue
            entry = _get(registry, m.group(1))
            entry["wrapped_by"].append("{}.{}".format(fname[:-3], node.name))
            count += 1
    return count


# --------------------------------------------------------------------------
# finalize + write
# --------------------------------------------------------------------------

def finalize(registry, examples_cap=6):
    out = {}
    for name in sorted(registry):
        e = registry[name]
        e["gui"]["command_ids"] = sorted(e.pop("_command_ids"), key=_sort_key_numeric)
        e["gui"]["categories"] = sorted(e.pop("_categories"), key=_sort_key_numeric)
        # sort before capping so the cap does not depend on file order
        e["gui"]["examples"] = sorted(e.pop("_examples"))[:examples_cap]
        e["gui"]["labels"] = sorted(e.pop("_labels"))
        e["gui"]["ribbon_paths"] = sorted(e.pop("_ribbon_paths"))
        e.pop("_param_index")
        e["wrapped_by"] = sorted(set(e["wrapped_by"]))
        e["origin"] = sorted(e["origin"])
        out[name] = e
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mftools", default=DEFAULT_MFTOOLS,
                        help="Path to <EPLAN install>/Cfg/MFTools.xml "
                             "(default: %(default)s). Optional.")
    parser.add_argument("--docs", default=DEFAULT_DOCS,
                        help="Path to official_actions_2027.json")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="Output registry path")
    parser.add_argument("--labels", default=DEFAULT_LABELS,
                        help="Ribbon button labels captured by "
                             "tools/capture_ribbon_labels.py (default: %(default)s). Optional.")
    parser.add_argument("--live", default=DEFAULT_LIVE,
                        help="Path to a live ActionManager.FindAction probe "
                             "(default: %(default)s). Optional; when absent "
                             "every live_resolved stays null.")
    parser.add_argument("--examples-cap", type=int, default=6,
                        help="Max GUI command-line examples per action")
    args = parser.parse_args()

    registry = {}
    collisions = []

    documented = load_docs(args.docs, registry, collisions)
    mf = load_mftools(args.mftools, registry, collisions)
    wrapper_funcs = load_wrappers(ACTIONS_DIR, registry)
    live = load_live_probe(args.live, registry)
    labels = load_ribbon_labels(args.labels, registry)

    entries = finalize(registry, args.examples_cap)

    wrapped = sum(1 for e in entries.values() if e["wrapped_by"])
    gui_only = sum(1 for e in entries.values()
                   if "docs" not in e["origin"] and not e["wrapped_by"])

    version = VERSION_RE.search(args.mftools or "")
    payload = {
        "_meta": {
            "counts": {
                "total": len(entries),
                "documented": documented,
                "wrapped": wrapped,
                "gui_only": gui_only,
                "wrapper_functions": wrapper_funcs,
                "used_actions": mf["used_actions"],
                "action_categories": mf["categories"],
                "sample_actions": mf["sample_actions"],
                "dialogs": mf["dialogs"],
                "live_resolved": live["resolved"],
                "live_unresolved": live["unresolved"],
                "labelled_actions": labels["labelled_actions"],
            },
            "eplan_version": version.group(0) if version else "2027",
            "examples_cap": args.examples_cap,
            "sources": {
                "docs": os.path.relpath(args.docs, REPO_ROOT).replace("\\", "/"),
                "wrappers": os.path.relpath(ACTIONS_DIR, REPO_ROOT).replace("\\", "/"),
                # Basename only: an absolute path here would bake the build
                # machine's install location (and possibly a username or UNC
                # share) into a committed file. The version lives in
                # eplan_version, so the full path adds nothing.
                "mftools": os.path.basename(args.mftools or ""),
                "mftools_found": mf["found"],
                # Relative like docs/wrappers: an absolute path here would
                # bake the build machine's username into a committed file.
                "live_probe": (
                    os.path.relpath(args.live, REPO_ROOT).replace("\\", "/")
                    if args.live and os.path.isfile(args.live) else ""
                ),
                "live_probe_found": live["found"],
            },
        },
        # GUI command id -> {action, command_line}. Lets ribbon_catalog()
        # resolve a built-in ribbon button (which exposes only text + id) to
        # the action command line it actually runs.
        "_command_index": dict(sorted(mf["command_index"].items())),
    }
    payload["_meta"]["counts"]["gui_command_ids"] = len(mf["command_index"])
    payload.update(entries)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print("Registry written to {}".format(args.out))
    print("  total={total}  documented={documented}  wrapped={wrapped}  "
          "gui_only={gui_only}".format(**payload["_meta"]["counts"]))
    print("  Ribbon labels: found={} actions_labelled={} labels={}"
          .format(labels["found"], labels["labelled_actions"], labels["labels"]))
    print("  Live probe: found={} resolved={} unresolved={}"
          .format(live["found"], live["resolved"], live["unresolved"]))
    print("  MFTools: found={} used_actions={} categories={} samples={} dialogs={}"
          .format(mf["found"], mf["used_actions"], mf["categories"],
                  mf["sample_actions"], mf["dialogs"]))
    if collisions:
        print("  NOTE: {} case-only parameter collisions (docs casing kept), e.g. {}"
              .format(len(collisions), collisions[:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
