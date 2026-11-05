"""
Tools built on API members that are NEW in EPLAN 2027.

Found by diffing the public metadata of the 2026.0.3 and 2027.0.3 API
assemblies. Each new member is reached by REFLECTION, never named statically in
the generated C#. A static reference to a member that does not exist fails to
compile on an older EPLAN, and a compile error inside EPLAN's script engine
reaches the caller only as "Timeout waiting for script results". Through
reflection, an older EPLAN gets a clear "new in 2027" error instead.

    live_read_terminal_jumpers     Terminal.GetJumpers(bool)              (read)
    parts_db_export_edz            MDPartsDatabase.ExportPartsToEDZ(...)  (writes a file)
    remove_unused_user_properties  Project / MDPartsDatabase
                                   .RemoveUnusedUserPropertyDefinitions() (write, guarded)

The project-side tools ride live.py's reflection scaffold (LockingStep,
FindType, the *Netu-first assembly lookup); the parts-database tools open the
database through MDPartsManagement like scripted.py's parts_db_* tools.
"""

import uuid

from ._base import cs_escape
from .live import _script
from .scripted import _execute_script
from .schematic import _HELPERS_SCHEMATIC, _guard_prelude, _fill
from .schematic_model import cs_bool


_RESULT_TOKEN = "{{RESULT_PATH}}"


def _int_arg(value, name, minimum=1):
    """An integer bound for C# source OUTSIDE a string literal - so it must be real."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}: {value!r}. Must be an integer.")
    if out < minimum:
        raise ValueError(f"Invalid {name}: {out}. Must be >= {minimum}.")
    return out


def _text_arg(value, name):
    """A string bound for a C# string literal (escaped by the caller)."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}.")
    if _RESULT_TOKEN in value:
        raise ValueError(
            f"{name} must not contain {_RESULT_TOKEN}: the script runner replaces "
            "that token across the whole script."
        )
    return value


# =============================================================================
# Terminal jumpers
# =============================================================================


def live_read_terminal_jumpers(contains: str = None, all_levels: bool = True,
                               limit: int = 200,
                               timeout_seconds: float = 120.0) -> dict:
    """
    List the jumpers (bridges) between terminals in the project open in EPLAN.

    Uses Terminal.GetJumpers(allLevels), which is new in EPLAN 2027. Each jumper
    is reported once, even though every terminal it touches returns it, with
    its kind (Intern, Extern, Small, Saddleslot_3..5, Undetermined), its type
    (the function-definition tag of its connections, -1 when mixed), the
    terminals it connects, and its individual segments.

    Use it to check terminal strips against a design rule or a review remark
    ("X1:3 and X1:4 must be bridged"), without exporting a terminal diagram.

    Args:
        contains: Optional case-insensitive substring filter on the terminal's
            full name, e.g. "-X1" for one strip or "-X1:1" for one terminal.
            Only the terminals that pass the filter are asked for their
            jumpers. A jumper is still reported whole, so it can list
            terminals the filter excluded.
        all_levels: For multi-level terminals, True (default) returns the
            jumpers of every level of the terminal device; False only those
            of the matched level.
        limit: Max distinct jumpers to return (default 200).
        timeout_seconds: Max seconds to wait (default 120): a large project
            has thousands of terminals, and each is asked for its jumpers.

    Returns:
        dict with "jumpers" (each: kind, type, terminals, segments ->
        [{bridged_terminal, kind}], seen_from), "terminals_matched",
        "terminals_with_jumpers", "returned", "truncated".
        On EPLAN versions before 2027 the call fails with a message naming
        the missing API.
    """
    try:
        limit = _int_arg(limit, "limit")
        contains = _text_arg(contains or "", "contains")
    except ValueError as e:
        return {"success": False, "error": str(e)}

    body = '''            Type finderType = FindType("Eplan.EplApi.DataModel.DMObjectsFinder");
            object finder = Activator.CreateInstance(finderType, new object[] { project });
            // GetTerminals takes one filter argument; null means "all terminals"
            // (that is how EPLAN's own TerminalStripCache example calls it).
            MethodInfo getTerms = RequireMethod(finderType, "GetTerminals", new string[] { "" }, false);
            IEnumerable terms = (IEnumerable)Call(getTerms, finder, new object[] { null });

            List<Dictionary<string, object>> jumpers = new List<Dictionary<string, object>>();
            Dictionary<string, bool> seen = new Dictionary<string, bool>();
            MethodInfo getJumpers = null;
            int matched = 0;
            int withJumpers = 0;
            bool truncated = false;

            foreach (object t in terms)
            {
                if (t == null) continue;
                string tn = PropText(t, "Name");
                if (!Matches(tn, "CONTAINS")) continue;
                matched++;

                if (getJumpers == null)
                {
                    getJumpers = MethodByShape(t.GetType(), "GetJumpers", new string[] { "Boolean" }, false);
                    if (getJumpers == null)
                        throw new Exception("Terminal.GetJumpers(bool) is not available in this " +
                            "EPLAN: it is new in EPLAN 2027. " + MemberList(t.GetType(), true));
                }

                IEnumerable bridges = Call(getJumpers, t, new object[] { ALL_LEVELS }) as IEnumerable;
                if (bridges == null) continue;

                bool any = false;
                foreach (object br in bridges)
                {
                    if (br == null) continue;
                    any = true;

                    List<string> tnames = new List<string>();
                    IEnumerable bts = TryRead(br, "Terminals", null) as IEnumerable;
                    if (bts != null)
                    {
                        foreach (object x in bts)
                        {
                            string s = x == null ? null : PropText(x, "Name");
                            if (s != null && !tnames.Contains(s)) tnames.Add(s);
                        }
                    }
                    tnames.Sort(StringComparer.Ordinal);
                    string kind = SafeText(TryRead(br, "Kind", null));
                    string key = kind + "|" + string.Join("|", tnames.ToArray());
                    if (seen.ContainsKey(key)) continue;
                    seen[key] = true;
                    if (jumpers.Count >= LIMIT) { truncated = true; continue; }

                    Dictionary<string, object> d = new Dictionary<string, object>();
                    d["kind"] = kind == null ? "" : kind;
                    object jt = TryRead(br, "Type", null);
                    d["type"] = jt == null ? null : (object)Convert.ToInt32(jt);
                    d["terminals"] = tnames;
                    d["seen_from"] = tn == null ? "" : tn;

                    // BridgeSegments, Term, BridgedTerminal and Kind are public
                    // FIELDS, not properties - TryRead would never see them.
                    List<Dictionary<string, object>> segs = new List<Dictionary<string, object>>();
                    FieldInfo segField = br.GetType().GetField("BridgeSegments");
                    IEnumerable segArr = segField == null ? null : segField.GetValue(br) as IEnumerable;
                    if (segArr != null)
                    {
                        foreach (object seg in segArr)
                        {
                            if (seg == null) continue;
                            Dictionary<string, object> sd = new Dictionary<string, object>();
                            FieldInfo otherF = seg.GetType().GetField("BridgedTerminal");
                            object other = otherF == null ? null : otherF.GetValue(seg);
                            sd["bridged_terminal"] = other == null ? null : PropText(other, "Name");
                            FieldInfo kindF = seg.GetType().GetField("Kind");
                            sd["kind"] = kindF == null ? null : SafeText(kindF.GetValue(seg));
                            segs.Add(sd);
                        }
                    }
                    d["segments"] = segs;
                    jumpers.Add(d);
                }
                if (any) withJumpers++;
            }

            results["success"] = true;
            results["terminals_matched"] = matched;
            results["terminals_with_jumpers"] = withJumpers;
            results["returned"] = jumpers.Count;
            results["truncated"] = truncated;
            results["jumpers"] = jumpers;
'''
    # ONE-pass substitution (schematic._fill): a caller value that happens to
    # contain a token name can never be rewritten by a later replacement.
    body = _fill(body, CONTAINS=cs_escape(contains),
                 ALL_LEVELS=cs_bool(all_levels), LIMIT=str(limit))
    return _execute_script(
        _script("LiveJumpers_" + uuid.uuid4().hex[:6], body),
        timeout=timeout_seconds,
    )


# =============================================================================
# Parts database: export selected parts to EDZ
# =============================================================================


_PARTS_FLATTEN = '''
    static string Flatten(Exception ex)
    {
        var sb = new System.Text.StringBuilder();
        Exception e = ex;
        int depth = 0;
        while (e != null && depth < 6)
        {
            if (sb.Length > 0) sb.Append(" <- ");
            sb.Append(e.GetType().Name).Append(": ").Append(e.Message);
            e = e.InnerException;
            depth++;
        }
        return sb.ToString();
    }

    static MethodInfo FindMethod(object target, string name, int paramCount)
    {
        foreach (MethodInfo m in target.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance))
            if (m.Name == name && m.GetParameters().Length == paramCount) return m;
        return null;
    }

    static object Invoke(MethodInfo mi, object target, object[] args)
    {
        try { return mi.Invoke(target, args); }
        catch (TargetInvocationException tie) { throw new Exception(mi.Name + ": " + Flatten(tie.InnerException)); }
    }
'''


def parts_db_export_edz(part_numbers: list, file_path: str,
                        include_references: bool = True) -> dict:
    """
    Export specific parts from the parts database to an EDZ file.

    Uses MDPartsDatabase.ExportPartsToEDZ, which is new in EPLAN 2027. Unlike
    eplan_partsmanagement_export (the whole database, or a property filter),
    this exports exactly the parts you name, e.g. the result of
    parts_db_query. With include_references=True the EDZ also carries what the
    parts reference (macros, pictures, connection point patterns, drilling
    patterns, accessories), so the file can be imported elsewhere as is.

    Args:
        part_numbers: Exact part numbers (MDPart.PartNr). All variants of each
            part number are exported. Unknown numbers are reported in
            "missing" rather than failing the export.
        file_path: Full path of the .edz file to write, as seen by the EPLAN
            machine. The directory must already exist.
        include_references: Also export the parts' referenced data (default
            True).

    Returns:
        dict with "exported_parts" ("PartNr / Variant"), "missing",
        "file_path", "file_exists", "file_size_bytes". On EPLAN versions
        before 2027 the call fails with a message naming the fallback tool.
    """
    if isinstance(part_numbers, str):
        part_numbers = [part_numbers]
    if not part_numbers or not isinstance(part_numbers, (list, tuple)):
        return {"success": False, "error": "part_numbers must be a non-empty list of part numbers."}
    try:
        part_numbers = [_text_arg(p, "part_numbers entry") for p in part_numbers]
        file_path = _text_arg(file_path, "file_path")
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not file_path.lower().endswith(".edz"):
        return {"success": False, "error": f"file_path must end in .edz, got {file_path!r}."}

    wanted = ", ".join('"%s"' % cs_escape(p) for p in part_numbers)
    script = '''using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using Eplan.EplApi.MasterData;
using Eplan.EplApi.Scripting;

public class CLASSNAME
{
''' + _PARTS_FLATTEN + '''
    [Start]
    public void Run()
    {
        var results = new Dictionary<string, object>();
        string path = "PATH";
        try
        {
            string[] wanted = new string[] { WANTED };
            var wantedSet = new HashSet<string>(wanted, StringComparer.Ordinal);
            var mdParts = new MDPartsManagement();
            using (var db = mdParts.OpenDatabase())
            {
                var parts = db.Parts.Where(p => wantedSet.Contains(p.PartNr)).ToList();
                var found = new HashSet<string>(parts.Select(p => p.PartNr), StringComparer.Ordinal);
                results["missing"] = wanted.Where(w => !found.Contains(w)).Distinct().ToList();
                results["exported_parts"] = parts.Select(p => p.PartNr + " / " + p.Variant).ToList();
                if (parts.Count == 0)
                    throw new Exception("None of the requested part numbers exist in the parts database.");

                MethodInfo mi = FindMethod(db, "ExportPartsToEDZ", 3);
                if (mi == null)
                    throw new Exception("MDPartsDatabase.ExportPartsToEDZ is not available in this EPLAN: " +
                        "it is new in EPLAN 2027. On older versions use eplan_partsmanagement_export " +
                        "with format=IXPartsImportExportEdz.");
                object ok = Invoke(mi, db, new object[] { path, parts, INCLUDE_REFS });

                var fi = new FileInfo(path);
                results["export_returned"] = ok;
                results["file_path"] = path;
                results["file_exists"] = fi.Exists;
                if (fi.Exists) results["file_size_bytes"] = fi.Length;
                results["success"] = (ok is bool) && (bool)ok && fi.Exists;
                if (!(bool)results["success"])
                    results["error"] = "ExportPartsToEDZ returned " + Convert.ToString(ok) +
                        " and the file " + (fi.Exists ? "exists" : "was not written") + ".";
            }
        }
        catch (Exception ex)
        {
            results["success"] = false;
            results["error"] = Flatten(ex);
        }
        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented);
        File.WriteAllText(@"{{RESULT_PATH}}", json);
    }
}
'''
    script = _fill(script, CLASSNAME="PartsEdz_" + uuid.uuid4().hex[:6],
                   PATH=cs_escape(file_path), WANTED=wanted,
                   INCLUDE_REFS=cs_bool(include_references))
    return _execute_script(script, timeout=120.0)


# =============================================================================
# Remove unused user-defined property definitions
# =============================================================================


_PROJECT_UDP_BODY = '''GUARD
            IEnumerable defs = TryRead(project, "UserDefinedPropertyDefinitions", null) as IEnumerable;
            List<string> before = new List<string>();
            List<Dictionary<string, object>> details = new List<Dictionary<string, object>>();
            if (defs != null)
            {
                foreach (object d in defs)
                {
                    if (d == null) continue;
                    string n = SafeText(TryRead(d, "IdentifyingName", null));
                    if (n == null) continue;
                    before.Add(n);
                    Dictionary<string, object> dd = new Dictionary<string, object>();
                    dd["name"] = n;
                    object assigned = TryRead(d, "IsAssigned", null);
                    if (assigned != null) dd["is_assigned"] = assigned;
                    details.Add(dd);
                }
            }
            results["definitions_before"] = before.Count;

            if (CONFIRM)
            {
                MethodInfo rm = MethodByShape(project.GetType(), "RemoveUnusedUserPropertyDefinitions",
                    new string[] { }, false);
                if (rm == null)
                    throw new Exception("Project.RemoveUnusedUserPropertyDefinitions() is not available in " +
                        "this EPLAN: it is new in EPLAN 2027.");
                Call(rm, project, new object[] { });

                List<string> after = new List<string>();
                IEnumerable defs2 = TryRead(project, "UserDefinedPropertyDefinitions", null) as IEnumerable;
                if (defs2 != null)
                    foreach (object d in defs2)
                    {
                        string n = d == null ? null : SafeText(TryRead(d, "IdentifyingName", null));
                        if (n != null) after.Add(n);
                    }
                results["definitions_after"] = after.Count;
                results["removed"] = before.Where(b => !after.Contains(b)).ToList();
            }
            else
            {
                results["definitions"] = details;
            }
            results["success"] = true;
'''


def remove_unused_user_properties(target: str = "project", confirm: bool = False,
                                  allow_real_project: bool = False) -> dict:
    """
    Remove user-defined property definitions that nothing uses any more.

    Uses RemoveUnusedUserPropertyDefinitions(), new in EPLAN 2027, on either
    the open project or the system parts database. Over time both build up
    definitions for properties that no object carries any more. They clutter
    the property dialogs and reports.

    SAFE BY DEFAULT: without confirm=True this only LISTS the definitions (with
    "is_assigned" where EPLAN reports it) and removes nothing. EPLAN alone
    decides which definitions are unused, so the listing is a preview, not a
    prediction. With confirm=True it removes them and reports exactly which
    names disappeared. For target="project", the write is also refused
    outside the scratch root unless allow_real_project=True (the same guard
    as the schematic tools).

    Args:
        target: "project" (the project open in EPLAN) or "parts_db" (the
            system parts database).
        confirm: True to actually remove. Default False only lists.
        allow_real_project: Required (with confirm) to clean a project outside
            the scratch root. Ignored for target="parts_db".

    Returns:
        dict with "definitions_before" and either "definitions" (preview) or
        "definitions_after" + "removed" (after a confirmed run).
    """
    target = (target or "").strip().lower()
    if target not in ("project", "parts_db"):
        return {"success": False,
                "error": f"target must be 'project' or 'parts_db', got {target!r}."}

    if target == "project":
        guard = _guard_prelude(allow_real_project) if confirm else ""
        body = _fill(_PROJECT_UDP_BODY, GUARD=guard, CONFIRM=cs_bool(confirm))
        # Needs System.Linq for the Where/ToList in the body.
        script = _script("RmUdp_" + uuid.uuid4().hex[:6], body,
                         extra_helpers=_HELPERS_SCHEMATIC)
        script = script.replace("using System.Collections.Generic;\n",
                                "using System.Collections.Generic;\nusing System.Linq;\n", 1)
        result = _execute_script(script, timeout=90.0)
    else:
        script = '''using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Collections.Generic;
using Eplan.EplApi.MasterData;
using Eplan.EplApi.Scripting;

public class CLASSNAME
{
''' + _PARTS_FLATTEN + '''
    static List<string> Names(object db)
    {
        var names = new List<string>();
        PropertyInfo pi = db.GetType().GetProperty("UserDefinedPropertyDefinitions");
        IEnumerable defs = pi == null ? null : pi.GetValue(db, null) as IEnumerable;
        if (defs == null) return names;
        foreach (object d in defs)
        {
            if (d == null) continue;
            PropertyInfo np = d.GetType().GetProperty("IdentifyingName");
            object v = np == null ? null : np.GetValue(d, null);
            if (v != null) names.Add(v.ToString());
        }
        return names;
    }

    [Start]
    public void Run()
    {
        var results = new Dictionary<string, object>();
        try
        {
            var mdParts = new MDPartsManagement();
            using (var db = mdParts.OpenDatabase())
            {
                var before = Names(db);
                results["definitions_before"] = before.Count;
                if (CONFIRM)
                {
                    MethodInfo mi = FindMethod(db, "RemoveUnusedUserPropertyDefinitions", 0);
                    if (mi == null)
                        throw new Exception("MDPartsDatabase.RemoveUnusedUserPropertyDefinitions() is not " +
                            "available in this EPLAN: it is new in EPLAN 2027.");
                    Invoke(mi, db, new object[] { });
                    var after = Names(db);
                    results["definitions_after"] = after.Count;
                    results["removed"] = before.Where(b => !after.Contains(b)).ToList();
                }
                else
                {
                    results["definitions"] = before;
                }
                results["success"] = true;
            }
        }
        catch (Exception ex)
        {
            results["success"] = false;
            results["error"] = Flatten(ex);
        }
        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented);
        File.WriteAllText(@"{{RESULT_PATH}}", json);
    }
}
'''
        script = _fill(script, CLASSNAME="RmMdUdp_" + uuid.uuid4().hex[:6],
                       CONFIRM=cs_bool(confirm))
        result = _execute_script(script, timeout=90.0)

    if isinstance(result, dict):
        result.setdefault("target", target)
        result.setdefault("mode", "removed" if confirm else "preview (nothing removed)")
    return result
