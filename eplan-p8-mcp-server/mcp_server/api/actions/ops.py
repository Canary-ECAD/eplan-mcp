"""
Batched page operations - many edits per EPLAN round-trip, by name, with proof.

Why. Each live_* tool compiles and runs one C# script inside EPLAN, which
costs seconds per call. Building a small panel - a dozen placements, their
tags, parts and dimensions - took eighty-odd scripts, and every object was
addressed by a session handle that stopped being valid when EPLAN restarted.
This module fixes both:

    live_batch                  a LIST of operations in ONE script
    live_find_placements        objects by device tag, not by handle
    live_place_device           place + tag + part + properties in one go
    live_insert_macro           a window macro, by insertion point or top-left
    live_place_panel_item       a part on the panel: its macro, or a rectangle
    live_place_plc_point        a PLC connection point with its definition
    live_place_terminal         a terminal with its strip and number
    live_update_placement       tag / part / properties on an existing object
    live_render_page            the page as a PNG, to look at
    live_check_page             check run + messages + overlapping objects

THE INTERPRETER. One fixed C# program (built from live.py's and schematic.py's
helpers plus the op implementations below) reads a JSON request - page, ops -
and writes a JSON result. Every op addresses objects by `ref`, which is a
session handle ("124/17/1201/0"), a device tag ("=+CE-K1"), or "$label" for the
object an earlier op in the same batch created.

REGISTERED, NOT RECOMPILED - FOR READS. The same C# declares an EPLAN action
([DeclareAction]) named after a hash of its own source. The first read of a
session registers it with RegisterScript; later reads call the action with
two file paths and skip the compile. If EPLAN was restarted, or the action
does not answer (no ".started" marker within a few seconds), the request
falls back to a one-shot ExecuteScript of the same source, which also
surfaces compile errors through scripted._execute_script.
EPLAN_MCP_OPS_MODE=script forces the one-shot path for everything.

Writes always take the one-shot path. Measured on 2026.0.3: inside the
registered action every write lock fails with
LockingExceptionFailedLockAttempt - Function.Create, and LockObject itself -
while the identical source run through ExecuteScript succeeds; the action
runs outside the context that owns the project's locks. The compile it
saves is small anyway: a read answered in 0.3 s registered and 0.5 s as a
one-shot, so the cost of a batch is its work, not its compile.

MEASURED ON EPLAN 2026.0.3 (the facts the ops encode):
- Function.Create(Page, SymbolVariant, PointD, PointD) throws
  NotImplementedException for terminals and PLC connection points; the
  2-arg Create(Page, SymbolVariant) followed by Location works. `place`
  tries the 4-arg form and falls back, reporting the route it took.
- A placed function's tag shows only once VisibleName is set; setting it to
  "CE-K1" inside location +CE yields "=+CE-CE-K1", so the default visible
  name is the tag from its first "-".
- A PLC point's role is its FunctionDefinition (category PLCTerminal; group/
  id 1/2 DI, 1/3 DO, 3/5 PS+, 3/6 PS M, 2/5 CPS+, 2/6 CPS M).
- Insert.WindowMacro(string, RepresentationType, int, Page, PointD, MoveKind)
  returns every created placement. A panel macro's functions sit inside a
  Group, so `remove` on a group removes its sub-placements first.
- Panel parts without a 2D macro are a SPECIAL/PANP rectangle created with
  its two corners (top-left, bottom-right) plus RECTANGLE_WIDTH/HEIGHT.
"""

import hashlib
import json
import os
import re
import time
import uuid

from ._base import cs_escape, _get_connected_manager
from . import live, schematic, scripted, target
from .fixtures import SCRATCH_ROOT
from .schematic_model import SchematicValueError, cs_text

__all__ = [
    "live_batch",
    "live_find_placements",
    "live_place_device",
    "live_insert_macro",
    "live_place_panel_item",
    "live_place_plc_point",
    "live_place_terminal",
    "live_update_placement",
    "live_render_page",
    "live_check_page",
]

# Directory for the registered interpreter script and the per-batch request
# files; results go to scripted.RESULTS_DIR like every other script's.
OPS_DIR = os.path.join(scripted._MCP_ROOT, "scripts", "ops")

# How long to wait for the registered action to acknowledge a request before
# deciding it is not registered (EPLAN restarted, registration refused).
STARTED_TIMEOUT_S = 4.0

# PLC connection point roles -> FunctionDefinition (group, id) in category
# PLCTerminal. Measured on the Siemens S7-1200 Data Portal macro.
PLC_POINT_KINDS = {
    "DI": (1, 2), "DO": (1, 3),
    "PS+": (3, 5), "PS-": (3, 6),
    "CPS+": (2, 5), "CPS-": (2, 6),
}

_HANDLE_RE = re.compile(r"^\d+/\d+/\d+/\d+$")

# Hashes of interpreter sources this process has registered in EPLAN, keyed by
# the EPLAN connection generation they were registered under.
_registered = set()


_HEADER = '''using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Reflection;
using System.Collections;
using System.Collections.Generic;
using Eplan.EplApi.Base;
using Eplan.EplApi.Scripting;
using Newtonsoft.Json.Linq;

public class '''


_OPS_HELPERS = r'''
    // ---- request access ----------------------------------------------------
    static bool Has(JObject o, string k)
    {
        if (o == null) return false;
        JToken t;
        return o.TryGetValue(k, out t) && t.Type != JTokenType.Null;
    }
    static string S(JObject o, string k, string def) { return Has(o, k) ? (string)o[k] : def; }
    static double D(JObject o, string k, double def) { return Has(o, k) ? (double)o[k] : def; }
    static int I(JObject o, string k, int def) { return Has(o, k) ? (int)o[k] : def; }
    static bool B(JObject o, string k, bool def) { return Has(o, k) ? (bool)o[k] : def; }
    static string Req(JObject o, string k)
    {
        if (!Has(o, k)) throw new Exception("Missing argument '" + k + "'.");
        return (string)o[k];
    }

    static readonly Regex HANDLE_RE = new Regex(@"^\d+/\d+/\d+/\d+$");

    // Objects that can carry a device tag and a part.
    static bool IsDevice(object o)
    {
        return o != null && GetReadable(o.GetType(), "ArticleReferences") != null
            && GetWritable(o.GetType(), "Name") != null;
    }

    static string VisibleNameOf(object o)
    {
        try { object v = TryRead(o, "VisibleName", null); return v == null ? null : v.ToString(); }
        catch { return null; }
    }

    // ---- ref -> object: handle, "$label", or device tag -------------------
    static object Resolve(object page, string r, Dictionary<string, string> labels)
    {
        if (string.IsNullOrEmpty(r)) throw new Exception("'ref' is required: a handle, a device tag, or $label.");
        if (r.StartsWith("$"))
        {
            string label = r.Substring(1);
            if (!labels.ContainsKey(label))
                throw new Exception("No earlier op in this batch is labelled '" + label + "'.");
            return ResolveOnPage(page, labels[label]);
        }
        if (HANDLE_RE.IsMatch(r)) return ResolveOnPage(page, r);

        List<object> hits = new List<object>();
        foreach (object pl in PagePlacements(page))
        {
            if (pl == null) continue;
            string n = PropText(pl, "Name");
            if (n == r || VisibleNameOf(pl) == r) hits.Add(pl);
        }
        if (hits.Count == 1) return hits[0];
        if (hits.Count == 0)
            throw new Exception("No placement named '" + r + "' on page '" + PropText(page, "Name") +
                "'. Names are device tags as EPLAN stores them (e.g. =+CE-K1); use live_find_placements to list them.");
        List<string> hs = new List<string>();
        foreach (object h in hits) hs.Add(h.GetType().Name + "=" + Handle(h));
        throw new Exception(hits.Count + " placements are named '" + r + "' on this page; address one by handle: " +
            string.Join(" | ", hs.ToArray()));
    }

    // A project that is open but NOT the GUI's current one hands out objects
    // the LockingStep alone has not locked for writing: Function.Create on
    // its page throws LockingException ("object not locked for write
    // access"). LockObject() takes the write lock explicitly; it is a no-op
    // on an object already locked.
    static void Lock(object o)
    {
        if (o == null) return;
        MethodInfo lo = MethodByShape(o.GetType(), "LockObject", new string[] { }, false);
        if (lo == null) return;
        try { lo.Invoke(o, null); }
        catch (TargetInvocationException tie) { throw new Exception("LockObject: " + Flatten(tie.InnerException)); }
    }

    // The boxes of a placement's displayed texts (device tag, part number,
    // function text, connection designations...). PropertyPlacement
    // bounding boxes are RELATIVE to the owner's Location (measured: a rail's
    // caption at +112..127 of a rail placed at x=170 sits at x=282..297, the
    // rail's middle). Unplaced properties report a zero box and are skipped.
    static List<object> TextBoxes(object pl)
    {
        List<object> boxes = new List<object>();
        object pps = TryRead(pl, "PropertyPlacements", null);
        if (pps == null) return boxes;
        double lx = 0, ly = 0;
        object loc = TryRead(pl, "Location", null);
        if (loc != null)
        {
            Dictionary<string, object> ld = PtDict(loc);
            if (ld["x"] != null && ld["y"] != null) { lx = Convert.ToDouble(ld["x"]); ly = Convert.ToDouble(ld["y"]); }
        }
        foreach (object pp in (IEnumerable)pps)
        {
            if (pp == null) continue;
            MethodInfo bb = MethodByShape(pp.GetType(), "GetBoundingBox", new string[] { }, false);
            if (bb == null) continue;
            try
            {
                double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
                foreach (object p in (IEnumerable)bb.Invoke(pp, null))
                {
                    Dictionary<string, object> d = PtDict(p);
                    if (d["x"] == null || d["y"] == null) continue;
                    double x = Convert.ToDouble(d["x"]), y = Convert.ToDouble(d["y"]);
                    x0 = Math.Min(x0, x); x1 = Math.Max(x1, x); y0 = Math.Min(y0, y); y1 = Math.Max(y1, y);
                }
                if (x1 - x0 < 1e-6 || y1 - y0 < 1e-6) continue;
                boxes.Add(new double[] { lx + x0, ly + y0, lx + x1, ly + y1 });
            }
            catch { }
        }
        return boxes;
    }

    static double[] BBoxOf(object pl)
    {
        Dictionary<string, object> d = DumpPlacement(pl, false);
        if (!d.ContainsKey("boundingBox")) return null;
        double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
        bool any = false;
        foreach (object c in (IEnumerable)d["boundingBox"])
        {
            Dictionary<string, object> p = c as Dictionary<string, object>;
            if (p == null || p["x"] == null || p["y"] == null) continue;
            double x = Convert.ToDouble(p["x"]), y = Convert.ToDouble(p["y"]);
            if (Math.Abs(x) > 1e6 || Math.Abs(y) > 1e6) continue;
            x0 = Math.Min(x0, x); x1 = Math.Max(x1, x); y0 = Math.Min(y0, y); y1 = Math.Max(y1, y);
            any = true;
        }
        return any ? new double[] { x0, y0, x1, y1 } : null;
    }

    static double[] BBoxOfAll(object[] objs)
    {
        double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
        bool any = false;
        foreach (object o in objs)
        {
            if (o == null) continue;
            double[] b = null;
            try { b = BBoxOf(o); } catch { b = null; }
            if (b == null) continue;
            x0 = Math.Min(x0, b[0]); y0 = Math.Min(y0, b[1]); x1 = Math.Max(x1, b[2]); y1 = Math.Max(y1, b[3]);
            any = true;
        }
        return any ? new double[] { x0, y0, x1, y1 } : null;
    }

    // ---- shared post-steps: tag, part, properties, function definition ----
    static void SetTag(object page, object fn, string tag, string visibleName, bool allowMerge,
                       Dictionary<string, object> r)
    {
        if (!allowMerge)
        {
            List<string> clash = new List<string>();
            string me = Handle(fn);
            foreach (object pl in PagePlacements(page))
            {
                if (pl == null || Handle(pl) == me) continue;
                if (PropText(pl, "Name") == tag) clash.Add(pl.GetType().Name + "=" + Handle(pl));
            }
            if (clash.Count > 0)
                throw new Exception("Device tag " + tag + " is already used on this page by " +
                    string.Join(", ", clash.ToArray()) + "; EPLAN would MERGE this object into that device. " +
                    "Pass allowMerge=true if that is intended.");
        }
        GetWritable(fn.GetType(), "Name").SetValue(fn, tag, null);
        string vis = visibleName;
        if (vis == null)
        {
            int i = tag.IndexOf('-');
            vis = i >= 0 ? tag.Substring(i) : tag;
        }
        if (vis.Length > 0)
        {
            try { GetWritable(fn.GetType(), "VisibleName").SetValue(fn, vis, null); }
            catch (Exception e) { r["visibleNameError"] = Flatten(e); }
        }
        r["name"] = PropText(fn, "Name");
    }

    static void AddPart(object fn, string part, Dictionary<string, object> r)
    {
        object ars = TryRead(fn, "ArticleReferences", null);
        if (ars != null)
            foreach (object ar in (IEnumerable)ars)
                if (PropText(ar, "PartNr") == part) { r["part"] = "already present"; return; }
        MethodInfo add = RequireMethod(fn.GetType(), "AddArticleReference", new string[] { "String" }, false);
        Call(add, fn, new object[] { part });
        r["part"] = part;
    }

    static void SetProps(object fn, JObject props, Dictionary<string, object> r)
    {
        object plist = RequireReadable(fn.GetType(), "Properties").GetValue(fn, null);
        Dictionary<string, object> set = new Dictionary<string, object>();
        foreach (JProperty p in props.Properties())
        {
            string name = p.Name;
            string val = p.Value.Type == JTokenType.Null ? "" : (string)p.Value;
            int idx = -1;
            int b = name.IndexOf('[');
            if (b > 0 && name.EndsWith("]"))
            {
                idx = int.Parse(name.Substring(b + 1, name.Length - b - 2));
                name = name.Substring(0, b);
            }
            if (idx < 0) { set[p.Name] = SetLiveProp(plist, name, val); continue; }
            // "NAME[i]" addresses one slot of a property declared both plain
            // and indexed (FUNC_CONNECTIONDESIGNATION): the indexed getter
            // returns a PropertyValue whose Set(string) writes through.
            PropertyInfo pi = GetPropInfoIdx(plist.GetType(), name);
            if (pi == null)
                throw new Exception("Property list " + plist.GetType().Name + " has no indexed '" + name + "'.");
            object pv = pi.GetValue(plist, new object[] { idx });
            MethodInfo setter = pv.GetType().GetMethod("Set", new Type[] { typeof(string) });
            if (setter == null) throw new Exception("Indexed " + name + " has no Set(string).");
            Call(setter, pv, new object[] { val });
            set[p.Name] = "indexed Set(string)";
        }
        r["properties"] = set;
    }

    static void SetFunctionDefinition(object project, object fn, JObject fd, Dictionary<string, object> r)
    {
        string category = S(fd, "category", "PLCTerminal");
        int group = I(fd, "group", 0), id = I(fd, "id", 0);
        Type fdType = FindType("Eplan.EplApi.DataModel.FunctionDefinition");
        ConstructorInfo ctor = null;
        foreach (ConstructorInfo c in fdType.GetConstructors())
        {
            ParameterInfo[] ps = c.GetParameters();
            if (ps.Length == 4 && ps[1].ParameterType.Name == "FunctionCategory" && ps[2].ParameterType == typeof(short))
                ctor = c;
        }
        if (ctor == null)
            throw new Exception("FunctionDefinition has no (Project, FunctionCategory, short, short) ctor. " +
                MemberList(fdType, true));
        object cat = Enum.Parse(ctor.GetParameters()[1].ParameterType, category);
        object def = ctor.Invoke(new object[] { project, cat, (short)group, (short)id });
        GetWritable(fn.GetType(), "FunctionDefinition").SetValue(fn, def, null);
        r["functionDefinition"] = category + " " + group + "/" + id;
    }

    static void Finish(object project, object page, object fn, JObject a, Dictionary<string, object> r)
    {
        if (Has(a, "functionDefinition")) SetFunctionDefinition(project, fn, (JObject)a["functionDefinition"], r);
        if (Has(a, "tag")) SetTag(page, fn, Req(a, "tag"), S(a, "visibleName", null), B(a, "allowMerge", false), r);
        if (Has(a, "part")) AddPart(fn, Req(a, "part"), r);
        if (Has(a, "properties")) SetProps(fn, (JObject)a["properties"], r);
    }

    // ---- symbols -----------------------------------------------------------
    // A fresh SymbolLibrary + Symbol + SymbolVariant per placement: a variant
    // instance cannot be reused (ObjectAlreadyCreatedException).
    static object MakeVariant(object project, string lib, string sym, int v)
    {
        Type libType = FindType("Eplan.EplApi.DataModel.MasterData.SymbolLibrary");
        Type symType = FindType("Eplan.EplApi.DataModel.MasterData.Symbol");
        Type varType = FindType("Eplan.EplApi.DataModel.MasterData.SymbolVariant");
        ConstructorInfo libCtor = libType.GetConstructor(new Type[] { project.GetType(), typeof(string) });
        if (libCtor == null) throw new Exception("SymbolLibrary has no (Project, string) ctor. " + MemberList(libType, true));
        object library;
        try { library = libCtor.Invoke(new object[] { project, lib }); }
        catch (TargetInvocationException tie) { throw new Exception("Cannot open symbol library " + lib + ": " + Flatten(tie.InnerException)); }
        ConstructorInfo symCtor = symType.GetConstructor(new Type[] { libType, typeof(string) });
        object symbol;
        try { symbol = symCtor.Invoke(new object[] { library, sym }); }
        catch (TargetInvocationException tie) { throw new Exception("No symbol " + sym + " in library " + lib + ": " + Flatten(tie.InnerException)); }
        ConstructorInfo varCtor = varType.GetConstructor(new Type[] { symType, typeof(int) });
        try { return varCtor.Invoke(new object[] { symbol, v }); }
        catch (TargetInvocationException tie) { throw new Exception("No variant " + v + " of " + lib + "/" + sym + ": " + Flatten(tie.InnerException)); }
    }

    static string TypeName(string t)
    {
        if (string.IsNullOrEmpty(t)) return "Eplan.EplApi.DataModel.Function";
        return t.Contains(".") ? t : "Eplan.EplApi.DataModel." + t;
    }

    // ---- ops ---------------------------------------------------------------
    static void OpPlace(object project, object page, JObject a, Dictionary<string, object> r)
    {
        string lib = Req(a, "library"), sym = Req(a, "symbol");
        int v = I(a, "variant", 0);
        double x = D(a, "x", 0), y = D(a, "y", 0);
        if (B(a, "snap", true))
        {
            double grid = 0.0;
            object gv = TryRead(page, "GridSize", null);
            if (gv != null) grid = Convert.ToDouble(gv);
            if (grid > 0.0001) { x = Snap(x, grid); y = Snap(y, grid); }
        }
        double x2 = Has(a, "x2") ? D(a, "x2", x) : x, y2 = Has(a, "y2") ? D(a, "y2", y) : y;
        Type funcType = FindType(TypeName(S(a, "type", null)));
        object variant = MakeVariant(project, lib, sym, v);
        object fn = Activator.CreateInstance(funcType);
        MethodInfo create4 = MethodByShape(funcType, "Create", new string[] { "Page", "SymbolVariant", "PointD", "PointD" }, false);
        string route;
        try
        {
            if (create4 == null) throw new NotImplementedException("no 4-arg Create on " + funcType.Name);
            Type pt = create4.GetParameters()[2].ParameterType;
            Call(create4, fn, new object[] { page, variant, MakePoint(pt, x, y), MakePoint(pt, x2, y2) });
            route = "Create(Page,SymbolVariant,PointD,PointD)";
        }
        catch (Exception ex)
        {
            if (Flatten(ex).IndexOf("NotImplemented", StringComparison.OrdinalIgnoreCase) < 0) throw;
            // Terminals and PLC connection points: only the 2-arg Create is
            // implemented; the object then lands at the origin and is moved.
            variant = MakeVariant(project, lib, sym, v);
            fn = Activator.CreateInstance(funcType);
            MethodInfo create2 = RequireMethod(funcType, "Create", new string[] { "Page", "SymbolVariant" }, false);
            Call(create2, fn, new object[] { page, variant });
            PropertyInfo locPi = RequireWritable(fn.GetType(), "Location");
            locPi.SetValue(fn, MakePoint(locPi.PropertyType, x, y), null);
            route = "Create(Page,SymbolVariant)+Location";
        }
        r["route"] = route;
        r["handle"] = Handle(fn);
        Finish(project, page, fn, a, r);
        r["placed"] = DumpPlacement(fn, true);
    }

    static void OpRect(object project, object page, JObject a, Dictionary<string, object> r)
    {
        string lib = S(a, "library", "SPECIAL"), sym = S(a, "symbol", "PANP");
        double x = D(a, "x", 0), y = D(a, "y", 0), w = D(a, "width", 0), h = D(a, "height", 0);
        if (w <= 0 || h <= 0) throw new Exception("'width' and 'height' must be positive (mm).");
        Type funcType = FindType("Eplan.EplApi.DataModel.Function");
        object variant = MakeVariant(project, lib, sym, I(a, "variant", 0));
        object fn = Activator.CreateInstance(funcType);
        MethodInfo create4 = RequireMethod(funcType, "Create", new string[] { "Page", "SymbolVariant", "PointD", "PointD" }, false);
        Type pt = create4.GetParameters()[2].ParameterType;
        // Corners: top-left and bottom-right of the part's outline.
        Call(create4, fn, new object[] { page, variant, MakePoint(pt, x, y), MakePoint(pt, x + w, y - h) });
        r["handle"] = Handle(fn);
        object plist = RequireReadable(fn.GetType(), "Properties").GetValue(fn, null);
        Dictionary<string, object> size = new Dictionary<string, object>();
        try { size["RECTANGLE_WIDTH"] = SetLiveProp(plist, "RECTANGLE_WIDTH", w.ToString(System.Globalization.CultureInfo.InvariantCulture)); }
        catch (Exception e) { size["RECTANGLE_WIDTH"] = Flatten(e); }
        try { size["RECTANGLE_HEIGHT"] = SetLiveProp(plist, "RECTANGLE_HEIGHT", h.ToString(System.Globalization.CultureInfo.InvariantCulture)); }
        catch (Exception e) { size["RECTANGLE_HEIGHT"] = Flatten(e); }
        if (Has(a, "mountingPlate"))
        {
            try { size["FUNC_ARTICLEPLACEMENT_MOUNTINGPLATE"] = SetLiveProp(plist, "FUNC_ARTICLEPLACEMENT_MOUNTINGPLATE", Req(a, "mountingPlate")); }
            catch (Exception e) { size["FUNC_ARTICLEPLACEMENT_MOUNTINGPLATE"] = Flatten(e); }
        }
        r["size"] = size;
        Finish(project, page, fn, a, r);
        r["placed"] = DumpPlacement(fn, false);
    }

    static object[] InsertMacro(object page, string file, string rep, int v, double x, double y)
    {
        Type insType = FindType("Eplan.EplApi.HEServices.Insert");
        object ins = Activator.CreateInstance(insType);
        MethodInfo wm = null;
        foreach (MethodInfo m in insType.GetMethods())
        {
            ParameterInfo[] ps = m.GetParameters();
            if (m.Name == "WindowMacro" && ps.Length == 6 && ps[0].ParameterType == typeof(string)) wm = m;
        }
        if (wm == null) throw new Exception("Insert has no WindowMacro(string, RepresentationType, int, Page, PointD, MoveKind). " + MemberList(insType, true));
        ParameterInfo[] wp = wm.GetParameters();
        object repVal;
        try { repVal = Enum.Parse(wp[1].ParameterType, rep); }
        catch (Exception) { throw new Exception("Unknown representation '" + rep + "'. Values: " + string.Join(", ", Enum.GetNames(wp[1].ParameterType))); }
        object move = Enum.Parse(wp[5].ParameterType, "Absolute");
        object[] objs = (object[])Call(wm, ins, new object[] { file, repVal, v, page, MakePoint(wp[4].ParameterType, x, y), move });
        if (objs == null || objs.Length == 0)
            throw new Exception("WindowMacro inserted nothing from '" + file + "' (representation " + rep + ", variant " + v + "). " +
                "Check the file exists and has that representation/variant.");
        return objs;
    }

    static void RemoveObject(object o)
    {
        if (o == null) return;
        object subs = TryRead(o, "SubPlacements", null);
        if (subs != null)
        {
            List<object> list = new List<object>();
            foreach (object s in (IEnumerable)subs) if (s != null) list.Add(s);
            foreach (object s in list) RemoveObject(s);
        }
        try
        {
            if (PropText(o, "IsValid") == "False") return;
            Call(RequireMethod(o.GetType(), "Remove", new string[] { }, false), o, new object[] { });
        }
        catch (Exception e)
        {
            if (Flatten(e).IndexOf("Invalid", StringComparison.OrdinalIgnoreCase) < 0) throw;
        }
    }

    static void OpMacro(object project, object page, JObject a, Dictionary<string, object> r)
    {
        string file = Req(a, "file");
        if (!File.Exists(file)) throw new Exception("Macro file not found: " + file);
        string rep = S(a, "representation", "MultiLine");
        int v = I(a, "variant", 0);
        double x = D(a, "x", 0), y = D(a, "y", 0);
        string anchor = S(a, "anchor", "insertion");
        object[] objs = InsertMacro(page, file, rep, v, x, y);
        double[] bb = BBoxOfAll(objs);
        if (anchor == "top_left")
        {
            // Measure where the macro landed, remove it, insert it again
            // offset so its top-left corner is at (x, y).
            if (bb == null) throw new Exception("Cannot anchor by top-left: no inserted object reports a bounding box.");
            double dx = x - bb[0], dy = y - bb[3];
            if (Math.Abs(dx) > 1e-6 || Math.Abs(dy) > 1e-6)
            {
                foreach (object o in objs) RemoveObject(o);
                objs = InsertMacro(page, file, rep, v, x + dx, y + dy);
                bb = BBoxOfAll(objs);
            }
        }
        else if (anchor != "insertion") throw new Exception("anchor must be 'insertion' or 'top_left'.");

        List<string> handles = new List<string>();
        List<object> devices = new List<object>();
        string first = null;
        foreach (object o in objs)
        {
            if (o == null) continue;
            handles.Add(Handle(o));
            if (!IsDevice(o)) continue;
            if (first == null) first = Handle(o);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["handle"] = Handle(o);
            d["clrType"] = o.GetType().Name;
            Finish(project, page, o, a, d);
            d["name"] = PropText(o, "Name");
            object fd = TryRead(o, "FunctionDefinition", null);
            if (fd != null) d["functionDefinitionName"] = PropText(fd, "Name");
            List<string> refs = new List<string>();
            object ars = TryRead(o, "ArticleReferences", null);
            if (ars != null) foreach (object ar in (IEnumerable)ars) refs.Add(PropText(ar, "PartNr"));
            d["parts"] = refs;
            double[] ob = null;
            try { ob = BBoxOf(o); } catch { }
            if (ob != null) d["bbox"] = ob;
            devices.Add(d);
        }
        r["count"] = objs.Length;
        r["handles"] = handles;
        r["devices"] = devices;
        if (first != null) r["handle"] = first;
        if (bb != null) { r["bbox"] = bb; r["size"] = new double[] { bb[2] - bb[0], bb[3] - bb[1] }; }
    }

    static void OpUpdate(object project, object page, JObject a, Dictionary<string, string> labels, Dictionary<string, object> r)
    {
        object fn = Resolve(page, Req(a, "ref"), labels);
        Lock(fn);
        r["handle"] = Handle(fn);
        Finish(project, page, fn, a, r);
        r["placed"] = DumpPlacement(fn, false);
    }

    static void OpMove(object page, JObject a, Dictionary<string, string> labels, Dictionary<string, object> r)
    {
        object o = Resolve(page, Req(a, "ref"), labels);
        Lock(o);
        PropertyInfo locPi = RequireWritable(o.GetType(), "Location");
        locPi.SetValue(o, MakePoint(locPi.PropertyType, D(a, "x", 0), D(a, "y", 0)), null);
        r["handle"] = Handle(o);
        r["placed"] = DumpPlacement(o, false);
    }

    static void OpRemove(object page, JObject a, Dictionary<string, string> labels, Dictionary<string, object> r)
    {
        List<string> refs = new List<string>();
        if (Has(a, "ref")) refs.Add(Req(a, "ref"));
        if (Has(a, "refs")) foreach (JToken t in (JArray)a["refs"]) refs.Add((string)t);
        if (refs.Count == 0) throw new Exception("'ref' or 'refs' is required.");
        List<object> targets = new List<object>();
        foreach (string rf in refs) targets.Add(Resolve(page, rf, labels));
        foreach (object o in targets) { Lock(o); RemoveObject(o); }
        r["removed"] = targets.Count;
    }

    static void OpDimension(object page, JObject a, Dictionary<string, object> r)
    {
        Type dt = FindType("Eplan.EplApi.DataModel.Graphics.DimensionItem");
        MethodInfo create = null;
        foreach (MethodInfo m in dt.GetMethods())
            if (m.Name == "Create" && m.GetParameters().Length == 4) create = m;
        if (create == null) throw new Exception("DimensionItem has no 4-arg Create. " + MemberList(dt, true));
        Type pt = create.GetParameters()[1].ParameterType;
        object d = Activator.CreateInstance(dt);
        Call(create, d, new object[] { page,
            MakePoint(pt, D(a, "x1", 0), D(a, "y1", 0)),
            MakePoint(pt, D(a, "x2", 0), D(a, "y2", 0)),
            MakePoint(pt, D(a, "lineX", 0), D(a, "lineY", 0)) });
        r["handle"] = Handle(d);
        r["text"] = PropText(d, "DimensionText");
    }

    static void OpLine(object page, JObject a, Dictionary<string, object> r)
    {
        double ax = D(a, "x1", 0), ay = D(a, "y1", 0), bx = D(a, "x2", 0), by = D(a, "y2", 0);
        if (Math.Abs(ax - bx) > 1e-6 && Math.Abs(ay - by) > 1e-6)
            throw new Exception("A connection line must be horizontal or vertical; EPLAN does not treat a diagonal as a wire.");
        Type dclType = FindType("Eplan.EplApi.DataModel.DynamicConnectionLine");
        object dcl = Activator.CreateInstance(dclType);
        Call(RequireMethod(dclType, "Create", new string[] { "Page" }, false), dcl, new object[] { page });
        MethodInfo setG = RequireMethod(dclType, "SetGraphics", new string[] { "PointD", "PointD" }, false);
        Type pt = setG.GetParameters()[0].ParameterType;
        // SetGraphics is RELATIVE to Location: anchor first, then the segment.
        RequireWritable(dclType, "Location").SetValue(dcl, MakePoint(pt, ax, ay), null);
        Call(setG, dcl, new object[] { MakePoint(pt, 0.0, 0.0), MakePoint(pt, bx - ax, by - ay) });
        r["handle"] = Handle(dcl);
    }

    static void OpFind(object page, JObject a, Dictionary<string, object> r)
    {
        string name = S(a, "name", null), contains = S(a, "contains", null), type = S(a, "type", null);
        int limit = I(a, "limit", 200);
        IEnumerable src = PagePlacements(page);
        if (B(a, "firstLevel", false))
        {
            PropertyInfo fl = GetReadable(page.GetType(), "AllFirstLevelPlacements");
            if (fl != null) { object v = fl.GetValue(page, null); if (v != null) src = (IEnumerable)v; }
        }
        List<object> items = new List<object>();
        int matched = 0;
        foreach (object pl in src)
        {
            if (pl == null) continue;
            string tn = pl.GetType().Name;
            if (type != null && !string.Equals(tn, type, StringComparison.OrdinalIgnoreCase)) continue;
            string n = PropText(pl, "Name");
            string vn = VisibleNameOf(pl);
            if (name != null && n != name && vn != name) continue;
            if (contains != null && !Matches(n, contains) && !Matches(vn, contains)) continue;
            matched++;
            if (items.Count >= limit) continue;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["handle"] = Handle(pl);
            d["clrType"] = tn;
            if (n != null) d["name"] = n;
            if (vn != null && vn != n) d["visibleName"] = vn;
            double[] bb = null;
            try { bb = BBoxOf(pl); } catch { }
            if (bb != null) d["bbox"] = bb;
            object loc = TryRead(pl, "Location", null);
            if (loc != null) d["location"] = PtDict(loc);
            if (IsDevice(pl))
            {
                List<string> refs = new List<string>();
                object ars = TryRead(pl, "ArticleReferences", null);
                if (ars != null) foreach (object ar in (IEnumerable)ars) refs.Add(PropText(ar, "PartNr"));
                d["parts"] = refs;
            }
            items.Add(d);
        }
        r["matched"] = matched;
        r["items"] = items;
    }

    static void OpRead(object page, JObject a, Dictionary<string, string> labels, Dictionary<string, object> r)
    {
        object o = Resolve(page, Req(a, "ref"), labels);
        r["handle"] = Handle(o);
        r["placed"] = DumpPlacement(o, B(a, "pins", true));
    }

    static void Dispatch(object project, object page, string kind, JObject a,
                         Dictionary<string, string> labels, Dictionary<string, object> r)
    {
        switch (kind)
        {
            case "place": OpPlace(project, page, a, r); break;
            case "rect": OpRect(project, page, a, r); break;
            case "macro": OpMacro(project, page, a, r); break;
            case "update": OpUpdate(project, page, a, labels, r); break;
            case "move": OpMove(page, a, labels, r); break;
            case "remove": OpRemove(page, a, labels, r); break;
            case "dimension": OpDimension(page, a, r); break;
            case "line": OpLine(page, a, r); break;
            case "find": OpFind(page, a, r); break;
            case "read": OpRead(page, a, labels, r); break;
            default: throw new Exception("Unknown op '" + kind + "'. Known: place, rect, macro, update, move, remove, dimension, line, find, read.");
        }
    }

    // ---- the run -----------------------------------------------------------
    static void RunOps(string opsPath, string resultPath, bool acknowledge)
    {
        if (string.IsNullOrEmpty(opsPath) || string.IsNullOrEmpty(resultPath)) return;
        // The marker tells the caller the registered action is alive before
        // the work is done; a one-shot script has ExecuteScript's own
        // synchronous return for that and leaves no marker behind.
        if (acknowledge) { try { File.WriteAllText(resultPath + ".started", "1"); } catch { } }
        Dictionary<string, object> results = new Dictionary<string, object>();
        Type lsType = null;
        object lockStep = null;
        try
        {
            JObject req = JObject.Parse(File.ReadAllText(opsPath));
            lsType = FindType("Eplan.EplApi.DataModel.LockingStep");
            lockStep = Activator.CreateInstance(lsType);
            object project = ResolveProject(S(req, "project", ""));
            results["project"] = PropText(project, "ProjectName");
            if (B(req, "write", true))
                GuardScratch(project, B(req, "allowReal", false), S(req, "scratchRoot", ""));
            object page = FindPage(project, Req(req, "page"));
            results["page"] = PropText(page, "Name");
            if (B(req, "write", true)) { Lock(project); Lock(page); }

            JArray ops = (JArray)req["ops"];
            bool stop = B(req, "stopOnError", true);
            Dictionary<string, string> labels = new Dictionary<string, string>();
            List<object> outs = new List<object>();
            int failed = 0;
            for (int i = 0; i < ops.Count; i++)
            {
                JObject op = (JObject)ops[i];
                string kind = S(op, "op", "");
                string label = S(op, "label", null);
                Dictionary<string, object> r = new Dictionary<string, object>();
                r["index"] = i;
                r["op"] = kind;
                if (label != null) r["label"] = label;
                try
                {
                    Dispatch(project, page, kind, op, labels, r);
                    r["success"] = true;
                    if (label != null && r.ContainsKey("handle")) labels[label] = (string)r["handle"];
                }
                catch (Exception ex)
                {
                    r["success"] = false;
                    r["error"] = Flatten(ex);
                    failed++;
                }
                outs.Add(r);
                if (failed > 0 && stop) { results["stoppedAt"] = i; break; }
            }
            results["ops"] = outs;
            results["labels"] = labels;
            results["failed"] = failed;
            results["allOk"] = failed == 0;
            if (B(req, "readBack", false))
            {
                string[] types = null;
                if (Has(req, "types"))
                {
                    List<string> tl = new List<string>();
                    foreach (JToken t in (JArray)req["types"]) tl.Add((string)t);
                    types = tl.ToArray();
                }
                Dictionary<string, object> after = ReadPage(page, I(req, "limit", 1000), B(req, "pins", false), types);
                // Attach each placement's text boxes, for the overlap check.
                Dictionary<string, Dictionary<string, object>> byHandle = new Dictionary<string, Dictionary<string, object>>();
                foreach (object it in (List<object>)after["placements"])
                {
                    Dictionary<string, object> d = (Dictionary<string, object>)it;
                    byHandle[(string)d["handle"]] = d;
                }
                foreach (object pl in PagePlacements(page))
                {
                    if (pl == null) continue;
                    string h = Handle(pl);
                    if (!byHandle.ContainsKey(h)) continue;
                    List<object> tb = TextBoxes(pl);
                    if (tb.Count > 0) byHandle[h]["texts"] = tb;
                }
                results["page_after"] = after;
            }
            results["success"] = true;
        }
        catch (Exception ex)
        {
            results["success"] = false;
            results["error"] = Flatten(ex);
        }
        finally
        {
            if (lockStep != null)
            {
                try { lsType.GetMethod("Dispose").Invoke(lockStep, null); }
                catch { }
            }
        }
        File.WriteAllText(resultPath, Newtonsoft.Json.JsonConvert.SerializeObject(results));
    }

    [Start]
    public void Run()
    {
        RunOps(@"{{OPS_PATH}}", @"{{RESULT_PATH}}", false);
    }

    [DeclareAction("ACTIONNAME")]
    public void McpOps(string ops, string result)
    {
        RunOps(ops, result, true);
    }
}
'''


# ---------------------------------------------------------------------------
# Interpreter source and execution
# ---------------------------------------------------------------------------

def _static_helpers():
    """live.py's static helper block (everything before its [Start] method)."""
    return live._HELPERS.split(live._START_MARKER)[0]


def _interpreter_source(class_name, action_name):
    return (_HEADER + class_name + _static_helpers() + live._PROJECT_HELPER
            + schematic._HELPERS_SCHEMATIC + _OPS_HELPERS.replace("ACTIONNAME", action_name))


def _source_hash():
    """Identifies the interpreter version: a changed op never hits a stale registration."""
    return hashlib.sha1(_interpreter_source("X", "X").encode("utf-8")).hexdigest()[:10]


def _action_name():
    return "McpOps_" + _source_hash()


def _ops_mode():
    return (os.environ.get("EPLAN_MCP_OPS_MODE") or "registered").strip().lower()


def _wait_for(path, timeout):
    start = time.time()
    while not os.path.exists(path):
        if time.time() - start > timeout:
            return False
        time.sleep(0.05)
    return True


def _read_result(result_path):
    for attempt in range(10):
        if attempt:
            time.sleep(0.05)
        try:
            with open(result_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, ValueError):
            if attempt == 9:
                raise


def _cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _run_registered(manager, request_path, result_path, timeout):
    """
    Run the request through the registered action. Returns the raw result
    dict, or None when the action did not answer (not registered, EPLAN
    restarted) so the caller falls back to a one-shot script.
    """
    name = _action_name()
    script_path = os.path.join(OPS_DIR, name + ".cs")
    if not os.path.exists(script_path):
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(_interpreter_source(name, name).replace("{{OPS_PATH}}", "").replace("{{RESULT_PATH}}", ""))

    started = result_path + ".started"
    for attempt in (1, 2):
        if name not in _registered:
            reg = manager.execute_action('RegisterScript /ScriptFile:"%s"' % script_path, quiet_mode=False)
            if not reg.get("success"):
                return None
            _registered.add(name)
        run = manager.execute_action('%s /ops:"%s" /result:"%s"' % (name, request_path, result_path),
                                     quiet_mode=False)
        if run.get("success") and _wait_for(started, STARTED_TIMEOUT_S):
            if not _wait_for(result_path, timeout):
                return {"success": False, "errorType": "McpOpsTimeout",
                        "error": "The batch started but wrote no result within %gs." % timeout}
            return _read_result(result_path)
        # No acknowledgement: the registration is stale (EPLAN restarted) or
        # was refused. Re-register once, then give up on this path.
        _registered.discard(name)
    return None


def run_ops(page, ops, read_back=False, stop_on_error=True, allow_real_project=False,
            write=True, pins=True, limit=1000, types=None, timeout_seconds=300.0):
    """Execute a list of ops on one page in ONE EPLAN script. Returns the shaped result.

    The read-back is limited to device types by default: a real page is mostly
    graphics (998 placements on a small panel page, most of them macro lines),
    and an unfiltered read truncates before it reaches the devices the overlap
    check needs.
    """
    if read_back and types is None:
        types = list(_READBACK_TYPES)
    manager, error = _get_connected_manager()
    if error:
        return error
    scripted._ensure_dirs()
    os.makedirs(OPS_DIR, exist_ok=True)

    exec_id = uuid.uuid4().hex[:8]
    request_path = os.path.join(OPS_DIR, "ops_%s.json" % exec_id)
    result_path = os.path.join(scripted.RESULTS_DIR, "ops_%s.json" % exec_id)
    request = {
        "project": target.get(),
        "page": page,
        "ops": ops,
        "readBack": bool(read_back),
        "types": types,
        "pins": bool(pins),
        "limit": int(limit),
        "stopOnError": bool(stop_on_error),
        "allowReal": bool(allow_real_project),
        "write": bool(write),
        "scratchRoot": SCRATCH_ROOT,
    }
    with open(request_path, "w", encoding="utf-8") as fh:
        json.dump(request, fh, ensure_ascii=False)

    raw = None
    engine = "script"
    try:
        # Reads only. Inside the registered action every write lock fails
        # (LockingExceptionFailedLockAttempt, even LockObject itself) while
        # the identical C# run by ExecuteScript succeeds - the action runs
        # outside the context that owns the project's locks. Measured on
        # 2026.0.3 the one-shot costs about 0.2 s more, so writes take it.
        if _ops_mode() != "script" and not write:
            raw = _run_registered(manager, request_path, result_path, timeout_seconds)
            if raw is not None:
                engine = "registered"
        if raw is None:
            class_name = "McpOps_" + exec_id
            script = (_interpreter_source(class_name, "McpOpsOneShot_" + exec_id)
                      .replace("{{OPS_PATH}}", request_path.replace("\\", "\\\\")))
            raw = scripted._execute_script(script, timeout=timeout_seconds)
    finally:
        _cleanup(request_path, result_path + ".started")

    if engine == "registered" and isinstance(raw, dict) and raw.get("errorType") != "McpOpsTimeout":
        # The registered action hands back the script's own result dict; put
        # it in the envelope _execute_script would have used, so _shape sees
        # one shape from both engines.
        raw = {"success": True, "results": raw}
    out = schematic._shape(raw)
    out["engine"] = engine
    if out.get("success"):
        out["success"] = bool(out.get("allOk"))
        if out.get("page_after"):
            schematic._annotate_pins(out)
            out["overlaps"] = _overlaps(out["page_after"].get("placements") or [])
    return out


# ---------------------------------------------------------------------------
# Overlap detection (Python side, from the read-back's bounding boxes)
# ---------------------------------------------------------------------------

_DEVICE_TYPES = ("Function", "Terminal", "PLC", "BoxedDevice")
# What the read-back fetches for the overlap check: devices, the connection
# symbols (their pins define where the autoconnect lines run) and dimensions.
_READBACK_TYPES = _DEVICE_TYPES + ("SymbolReference", "DimensionItem")


def _rect(pl):
    pts = pl.get("boundingBox") or []
    xs = [p["x"] for p in pts if p and p.get("x") is not None and abs(p["x"]) < 1e6]
    ys = [p["y"] for p in pts if p and p.get("y") is not None and abs(p["y"]) < 1e6]
    if not xs or not ys:
        return None
    r = (min(xs), min(ys), max(xs), max(ys))
    if r[2] - r[0] < 1e-6 or r[3] - r[1] < 1e-6:
        return None
    return r


def _who(pl):
    return {"handle": pl.get("handle"), "name": pl.get("name"), "clrType": pl.get("clrType")}


def _intersection(ra, rb):
    ix = min(ra[2], rb[2]) - max(ra[0], rb[0])
    iy = min(ra[3], rb[3]) - max(ra[1], rb[1])
    return ix * iy if ix > 0 and iy > 0 else 0.0


def _contains(outer, inner):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _autoconnect_segments(placements):
    """
    The lines EPLAN draws by itself, reconstructed from the pins: two pins on
    a shared axis, facing each other, with nothing of theirs in between. An
    autoconnect line is not an object, so this is the only way to know where
    one runs. Each segment is ((x0, y0, x1, y1), owner_a, owner_b).
    """
    pins = []
    for pl in placements:
        for pin in pl.get("pins") or []:
            pt = pin.get("point")
            d = pin.get("direction")
            if not pt or d not in ("Up", "Down", "Left", "Right"):
                continue
            pins.append((pt["x"], pt["y"], d, pl))
    opposite = {"Up": "Down", "Down": "Up", "Left": "Right", "Right": "Left"}
    segs = []
    for x, y, d, owner in pins:
        best = None
        for x2, y2, d2, other in pins:
            if other is owner or d2 != opposite[d]:
                continue
            if d in ("Up", "Down"):
                if abs(x2 - x) > 0.01:
                    continue
                dist = (y2 - y) if d == "Up" else (y - y2)
            else:
                if abs(y2 - y) > 0.01:
                    continue
                dist = (x2 - x) if d == "Right" else (x - x2)
            if dist <= 0.01:
                continue
            if best is None or dist < best[0]:
                best = (dist, x2, y2, other)
        if best and id(owner) < id(best[3]):
            segs.append(((min(x, best[1]), min(y, best[2]), max(x, best[1]), max(y, best[2])), owner, best[3]))
    return segs


def _segment_crosses(seg, r, margin=0.01):
    """True when the (axis-aligned) segment passes through the rectangle's interior."""
    x0, y0, x1, y1 = seg
    return (min(x1, r[2]) - max(x0, r[0]) > margin and min(y1, r[3]) - max(y0, r[1]) > margin) or (
        x0 == x1 and r[0] + margin < x0 < r[2] - margin and min(y1, r[3]) - max(y0, r[1]) > margin) or (
        y0 == y1 and r[1] + margin < y0 < r[3] - margin and min(x1, r[2]) - max(x0, r[0]) > margin)


def _overlaps(placements, min_area=2.0, limit=100):
    """
    What collides on the page, from the read-back:

    - outline/outline: two device outlines that intersect without one
      containing the other (a device on its plate is normal);
    - text/outline: a device's or dimension's text over another object's
      outline (the caption of a rail across the PSU on it) - except the
      object that contains the text's owner (a point's designation inside
      its PLC box, a part's caption on the mounting plate);
    - text/text: two objects' texts that overlap (terminal captions on top
      of each other);
    - line/outline and line/text: an autoconnect line, reconstructed from
      facing pins, running through an object it does not end on or in.

    One entry per pair, with the summed area and the number of collisions.
    Not visible to this check: a coil's contact image, which the API does
    not expose as geometry, and graphics inside macros.
    """
    outlines = []   # (pl, rect) for devices and dimensions
    texts = []      # (pl, rect)
    rect_of = {}
    for pl in placements:
        t = pl.get("clrType")
        r = _rect(pl)
        if r and t in _DEVICE_TYPES + ("DimensionItem",):
            outlines.append((pl, r))
            rect_of[id(pl)] = r
        for box in pl.get("texts") or []:
            if len(box) == 4 and box[2] - box[0] > 1e-6 and box[3] - box[1] > 1e-6:
                texts.append((pl, tuple(box)))

    found = {}

    def report(kind, a, b, area=None, extra=None):
        key = (kind, a.get("handle"), b.get("handle"))
        if kind == "text/text":
            key = (kind,) + tuple(sorted([a.get("handle") or "", b.get("handle") or ""]))
        entry = found.get(key)
        if entry is None:
            entry = {"kind": kind, "a": _who(a), "b": _who(b), "area_mm2": 0.0, "count": 0}
            if extra:
                entry.update(extra)
            found[key] = entry
        entry["count"] += 1
        if area:
            entry["area_mm2"] = round(entry["area_mm2"] + area, 2)

    def is_container(obj, owner):
        """obj's outline holds the whole of owner: a plate, a PLC box, a rail."""
        ro, rw = rect_of.get(id(obj)), rect_of.get(id(owner))
        return ro is not None and rw is not None and _contains(ro, rw)

    for i in range(len(outlines)):
        a, ra = outlines[i]
        if a.get("clrType") == "DimensionItem":
            continue
        for j in range(i + 1, len(outlines)):
            b, rb = outlines[j]
            if b.get("clrType") == "DimensionItem":
                continue
            area = _intersection(ra, rb)
            if area < min_area or _contains(ra, rb) or _contains(rb, ra):
                continue
            report("outline/outline", a, b, area)

    for tpl, tr in texts:
        for opl, orect in outlines:
            if opl is tpl or is_container(opl, tpl):
                continue
            area = _intersection(tr, orect)
            if area >= min_area:
                report("text/outline", tpl, opl, area)

    for i in range(len(texts)):
        a, ra = texts[i]
        for j in range(i + 1, len(texts)):
            b, rb = texts[j]
            if a is b:
                continue
            area = _intersection(ra, rb)
            if area >= min_area:
                report("text/text", a, b, area)

    for seg, owner_a, owner_b in _autoconnect_segments(placements):
        ends = ((seg[0], seg[1]), (seg[2], seg[3]))
        for opl, orect in outlines:
            if opl is owner_a or opl is owner_b:
                continue
            if any(orect[0] <= x <= orect[2] and orect[1] <= y <= orect[3] for x, y in ends):
                continue  # the line ends inside this object (a point in its PLC box)
            if _segment_crosses(seg, orect):
                report("line/outline", owner_a, opl, None, {"line_to": _who(owner_b), "segment": list(seg)})
        for tpl, tr in texts:
            if tpl is owner_a or tpl is owner_b:
                continue
            if _segment_crosses(seg, tr):
                report("line/text", owner_a, tpl, None, {"line_to": _who(owner_b), "segment": list(seg)})

    out = sorted(found.values(), key=lambda e: -e["area_mm2"])
    return out[:limit]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _err(exc):
    return {"success": False, "error": str(exc)}


def live_batch(page: str, operations: list, read_back: bool = False,
               stop_on_error: bool = True, allow_real_project: bool = False,
               timeout_seconds: float = 300.0) -> dict:
    """
    Run a list of page operations in ONE EPLAN script. WRITES - scratch-only by default.

    One compile (or none, once the interpreter is registered for the session)
    instead of one per object. Operations run in order; an op can refer to
    the object a previous op created with "$label".

    Each operation is {"op": ..., "label": optional, ...arguments}:

      place     library, symbol, variant=0, x, y, x2?, y2?, snap=true,
                type? ("Function" default, "EObjects.PLC" for a PLC box),
                plus any of: tag, visibleName, allowMerge, part,
                properties {NAME: value, "NAME[i]": value}, functionDefinition
                {category, group, id}. Falls back to the 2-arg Create for
                terminals and PLC points (reports "route").
      rect      x, y (top-left), width, height, library=SPECIAL, symbol=PANP,
                mountingPlate?, plus tag/part/properties - a panel part drawn
                as its outline.
      macro     file, x, y, variant=0, representation=MultiLine
                (ArticlePlacement for panels), anchor="insertion"|"top_left",
                plus tag/part applied to every device the macro created.
      update    ref, plus tag/visibleName/allowMerge/part/properties/
                functionDefinition.
      move      ref, x, y.
      remove    ref or refs[] (a group takes its sub-placements with it).
      dimension x1, y1, x2, y2, lineX, lineY.
      line      x1, y1, x2, y2 (horizontal or vertical connection line).
      find      name? contains? type? firstLevel? limit?  (read-only)
      read      ref, pins=true                             (read-only)

    `ref` is a handle, a device tag as EPLAN stores it ("=+CE-K1" or "-K1"
    as displayed), or "$label".

    Args:
        page: Page name, as live_read_page reports it.
        operations: The list above. An op that fails stops the batch
            (stop_on_error) and the result says at which index.
        read_back: Also return the page's devices (page_after, limited to
            Function/Terminal/PLC/BoxedDevice - graphics are left out) and
            "overlaps": pairs of device outlines that intersect without one
            containing the other.
        stop_on_error: Default True.
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: For the whole batch. Default 300.

    Returns:
        {"success" (every op succeeded), "engine" ("registered" or "script"),
         "ops": [per-op result with "success", "handle" when it made one,
         "error" when it failed], "labels": {label: handle}, "failed",
         "stoppedAt"?, "page_after"?, "overlaps"?}
    """
    try:
        page = cs_text(page, "page")
    except SchematicValueError as exc:
        return _err(exc)
    if not isinstance(operations, list) or not all(isinstance(o, dict) for o in operations):
        return {"success": False, "error": "operations must be a list of {\"op\": ...} dicts."}
    for i, op in enumerate(operations):
        if not isinstance(op.get("op"), str):
            return {"success": False, "error": "operation %d has no 'op' name." % i}
    return run_ops(page, operations, read_back=read_back, stop_on_error=stop_on_error,
                   allow_real_project=allow_real_project, timeout_seconds=timeout_seconds)


def live_find_placements(page: str, name: str = None, contains: str = None,
                         type: str = None, first_level: bool = False, limit: int = 200,
                         timeout_seconds: float = 120.0) -> dict:
    """
    Find objects on a page by device tag, substring or type - handles included. Read-only.

    Handles change when EPLAN restarts; tags do not. Use this to re-find a
    device after a restart, or to check what a tag resolves to before an
    update/remove.

    Args:
        page: Page name.
        name: Exact device tag, as stored ("=+CE-K1") or displayed ("-K1").
        contains: Case-insensitive substring of the tag.
        type: CLR type name to keep ("Function", "Terminal", "Group",
            "DimensionItem", ...).
        first_level: Only top-level placements (skip the contents of groups).
        limit: Max items returned (default 200).

    Returns:
        {"success", "matched", "items": [{"handle", "clrType", "name",
         "visibleName"?, "bbox": [x0, y0, x1, y1]?, "location"?, "parts"?}]}
    """
    out = run_ops(page, [{"op": "find", "name": name, "contains": contains, "type": type,
                          "firstLevel": bool(first_level), "limit": int(limit)}],
                  write=False, timeout_seconds=timeout_seconds)
    return _single(out)


def _single(out, key=None):
    """Lift the one op's result into the top level of a single-op tool's result."""
    if not out.get("success"):
        ops = out.get("ops") or []
        if ops and ops[0].get("error"):
            out["error"] = ops[0]["error"]
        return out
    op = (out.get("ops") or [{}])[0]
    merged = dict(op)
    merged.pop("index", None)
    merged["engine"] = out.get("engine")
    merged["project"] = out.get("project")
    merged["page"] = out.get("page")
    if "page_after" in out:
        merged["page_after"] = out["page_after"]
        merged["overlaps"] = out.get("overlaps")
    return merged


def live_place_device(page: str, library: str, symbol: str, x: float, y: float,
                      tag: str = None, part: str = None, properties: dict = None,
                      variant_nr: int = 0, function_definition: dict = None,
                      snap_to_grid: bool = True, allow_real_project: bool = False,
                      timeout_seconds: float = 120.0) -> dict:
    """
    Place a device and finish it - tag, part, properties - in one script. WRITES.

    Equivalent to live_place_symbol + live_set_device_tag + part + property
    writes, in one round trip. Terminals and PLC connection points, whose
    4-arg Create is not implemented, are placed through the 2-arg route
    automatically ("route" in the result says which).

    Args:
        page: Page name.
        library, symbol, variant_nr: The symbol (see live_symbol_catalog).
        x, y: Insertion point in mm.
        tag: Device tag to assign, e.g. "=+CE-K1". The visible name defaults
            to the tag from its first "-" ("-K1"), which is what makes it show.
        part: Part number to attach (must exist in the parts database).
        properties: {"FUNC_TEXT": "...", "FUNC_CONNECTIONDESIGNATION[1]": "A1"}.
        function_definition: {"category": "PLCTerminal", "group": 1, "id": 2}.
        snap_to_grid: Round x/y to the page grid first (default True).
        allow_real_project: Must be True to write outside the scratch root.

    Returns:
        {"success", "handle", "route", "name", "part"?, "properties"?,
         "placed" (DumpPlacement with absolute pins), "engine"}
    """
    op = {"op": "place", "library": library, "symbol": symbol, "variant": int(variant_nr),
          "x": float(x), "y": float(y), "snap": bool(snap_to_grid)}
    _optional(op, tag=tag, part=part, properties=properties, functionDefinition=function_definition)
    out = run_ops(page, [op], allow_real_project=allow_real_project, timeout_seconds=timeout_seconds)
    out = _single(out)
    if out.get("success") and isinstance(out.get("placed"), dict) and out["placed"].get("pins"):
        out["placed"]["pins"] = schematic.absolute_pins(out["placed"])
    return out


def _optional(op, **kwargs):
    for k, v in kwargs.items():
        if v is not None:
            op[k] = v


def live_insert_macro(page: str, macro_file: str, x: float, y: float,
                      variant_nr: int = 0, representation: str = "MultiLine",
                      anchor: str = "insertion", tag: str = None, part: str = None,
                      allow_real_project: bool = False, timeout_seconds: float = 240.0) -> dict:
    """
    Insert a window macro (.ema) on a page. WRITES - scratch-only by default.

    This is what EPLAN does when a part with a macro is dragged from the
    navigator: the macro's variant for the page type is placed, and every
    device it contains gets the tag and the part.

    Args:
        page: Page name.
        macro_file: Full path of the .ema file.
        x, y: Where to put it, in mm.
        variant_nr: Macro variant index (0-based).
        representation: "MultiLine" for schematics, "ArticlePlacement" for
            the panel layout, "SingleLine", "Overview", "Graphics", ...
        anchor: "insertion" places the macro's own insertion point at (x, y);
            "top_left" measures the macro, removes it and inserts it again so
            its top-left corner lands at (x, y) - what a panel layout needs.
        tag: Device tag for the devices the macro created (all of them: a
            panel macro's devices are one part).
        part: Part number to attach to those devices.
        allow_real_project: Must be True to write outside the scratch root.

    Returns:
        {"success", "count", "handles", "devices": [{"handle", "name",
         "parts", "bbox"}], "bbox": [x0, y0, x1, y1], "size": [w, h], "engine"}
    """
    op = {"op": "macro", "file": macro_file, "x": float(x), "y": float(y), "variant": int(variant_nr),
          "representation": representation, "anchor": anchor}
    _optional(op, tag=tag, part=part)
    return _single(run_ops(page, [op], allow_real_project=allow_real_project,
                           timeout_seconds=timeout_seconds))


def live_place_panel_item(page: str, tag: str, x: float, y: float, width: float = None,
                          height: float = None, part: str = None, macro_file: str = None,
                          variant_nr: int = 0, mounting_plate: str = None, symbol: str = "PANP",
                          allow_real_project: bool = False, timeout_seconds: float = 240.0) -> dict:
    """
    Put a part on the panel layout page by its top-left corner. WRITES.

    With macro_file, the part's 2D panel macro is inserted (ArticlePlacement
    representation) with its top-left at (x, y) and tagged. Without, EPLAN's
    own fallback is reproduced: a rectangle of width x height mm (symbol
    SPECIAL/PANP; "PAN" for a mounting plate or a door) carrying the tag and
    the part, so the parts list shows one device, not two.

    Args:
        page: The panel layout page.
        tag: Device tag, e.g. "=+CE-F1".
        x, y: Top-left corner in mm (page coordinates: y grows upward).
        width, height: Outline size in mm; required without a macro.
        part: Part number.
        macro_file: Path of the .ema with an ArticlePlacement variant.
        variant_nr: Macro variant to use.
        mounting_plate: Tag of the plate the part sits on (rectangle only).
        symbol: "PANP" (part) or "PAN" (plate/door).
        allow_real_project: Must be True to write outside the scratch root.

    Returns:
        The macro op's or the rect op's result, plus "engine".
    """
    if macro_file:
        op = {"op": "macro", "file": macro_file, "x": float(x), "y": float(y), "variant": int(variant_nr),
              "representation": "ArticlePlacement", "anchor": "top_left", "tag": tag}
        _optional(op, part=part)
    else:
        if width is None or height is None:
            return {"success": False, "error": "width and height are required when no macro_file is given."}
        op = {"op": "rect", "x": float(x), "y": float(y), "width": float(width), "height": float(height),
              "symbol": symbol, "tag": tag}
        _optional(op, part=part, mountingPlate=mounting_plate)
    return _single(run_ops(page, [op], allow_real_project=allow_real_project,
                           timeout_seconds=timeout_seconds))


def live_place_plc_point(page: str, x: float, y: float, kind: str, designation: str = None,
                         tag: str = None, address: str = None, library: str = "SPECIAL",
                         symbol: str = "PLCCP", variant_nr: int = 0,
                         allow_real_project: bool = False, timeout_seconds: float = 120.0) -> dict:
    """
    Place a PLC connection point with its role already set. WRITES.

    A bare PLCCP symbol is nothing until its FunctionDefinition says what it
    is; this sets it from `kind` and places through the 2-arg Create that
    PLC points need.

    Args:
        page: Page name.
        x, y: Insertion point in mm.
        kind: "DI", "DO", "PS+", "PS-" (PLC card supply), "CPS+", "CPS-"
            (CPU supply). Group/id pairs: 1/2, 1/3, 3/5, 3/6, 2/5, 2/6.
        designation: Connection point designation, e.g. "DI a.0" or "L+".
        tag: Device tag of the PLC box this point belongs to, e.g. "=+CE-A1".
        address: PLC address, e.g. "I0.0" (FUNC_PLCADDRESS).
        library, symbol, variant_nr: Default SPECIAL/PLCCP variant 0.
        allow_real_project: Must be True to write outside the scratch root.

    Returns:
        As live_place_device.
    """
    key = (kind or "").upper().replace(" ", "")
    if key not in PLC_POINT_KINDS:
        return {"success": False, "error": "kind must be one of %s." % ", ".join(PLC_POINT_KINDS)}
    group, fid = PLC_POINT_KINDS[key]
    props = {}
    if designation is not None:
        props["FUNC_CONNECTIONDESIGNATION[1]"] = designation
    if address is not None:
        props["FUNC_PLCADDRESS"] = address
    return live_place_device(page, library, symbol, x, y, tag=tag, properties=props or None,
                             variant_nr=variant_nr, snap_to_grid=False,
                             function_definition={"category": "PLCTerminal", "group": group, "id": fid},
                             allow_real_project=allow_real_project, timeout_seconds=timeout_seconds)


def live_place_terminal(page: str, library: str, symbol: str, x: float, y: float,
                        strip: str, number: str, part: str = None, variant_nr: int = 0,
                        allow_real_project: bool = False, timeout_seconds: float = 120.0) -> dict:
    """
    Place a terminal of a strip. WRITES.

    Terminals need the 2-arg Create and carry their strip and number in the
    tag ("-X1:3"), which EPLAN splits into strip -X1 and terminal 3.

    Args:
        page: Page name.
        library, symbol, variant_nr: The terminal symbol (e.g. SPECIAL/X2_1).
        x, y: Insertion point in mm.
        strip: The strip's tag, e.g. "=+CE-X1".
        number: Terminal designation, e.g. "3".
        part: Part number of the terminal block.
        allow_real_project: Must be True to write outside the scratch root.

    Returns:
        As live_place_device.
    """
    return live_place_device(page, library, symbol, x, y, tag="%s:%s" % (strip, number), part=part,
                             variant_nr=variant_nr, snap_to_grid=False,
                             allow_real_project=allow_real_project, timeout_seconds=timeout_seconds)


def live_update_placement(page: str, ref: str, tag: str = None, visible_name: str = None,
                          allow_merge: bool = False, part: str = None, properties: dict = None,
                          function_definition: dict = None, allow_real_project: bool = False,
                          timeout_seconds: float = 120.0) -> dict:
    """
    Set the tag, part, properties or function definition of an existing object. WRITES.

    Args:
        page: Page name.
        ref: Handle, or the object's current device tag.
        tag: New device tag. A tag already used on the page is refused unless
            allow_merge, because EPLAN would merge the two devices.
        visible_name: Override the displayed name (default: tag from its
            first "-"). Never pass a location prefix: "CE-K1" inside +CE
            displays as "=+CE-CE-K1".
        allow_merge: Permit a tag already present on this page.
        part: Part number to add (skipped if already attached).
        properties: {"FUNC_TEXT": "...", "NAME[i]": "..." for indexed ones}.
        function_definition: {"category", "group", "id"}.
        allow_real_project: Must be True to write outside the scratch root.

    Returns:
        {"success", "handle", "name"?, "part"?, "properties"?, "placed", "engine"}
    """
    op = {"op": "update", "ref": ref, "allowMerge": bool(allow_merge)}
    _optional(op, tag=tag, visibleName=visible_name, part=part, properties=properties,
              functionDefinition=function_definition)
    return _single(run_ops(page, [op], allow_real_project=allow_real_project,
                           timeout_seconds=timeout_seconds))


def live_render_page(page: str, output_dir: str = None, image_width: int = 2000,
                     project_name: str = None) -> dict:
    """
    Export one page as a PNG so it can be looked at. Read-only.

    The quickest way to see what a batch produced: export, then open the
    file with an image viewer (or the Read tool). The file name is EPLAN's
    own; the result lists whatever PNG files the export wrote.

    Args:
        page: Page name, e.g. "=+CE/0".
        output_dir: Folder for the image (default: <scratch root>/renders).
        image_width: Pixel width (default 2000).
        project_name: Project path; defaults to the target project.

    Returns:
        {"success", "files": [paths written or updated], "export": the
         export action's result}
    """
    from .export_ import export_graphics_pages
    out_dir = output_dir or os.path.join(SCRATCH_ROOT, "renders")
    os.makedirs(out_dir, exist_ok=True)

    def snapshot():
        return {f: os.path.getmtime(os.path.join(out_dir, f))
                for f in os.listdir(out_dir) if f.lower().endswith(".png")}

    before = snapshot()
    res = export_graphics_pages(destination_path=out_dir, page_name=page, project_name=project_name,
                                format="PNG", image_width=int(image_width))
    after = snapshot()
    files = sorted(os.path.join(out_dir, f) for f, m in after.items() if before.get(f) != m)
    ok = bool(res.get("success")) and bool(files)
    out = {"success": ok, "files": files, "export": res}
    if res.get("success") and not files:
        out["error"] = "The export reported success but wrote no PNG into %s." % out_dir
    return out


def live_check_page(page: str, limit: int = 200, project_name: str = None,
                    timeout_seconds: float = 180.0) -> dict:
    """
    Check a page and report what is wrong with it, in one call. Read-only.

    Runs EPLAN's page check, reads the itemized messages it produced, and
    reads the page back to find device outlines that overlap each other.
    Call it after a batch, before telling the user the page is done.

    Args:
        page: Page name.
        limit: Max check messages to return (default 200).
        project_name: Project path; defaults to the target project.
        timeout_seconds: For the read-back (default 180).

    Returns:
        {"success", "check": the check action's result, "messages": [...]
         (as live_read_check_messages), "overlaps": [{"a", "b", "area_mm2"}],
         "placementCount"}
    """
    from .verify import check_pages
    chk = check_pages(page_name=page, project_name=project_name)
    msgs = live.live_read_check_messages(limit=int(limit), timeout_seconds=timeout_seconds)
    msg_list = (msgs.get("results") or {}).get("messages") if isinstance(msgs.get("results"), dict) else msgs.get("messages")
    page_out = run_ops(page, [], read_back=True, write=False, timeout_seconds=timeout_seconds)
    out = {
        "success": bool(chk.get("success")) and bool(page_out.get("success")),
        "check": chk,
        "messages": msg_list or [],
        "messagesTotal": (msgs.get("results") or msgs).get("total"),
        "overlaps": page_out.get("overlaps") or [],
        "placementCount": (page_out.get("page_after") or {}).get("placementCount"),
    }
    if not page_out.get("success"):
        out["error"] = page_out.get("error")
    return out
