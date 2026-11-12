"""
Generic live object query/edit - one engine for "find these objects, read or
write these properties" instead of one tool per property.

Same reflection technique and scaffold as live.py (no DataModel `using`, types
resolved from the loaded assemblies, LockingStep held for the run).

    live_objects_read   pick objects, filter them, read properties
    live_objects_edit   same selection, then write properties and/or re-apply
                        part data (DeviceService.UpdateDevice); dry-run default

Objects (`kind`): "function" (devices, cables, terminals...), "connection",
"page" or "macrobox" (window-macro boxes: 23001 = macro file name, 23011 = type
of usage; found by walking every placement, so allow time on big projects),
found project-wide by filter. `project` picks any OPEN project by
name or path; without it the tools act on the one with GUI focus. For objects the user has SELECTED,
use the existing eplan_get_property / eplan_set_property instead - these tools
deliberately do not duplicate them.

A property spec is one of:
    "31002"                     property id, index 0
    "20901:2"                   property id, index 2
    "Acme.Fn.Lbl.CP01.T01.L"    user-defined property, by identifying name
    "Acme.Fn.Foo:3"             user-defined property, index 3
    name | page | type | handle | partNr | area
                                pseudo-properties of the object itself;
                                partNr is every part number on its article
                                references (a filter matches if any does);
                                area is a placement's logical area
                                "x1,y1,x2,y2" in mm, 2 decimals (macro boxes)

A filter (`where`) is a list of {"prop", "op", "value"}, all of which must
hold. Ops: eq, ne, contains (case-insensitive), startswith, regex, empty,
notempty.
"""

import uuid

from ._base import cs_escape
from .live import _FINDER, _execute_script, _script

KINDS = ("function", "connection", "page", "macrobox")
OPS = ("eq", "ne", "contains", "startswith", "regex", "empty", "notempty")


_HELPERS = '''
    // Resolved property ids, cached per spec: a by-name lookup is not free.
    static Dictionary<string, object[]> _ids = new Dictionary<string, object[]>();

    static object[] Resolve(object project, string spec)
    {
        object[] hit;
        if (_ids.TryGetValue(spec, out hit)) return hit;
        int index = 0;
        string key = spec;
        int colon = spec.LastIndexOf(':');
        int ix;
        if (colon > 0 && int.TryParse(spec.Substring(colon + 1), out ix))
        {
            index = ix;
            key = spec.Substring(0, colon);
        }
        // AnyPropertyId has an implicit conversion from int and NO int
        // constructor; a user-defined property is AnyPropertyId(project, name).
        Type anyId = FindType("Eplan.EplApi.DataModel.AnyPropertyId");
        object id;
        int num;
        if (int.TryParse(key, out num)) id = MakeValue(anyId, num);
        else
        {
            try { id = Activator.CreateInstance(anyId, new object[] { project, key }); }
            catch (Exception ex) { throw new Exception("Unknown property '" + key + "': " + Flatten(ex)); }
        }
        hit = new object[] { id, index };
        _ids[spec] = hit;
        return hit;
    }

    static object PropValue(object obj, object project, string spec)
    {
        object[] r = Resolve(project, spec);
        object props = RequireReadable(obj.GetType(), "Properties").GetValue(obj, null);
        // PropertyList only has this[AnyPropertyId]; the index lives on the
        // returned PropertyValue (this[int]). There is no (id, index) indexer.
        MethodInfo item = MethodByShape(props.GetType(), "get_Item",
            new string[] { "AnyPropertyId" }, false);
        if (item == null)
        {
            // PagePropertyList (and other typed lists) have no this[AnyPropertyId]; they
            // expose Property(AnyPropertyId, int) instead, which takes the index directly.
            MethodInfo prop = RequireMethod(props.GetType(), "get_Property",
                new string[] { "AnyPropertyId", "Int32" }, false);
            return Call(prop, props, new object[] { r[0], r[1] });
        }
        object pv = Call(item, props, new object[] { r[0] });
        if ((int)r[1] == 0) return pv;
        MethodInfo byIndex = RequireMethod(pv.GetType(), "get_Item", new string[] { "Int32" }, false);
        return Call(byIndex, pv, new object[] { r[1] });
    }

    // Every value a spec has on one object. Throws when the property does not
    // apply to this object; callers decide what that means.
    static List<string> Values(object obj, object project, string spec)
    {
        List<string> v = new List<string>();
        if (spec == "name") { v.Add(PropText(obj, "Name")); return v; }
        if (spec == "type") { v.Add(obj.GetType().Name); return v; }
        if (spec == "handle") { v.Add(Handle(obj)); return v; }
        if (spec == "page")
        {
            object pg = TryRead(obj, "Page", null);
            v.Add(pg == null ? null : PropText(pg, "Name"));
            return v;
        }
        if (spec == "area")
        {
            // Location throws on a MacroBox; its logical area is what defines the box.
            object a = Call(RequireMethod(obj.GetType(), "GetLogicalArea", new string[] { }, false), obj, null);
            object ll = RequireReadable(a.GetType(), "LowerLeft").GetValue(a, null);
            object ur = RequireReadable(a.GetType(), "UpperRight").GetValue(a, null);
            Func<object, string, string> c = (p, n) => ((double)RequireReadable(p.GetType(), n).GetValue(p, null))
                .ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
            v.Add(c(ll, "X") + "," + c(ll, "Y") + "," + c(ur, "X") + "," + c(ur, "Y"));
            return v;
        }
        if (spec == "partNr")
        {
            IEnumerable refs = TryRead(obj, "ArticleReferences", null) as IEnumerable;
            if (refs != null)
                foreach (object ar in refs) v.Add(SafeText(TryRead(ar, "PartNr", null)));
            return v;
        }
        v.Add(SafeText(PropValue(obj, project, spec)));
        return v;
    }

    static bool TestOne(string s, string op, string want)
    {
        if (s == null) s = "";
        if (op == "eq" || op == "ne") return string.Equals(s, want, StringComparison.Ordinal);
        if (op == "contains") return s.IndexOf(want, StringComparison.OrdinalIgnoreCase) >= 0;
        if (op == "startswith") return s.StartsWith(want, StringComparison.Ordinal);
        if (op == "regex") return System.Text.RegularExpressions.Regex.IsMatch(s, want);
        throw new Exception("Unknown op " + op);
    }

    static bool Passes(object obj, object project, string spec, string op, string want)
    {
        List<string> vals;
        try { vals = Values(obj, project, spec); }
        catch { vals = new List<string>(); }   // property does not apply: no value
        bool empty = true;
        foreach (string s in vals) if (!string.IsNullOrEmpty(s)) { empty = false; break; }
        if (op == "empty") return empty;
        if (op == "notempty") return !empty;
        bool any = false;
        foreach (string s in vals) if (TestOne(s, op, want)) { any = true; break; }
        return op == "ne" ? !any : any;
    }

    static string ReadText(object obj, object project, string spec)
    {
        try
        {
            List<string> vals = Values(obj, project, spec);
            return vals.Count == 1 ? vals[0] : string.Join("\\u00b6", vals.ToArray());
        }
        catch (Exception ex) { return "ERROR: " + Flatten(ex); }
    }
'''


def _cs_array(items):
    return "new string[] { " + ", ".join('"' + cs_escape(str(i)) + '"' for i in items) + " }"


def _validate(kind, where, read, limit):
    """Shared argument checks; returns (error_dict or None, where, read, limit)."""
    if kind not in KINDS:
        return {"success": False, "error": f"kind must be one of {KINDS}, got {kind!r}."}, None, None, None
    where = where or []
    if not isinstance(where, (list, tuple)):
        return {"success": False, "error": "where must be a list of {prop, op, value}."}, None, None, None
    for w in where:
        if not isinstance(w, dict) or not w.get("prop") or w.get("op", "eq") not in OPS:
            return {"success": False,
                    "error": f"Bad condition {w!r}: needs 'prop' and an op from {OPS}."}, None, None, None
    read = read or []
    if isinstance(read, str) or not isinstance(read, (list, tuple)):
        return {"success": False, "error": "read must be a list of property specs."}, None, None, None
    # limit is interpolated outside a string literal: must be a real integer.
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return {"success": False, "error": f"Invalid limit: {limit!r}. Must be an integer."}, None, None, None
    return None, list(where), [str(r) for r in read], limit


def _body(kind, where, read, set_props, update_from_part, dry_run, limit, project=None,
          guard=None):
    w_prop = _cs_array(w["prop"] for w in where)
    w_op = _cs_array(w.get("op", "eq") for w in where)
    w_val = _cs_array("" if w.get("value") is None else w["value"] for w in where)
    s_keys = list(set_props.keys())
    pick = '''            project = PickProject(project, "''' + cs_escape(project or "") + '''");
            results["project"] = PropText(project, "ProjectName");
'''
    if guard is not None:
        # After PickProject, so the guard checks the project the write really lands in.
        pick += guard
    return pick + _FINDER + '''            string KIND = "''' + kind + '''";
            string[] wProp = ''' + w_prop + ''';
            string[] wOp = ''' + w_op + ''';
            string[] wVal = ''' + w_val + ''';
            string[] readSpecs = ''' + _cs_array(read) + ''';
            string[] setSpecs = ''' + _cs_array(s_keys) + ''';
            string[] setVals = ''' + _cs_array(set_props[k] for k in s_keys) + ''';
            bool updateFromPart = ''' + ("true" if update_from_part else "false") + ''';
            bool dryRun = ''' + ("true" if dry_run else "false") + ''';
            int LIMIT = ''' + str(limit) + ''';

            IEnumerable source;
            if (KIND == "macrobox")
            {
                // No GetMacroBoxes: walk every placement and keep the MacroBox ones.
                Type fType = FindType("Eplan.EplApi.DataModel.PlacementsFilter");
                MethodInfo get = RequireMethod(finderType, "GetPlacements", new string[] { fType.Name }, false);
                List<object> boxes = new List<object>();
                foreach (object o in (IEnumerable)Call(get, finder, new object[] { Activator.CreateInstance(fType) }))
                    if (o != null && o.GetType().Name == "MacroBox") boxes.Add(o);
                source = boxes;
            }
            else
            {
                string filterName = KIND == "function" ? "FunctionsFilter"
                    : KIND == "connection" ? "ConnectionsFilter" : "PagesFilter";
                string getter = KIND == "function" ? "GetFunctions"
                    : KIND == "connection" ? "GetConnections" : "GetPages";
                Type fType = FindType("Eplan.EplApi.DataModel." + filterName);
                MethodInfo get = RequireMethod(finderType, getter, new string[] { fType.Name }, false);
                source = (IEnumerable)Call(get, finder, new object[] { Activator.CreateInstance(fType) });
            }
            if (source == null) throw new Exception("No objects returned for kind " + KIND + ".");

            object ds = null;
            MethodInfo update = null;
            if (updateFromPart && !dryRun)
            {
                Type dsType = FindType("Eplan.EplApi.HEServices.DeviceService");
                ds = Activator.CreateInstance(dsType);
                update = RequireMethod(dsType, "UpdateDevice", new string[] { "StorableObject" }, false);
            }

            List<object> items = new List<object>();
            int total = 0, matched = 0, changed = 0, failed = 0;
            foreach (object obj in source)
            {
                if (obj == null) continue;
                total++;
                bool ok = true;
                for (int i = 0; i < wProp.Length && ok; i++)
                    ok = Passes(obj, project, wProp[i], wOp[i], wVal[i]);
                if (!ok) continue;
                matched++;

                Dictionary<string, object> d = new Dictionary<string, object>();
                d["type"] = obj.GetType().Name;
                d["name"] = PropText(obj, "Name");
                object pg = TryRead(obj, "Page", null);
                d["page"] = pg == null ? null : PropText(pg, "Name");
                d["handle"] = Handle(obj);

                Dictionary<string, object> vals = new Dictionary<string, object>();
                foreach (string r in readSpecs) vals[r] = ReadText(obj, project, r);
                if (readSpecs.Length > 0) d["values"] = vals;

                List<object> changes = new List<object>();
                bool objFailed = false;
                if (updateFromPart)
                {
                    string res = "dry_run";
                    if (!dryRun)
                    {
                        try { res = (bool)Call(update, ds, new object[] { obj }) ? "updated" : "no article references"; }
                        catch (Exception ex) { res = "ERROR: " + Flatten(ex); objFailed = true; }
                    }
                    d["update_from_part"] = res;
                }
                for (int i = 0; i < setSpecs.Length; i++)
                {
                    Dictionary<string, object> c = new Dictionary<string, object>();
                    c["prop"] = setSpecs[i];
                    c["before"] = ReadText(obj, project, setSpecs[i]);
                    c["wanted"] = setVals[i];
                    if (!dryRun)
                    {
                        try
                        {
                            // Placements (macro boxes) refuse a write unless locked first:
                            // "The object has not been locked before a write access."
                            MethodInfo lockObj = MethodByShape(obj.GetType(), "LockObject", new string[] { }, false);
                            if (lockObj != null) Call(lockObj, obj, new object[] { });
                            object pv = PropValue(obj, project, setSpecs[i]);
                            Call(RequireMethod(pv.GetType(), "Set", new string[] { "String" }, false),
                                 pv, new object[] { setVals[i] });
                            // Fresh read proves the write reached the object.
                            c["after"] = ReadText(obj, project, setSpecs[i]);
                        }
                        catch (Exception ex) { c["error"] = Flatten(ex); objFailed = true; }
                    }
                    changes.Add(c);
                }
                if (setSpecs.Length > 0) d["changes"] = changes;
                if (objFailed) failed++;
                else if (!dryRun && (updateFromPart || setSpecs.Length > 0)) changed++;

                if (items.Count < LIMIT) items.Add(d);
            }

            results["success"] = failed == 0;
            results["kind"] = KIND;
            results["dry_run"] = dryRun;
            results["total"] = total;
            results["matched"] = matched;
            results["returned"] = items.Count;
            results["truncated"] = matched > items.Count;
            results["changed"] = changed;
            results["failed"] = failed;
            results["objects"] = items;
'''


def _run(name, body, timeout_seconds, extra=""):
    return _execute_script(
        _script(name + "_" + uuid.uuid4().hex[:6], body, extra_helpers=_HELPERS + extra),
        timeout=timeout_seconds,
    )


def live_objects_read(kind: str, where: list = None, read: list = None, limit: int = 100,
                      timeout_seconds: float = 300.0, project: str = None) -> dict:
    """
    Find objects in the project open in EPLAN and read any of their properties.
    READ-ONLY.

    Args:
        kind: "function" (devices, cables, terminals...), "connection",
            "page" or "macrobox". For the current selection use
            eplan_get_property.
        where: Optional filter, a list of {"prop", "op", "value"} that must all
            hold. ops: eq, ne, contains (case-insensitive), startswith, regex,
            empty, notempty. Example: [{"prop": "partNr", "op": "eq",
            "value": "#6-CU-STRANDED-UNSHIELDED-GN"}].
        read: Property specs to read: "31002" (id), "20901:2" (id:index),
            "Acme.Fn.Lbl.CP01.T01.L" (user-defined, by name), or the pseudo
            props name / page / type / handle / partNr / area. A property that
            does not apply to an object reads as "ERROR: ...".
        limit: Max objects returned (default 100); "matched" is the true total.
        timeout_seconds: Default 300 - a project-wide walk is not fast.
        project: An OPEN project by name or path (.elk optional). Default: the
            project with GUI focus, which is whatever the user last clicked.

    Returns:
        {"success", "total", "matched", "returned", "truncated", "objects": [
         {"type", "name", "page", "handle", "values": {spec: text}}]}
    """
    err, where, read, limit = _validate(kind, where, read, limit)
    if err:
        return err
    return _run("LiveObjectsRead", _body(kind, where, read, {}, False, True, limit, project),
                timeout_seconds)


def live_objects_edit(kind: str, where: list = None, set: dict = None,
                      update_from_part: bool = False, read: list = None,
                      dry_run: bool = True, limit: int = 500,
                      timeout_seconds: float = 300.0, project: str = None,
                      allow_real_project: bool = False) -> dict:
    """
    Find objects in the open project and write their properties and/or
    re-apply their part data. dry_run=True (default) changes nothing and shows
    each "before" and "wanted" value.

    Writes land on EPLAN's undo stack and are not saved until the project is.

    update_from_part runs DeviceService.UpdateDevice on each matched object:
    it re-applies master part data, which parts synchronization alone does
    not (sync refreshes only the project's stored part copy). It takes a
    device's MAIN function, a whole cable, or a single connection - never one
    core inside a cable - and empty part values do not overwrite filled ones.
    Run eplan_generate_connections afterwards if a cable-core connection still
    shows the old value.

    Args:
        kind, where, read, project: as live_objects_read. An edit without a
            where clause touches EVERY object of the kind - narrow it first.
            Macro boxes: {"23001": "<dir>\\<file>.ema"} repoints a box,
            {"23011": "2"} makes it Referencing (1 Defining, 3 Subordinate);
            filter one box by {"prop": "area", "op": "eq", ...}.
        set: {property spec: new text}, e.g. {"31002": "6"}. Pseudo props
            (name, page, ...) are not writable here.
        update_from_part: Re-apply part data (see above), before any `set`.
        dry_run: True (default) previews only.
        limit: Max objects listed (default 500). Every match is still edited.
        timeout_seconds: Default 300.
        allow_real_project: Must be True to write to a project outside the scratch
            root (eplan_scratch_project_create), like every other live writer. Checked
            inside EPLAN against the project the edit really lands in. Ignored on a
            dry run, which writes nothing.

    Returns:
        As live_objects_read, plus "changed", "failed", and per object
        "changes" [{"prop", "before", "wanted", "after"|"error"}] and
        "update_from_part" ("dry_run" | "updated" | "no article references" |
        "ERROR: ...").
    """
    set_props = set or {}
    if not isinstance(set_props, dict):
        return {"success": False, "error": "set must be a {property spec: value} dict."}
    pseudo = {"name", "page", "type", "handle", "partNr", "area"}
    if pseudo & {str(k) for k in set_props}:
        return {"success": False, "error": f"Pseudo properties {sorted(pseudo)} cannot be set."}
    if not set_props and not update_from_part:
        return {"success": False, "error": "Nothing to do: pass set and/or update_from_part."}
    err, where, read, limit = _validate(kind, where, read, limit)
    if err:
        return err
    set_props = {str(k): "" if v is None else str(v) for k, v in set_props.items()}
    from .schematic import _GUARD_SCRATCH_CS, _guard_prelude
    guard = None if dry_run else _guard_prelude(allow_real_project)
    return _run("LiveObjectsEdit",
                _body(kind, where, read, set_props, update_from_part, dry_run, limit, project,
                      guard=guard),
                timeout_seconds, extra="" if dry_run else _GUARD_SCRATCH_CS)
