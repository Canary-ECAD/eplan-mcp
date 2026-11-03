"""
Cables: what cables the project has and which connections they carry, and a
writer that places a CABLE DEFINITION LINE across connections, the way
"Insertar > Definición de cables" does.

Learned live on 2026.0.3 (scratch copy of TEST-S7-1200):

- A cable is an `EObjects.Cable` function (function category Cable 1/1,
  "Definición de cables"). Placed, it is the SPECIAL/CABDL line; the
  connections the line crosses become its conductors (`CableConnections`)
  once the connections are generated. A cable without a part has as many
  conductors as lines it crosses; with a part, the part's connection
  templates (MDCableTemplatePosition) give the conductors their colours and
  cross-sections, and "Asignar conexiones" matches them.
- `Cable.Create(Page, SymbolVariant, PointD start, PointD end)` places the
  line; Name, part and FUNC_TEXT are written afterwards like any function.
- The GUI assigns the crossed connections while the line is drawn; a line
  placed by the API gets NO conductors from "generate connections" alone,
  however often it runs (verified: 0 after rebuild-all, after opening the
  page, after nudging the line). What works is what the GUI does under the
  hood: write the cable's `NameParts` into each crossed Connection's
  `CableNameParts` (the connection then answers CONNECTION_IS_CABLE=1) and
  regenerate connections once - the cable's `CableConnections` then lists
  them and each connection's `CableDefinitionLine` is the cable. Which
  connections cross is decided geometrically here: a connection runs
  between its two symbol references' pins (reference Location + pin
  offset), and it crosses when that segment straddles the line's y inside
  the line's x range (or the transposed test for a vertical line).
- The workstation licence answers EditingOfCables=true, Cabling=false:
  cable functions and diagrams are allowed, 3D routing is not.
"""

import uuid

from ._base import cs_escape
from .scripted import _execute_script
from . import live, schematic
from .schematic import _err, _guard_prelude
from .schematic_model import cs_text, SchematicValueError
from .terminals_live import _HELPERS_TERM


_CABLE_DICT = '''
                Dictionary<string, object> d = new Dictionary<string, object>();
                d["handle"] = Handle(fn);
                d["name"] = PropText(fn, "Name") ?? "";
                object fprops = TryRead(fn, "Properties", null);
                d["text"] = fprops == null ? "" : (PropText(fprops, "FUNC_TEXT") ?? "");
                object pg = TryRead(fn, "Page", null);
                d["page"] = pg == null ? null : PropText(pg, "Name");
                List<string> parts = new List<string>();
                object ars = TryRead(fn, "ArticleReferences", null);
                if (ars != null) foreach (object ar in (IEnumerable)ars) parts.Add(PropText(ar, "PartNr") ?? "");
                d["parts"] = parts;
                List<Dictionary<string, object>> conductors = new List<Dictionary<string, object>>();
                object conns = TryRead(fn, "CableConnections", null);
                if (conns != null) foreach (object c in (IEnumerable)conns)
                {
                    if (c == null) continue;
                    Dictionary<string, object> cd = new Dictionary<string, object>();
                    cd["name"] = PropText(c, "Name") ?? "";
                    object cp = TryRead(c, "Properties", null);
                    if (cp != null)
                    {
                        cd["designation"] = PropText(cp, "CONNECTION_DESIGNATION") ?? "";
                        cd["colour"] = PropText(cp, "CONNECTION_WIRENUMBER") ?? "";
                        cd["crossSection"] = PropText(cp, "CONNECTION_WIRECROSSSECTION_WITH_UNIT") ?? "";
                    }
                    object s1 = TryRead(c, "StartSymbolReference", null), s2 = TryRead(c, "EndSymbolReference", null);
                    cd["source"] = s1 == null ? "" : (PropText(s1, "Name") ?? "");
                    cd["target"] = s2 == null ? "" : (PropText(s2, "Name") ?? "");
                    object cpg = TryRead(c, "Page", null);
                    cd["page"] = cpg == null ? null : PropText(cpg, "Name");
                    conductors.Add(cd);
                }
                d["conductors"] = conductors;
'''


def live_cables(contains: str = None, timeout_seconds: float = 120.0) -> dict:
    """
    The project's cables with their conductors. Read-only.

    Lists every cable function (placed definition lines and unplaced cables
    alike) with its part(s), function text, page and the connections it
    carries: conductor designation, colour, cross-section, source and target
    device. A cable whose conductor list is empty crosses no generated
    connection yet: run eplan_generate_connections, or move the line.

    Args:
        contains: Only cables whose name contains this ("-W1", "+CE").
        timeout_seconds: Default 120.

    Returns:
        {"success", "cables": [{"handle", "name", "text", "page", "parts",
        "conductors": [{"designation" (wire number), "colour", "crossSection",
        "source", "target", "page"}]}], "count"}.
    """
    try:
        contains_cs = cs_escape(cs_text(contains, "contains")) if contains else ""
    except SchematicValueError as exc:
        return _err(exc)

    body = '''
            string contains = "''' + contains_cs + '''";
            List<Dictionary<string, object>> cables = new List<Dictionary<string, object>>();
            foreach (object fn in AllFunctions(project))
            {
                if (fn == null || fn.GetType().Name != "Cable") continue;
                string name = PropText(fn, "Name") ?? "";
                if (contains != "" && name.IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0) continue;
''' + _CABLE_DICT + '''
                cables.Add(d);
            }
            results["cables"] = cables;
            results["count"] = cables.Count;
            results["success"] = true;
'''
    return _execute_script(
        live._script("LiveCables_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_TERM),
        timeout=timeout_seconds,
    )


_ASSIGN_BODY = '''
            object page = FindPage(project, "PAGENAME");
            object cable = null;
            string wantedCable = "CABLENAME";
            foreach (object pl in PagePlacements(page))
            {
                if (pl == null || pl.GetType().Name != "Cable") continue;
                string n = PropText(pl, "Name") ?? "";
                if (n == wantedCable || Handle(pl) == wantedCable || (n.Length > 0 && n.EndsWith(wantedCable) && wantedCable.StartsWith("-"))) { cable = pl; break; }
            }
            if (cable == null) throw new Exception("No cable definition line '" + wantedCable + "' on page PAGENAME.");
            object bb = cable.GetType().GetMethod("GetBoundingBox", Type.EmptyTypes).Invoke(cable, null);
            double cx1 = 1e9, cx2 = -1e9, cy1 = 1e9, cy2 = -1e9;
            foreach (object p in (IEnumerable)bb)
            {
                double px = Convert.ToDouble(p.GetType().GetProperty("X").GetValue(p, null)), py = Convert.ToDouble(p.GetType().GetProperty("Y").GetValue(p, null));
                cx1 = Math.Min(cx1, px); cx2 = Math.Max(cx2, px); cy1 = Math.Min(cy1, py); cy2 = Math.Max(cy2, py);
            }
            bool horizontal = (cx2 - cx1) >= (cy2 - cy1);
            double cmid = horizontal ? (cy1 + cy2) / 2.0 : (cx1 + cx2) / 2.0;
            object cableParts = TryRead(cable, "NameParts", null);
            Type finderType = FindType("Eplan.EplApi.DataModel.DMObjectsFinder");
            object finder = Activator.CreateInstance(finderType, new object[] { project });
            Type cfT = FindType("Eplan.EplApi.DataModel.ConnectionsFilter");
            object cf = Activator.CreateInstance(cfT);
            MethodInfo gc = finderType.GetMethod("GetConnections", new Type[] { cfT });
            List<Dictionary<string, object>> assigned = new List<Dictionary<string, object>>();
            List<string> errors = new List<string>();
            foreach (object cn in (IEnumerable)gc.Invoke(finder, new object[] { cf }))
            {
                if (cn == null) continue;
                object pg = TryRead(cn, "Page", null);
                if (pg == null || PropText(pg, "Name") != "PAGENAME") continue;
                object sr1 = TryRead(cn, "StartSymbolReference", null), sr2 = TryRead(cn, "EndSymbolReference", null);
                if (sr1 == null || sr2 == null) continue;
                object l1 = TryRead(sr1, "Location", null), l2 = TryRead(sr2, "Location", null);
                if (l1 == null || l2 == null) continue;
                double x1 = Convert.ToDouble(l1.GetType().GetProperty("X").GetValue(l1, null)), y1 = Convert.ToDouble(l1.GetType().GetProperty("Y").GetValue(l1, null));
                double x2 = Convert.ToDouble(l2.GetType().GetProperty("X").GetValue(l2, null)), y2 = Convert.ToDouble(l2.GetType().GetProperty("Y").GetValue(l2, null));
                object sp = TryRead(cn, "StartSymbolConnPoint", null), ep = TryRead(cn, "EndSymbolConnPoint", null);
                object pl1 = sp == null ? null : TryRead(sp, "Location", null), pl2 = ep == null ? null : TryRead(ep, "Location", null);
                if (pl1 != null) { x1 += Convert.ToDouble(pl1.GetType().GetProperty("X").GetValue(pl1, null)); y1 += Convert.ToDouble(pl1.GetType().GetProperty("Y").GetValue(pl1, null)); }
                if (pl2 != null) { x2 += Convert.ToDouble(pl2.GetType().GetProperty("X").GetValue(pl2, null)); y2 += Convert.ToDouble(pl2.GetType().GetProperty("Y").GetValue(pl2, null)); }
                bool crosses;
                if (horizontal)
                    crosses = Math.Abs(x1 - x2) < 0.01 && x1 >= cx1 && x1 <= cx2 && Math.Min(y1, y2) < cmid && Math.Max(y1, y2) > cmid;
                else
                    crosses = Math.Abs(y1 - y2) < 0.01 && y1 >= cy1 && y1 <= cy2 && Math.Min(x1, x2) < cmid && Math.Max(x1, x2) > cmid;
                if (!crosses) continue;
                object cp = TryRead(cn, "Properties", null);
                Dictionary<string, object> d = new Dictionary<string, object>();
                d["designation"] = cp == null ? "" : (PropText(cp, "CONNECTION_DESIGNATION") ?? "");
                d["source"] = PropText(sr1, "Name"); d["target"] = PropText(sr2, "Name");
                object already = TryRead(cn, "CableDefinitionLine", null);
                if (already != null && Handle(already) == Handle(cable)) { d["assigned"] = "already"; assigned.Add(d); continue; }
                try
                {
                    try { MethodInfo lk = MethodByShape(cn.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(cn, null); } catch { }
                    GetWritable(cn.GetType(), "CableNameParts").SetValue(cn, cableParts, null);
                    d["assigned"] = "now";
                }
                catch (Exception e) { d["assigned"] = "failed"; errors.Add((string)d["designation"] + ": " + Flatten(e)); }
                assigned.Add(d);
            }
            results["cable"] = PropText(cable, "Name");
            results["handle"] = Handle(cable);
            results["orientation"] = horizontal ? "horizontal" : "vertical";
            results["crossed"] = assigned;
            results["errors"] = errors;
            results["success"] = errors.Count == 0;
'''


_REASSIGN_TAIL = '''
            if (REASSIGN)
            {
                // "Asignar conexiones": the part's wire templates hand their
                // colour / cross-section to the conductors (EPL.DEFAULT-CABLE
                // turned BU/BU/BU into BK/BN/GY). Verified 2026-11-03.
                Type csT = FindType("Eplan.EplApi.HEServices.CableService");
                object csvc = Activator.CreateInstance(csT);
                Type apT = FindType("Eplan.EplApi.DataModel.AnyPropertyId");
                Array excl = Array.CreateInstance(apT, 0);
                MethodInfo m = null;
                foreach (MethodInfo mi in csT.GetMethods())
                    if (mi.Name == "DoReassignWires" && mi.GetParameters().Length == 3 && mi.GetParameters()[0].ParameterType.Name == "Function") m = mi;
                if (m == null) throw new Exception("CableService.DoReassignWires(Function, bool, AnyPropertyId[]) not found.");
                try { MethodInfo lk = MethodByShape(cable.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(cable, null); } catch { }
                try { m.Invoke(csvc, new object[] { cable, true, excl }); results["reassignedFromPart"] = true; }
                catch (Exception e) { results["reassignedFromPart"] = false; errors.Add("DoReassignWires: " + Flatten(e)); results["success"] = false; }
            }
'''


def live_assign_cable_connections(page: str, cable: str, generate: bool = True,
                                  reassign_from_part: bool = False,
                                  allow_real_project: bool = False,
                                  timeout_seconds: float = 180.0) -> dict:
    """
    Make the connections a cable definition line crosses its conductors.
    WRITES - scratch-only by default.

    A line placed by the API (or moved afterwards) crosses wires that EPLAN
    does not assign to it on its own; this does what drawing the line in the
    GUI does: every connection on the page whose run straddles the line gets
    the cable's name, and after one connection update the cable lists them
    as conductors. Safe to repeat: already-assigned wires are reported as
    "already".

    Args:
        page: Page name, as live_query_pages reports it.
        cable: The cable's full name ("=+CE-W1"), short tag ("-W1") or
            handle.
        generate: Regenerate the page's connections afterwards (default
            True) so the cable's conductor list is current.
        reassign_from_part: Also run "Asignar conexiones" so the cable
            part's wire templates give the conductors their colour and
            cross-section (default False; the placing tool passes True when
            a part is attached). Without a part it changes nothing.
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: Default 180.

    Returns:
        {"success", "cable", "handle", "orientation", "crossed": [{
        "designation", "source", "target", "assigned": "now"|"already"|
        "failed"}], "errors", "conductors" (after generate)}.
    """
    try:
        page = cs_text(page, "page")
        cable = cs_text(cable, "cable")
    except SchematicValueError as exc:
        return _err(exc)
    def _run(reassign):
        body = (_guard_prelude(allow_real_project)
                + _ASSIGN_BODY.replace("PAGENAME", cs_escape(page)).replace("CABLENAME", cs_escape(cable))
                + _REASSIGN_TAIL.replace("REASSIGN", "true" if reassign else "false"))
        return _execute_script(
            live._script("LiveCableAssign_" + uuid.uuid4().hex[:6], body,
                         extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_TERM),
            timeout=timeout_seconds,
        )

    r = _run(False)
    res = r.get("results") if isinstance(r.get("results"), dict) else r
    if generate and isinstance(res, dict) and res.get("success"):
        from .generate import generate_connections
        from . import target as _target
        # PROJECTNAME is passed explicitly: without it the action runs on
        # whatever project is current in the GUI, not on the target.
        wanted = len([c for c in res.get("crossed") or [] if c.get("assigned") in ("now", "already")])

        def _read():
            after = live_cables(contains=res.get("cable") or cable, timeout_seconds=timeout_seconds)
            after_res = after.get("results") if isinstance(after.get("results"), dict) else after
            for c in (after_res or {}).get("cables") or []:
                if c.get("handle") == res.get("handle"):
                    return c.get("conductors") or []
            return []

        # Measured on 2026.0.3: the first connection update after the
        # assignment does not yet list the conductors, the second does. So
        # update, read, and update once more while the count is short.
        runs = 0
        conductors = []
        while runs < 3:
            g = generate_connections(project_name=_target.get() or None, page_name=page)
            runs += 1
            if not g.get("success"):
                res["generateError"] = g.get("error") or g.get("eplanMessages")
                break
            conductors = _read()
            if len(conductors) >= wanted:
                break
        if reassign_from_part and conductors:
            # The templates can only be handed to conductors that exist, so
            # this runs after the connection update, then one more update.
            r2 = _run(True)
            res2 = r2.get("results") if isinstance(r2.get("results"), dict) else r2
            res["reassignedFromPart"] = bool(isinstance(res2, dict) and res2.get("reassignedFromPart"))
            if isinstance(res2, dict) and not res2.get("success"):
                res["reassignError"] = res2.get("error") or res2.get("errors")
            g = generate_connections(project_name=_target.get() or None, page_name=page)
            runs += 1
            if g.get("success"):
                conductors = _read()
        res["connectionsGenerated"] = runs
        res["conductors"] = conductors
    return r


def live_place_cable_definition(page: str, name: str, x1: float, y1: float,
                                x2: float, y2: float, part: str = None,
                                text: str = None, properties: dict = None,
                                symbol: str = "CABDL", variant: int = 0,
                                generate: bool = True,
                                allow_real_project: bool = False,
                                timeout_seconds: float = 180.0) -> dict:
    """
    Place a cable definition line across connections and name it. WRITES -
    scratch-only by default.

    Draw the line (x1,y1)-(x2,y2) so it crosses the connection lines that
    belong to the cable - a horizontal line under the terminal strip across
    the vertical wires to the field devices is the usual case. Keep it clear
    of the connection definition points (the wire-number symbols): cross the
    bare wire. Every crossed connection becomes a conductor of the cable;
    with a cable part attached EPLAN takes colours and cross-sections from
    the part's connection templates. The conductors are read back, so an
    empty list means the line crossed nothing (wrong y, or the wires are
    not generated connections yet).

    Args:
        page: Page name, as live_query_pages reports it.
        name: Cable tag, e.g. "-W1" or "=+CE-W1".
        x1, y1, x2, y2: Line ends in mm.
        part: Cable part number (e.g. an ÖLFLEX from the parts database).
        text: Function text ("es_ES@...;en_US@...;" for both languages).
        properties: Extra {"PROPERTY_NAME": value} on the cable.
        symbol: SPECIAL symbol for the line (default CABDL).
        variant: Symbol variant (default 0).
        generate: Assign the crossed connections and regenerate (default
            True) - see live_assign_cable_connections; EPLAN does not do it
            for an API-placed line. False places the bare line.
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: Default 180.

    Returns:
        {"success", "handle", "name", "page", "parts", "conductors": [...]} -
        same shape as one entry of live_cables.
    """
    try:
        page = cs_text(page, "page")
        name = cs_text(name, "name")
        symbol = cs_text(symbol, "symbol")
        coords = [float(v) for v in (x1, y1, x2, y2)]
        part_cs = cs_escape(cs_text(part, "part")) if part else ""
        text_cs = cs_escape(cs_text(text, "text")) if text else ""
        if properties is not None and not isinstance(properties, dict):
            raise SchematicValueError("properties must be a dict of {name: value}.")
    except (SchematicValueError, TypeError, ValueError) as exc:
        return _err(exc) if isinstance(exc, SchematicValueError) else {
            "success": False, "error": "x1, y1, x2, y2 must be numbers."}
    props_cs = "".join('            propsIn["%s"] = "%s";\n' % (cs_escape(str(k)), cs_escape(str(v)))
                       for k, v in (properties or {}).items())

    c1 = "%r, %r" % (coords[0], coords[1])
    c2 = "%r, %r" % (coords[2], coords[3])

    body = _guard_prelude(allow_real_project) + '''
            object page = FindPage(project, "''' + cs_escape(page) + '''");
            Type cT = FindType("Eplan.EplApi.DataModel.EObjects.Cable");
            object fn = Activator.CreateInstance(cT);
            object variant = MakeVariantT(project, "SPECIAL", "''' + cs_escape(symbol) + '''", ''' + str(int(variant)) + ''');
            MethodInfo create = RequireMethod(cT, "Create", new string[] { "Page", "SymbolVariant", "PointD", "PointD" }, false);
            Type pt = create.GetParameters()[2].ParameterType;
            Call(create, fn, new object[] { page, variant, MakePoint(pt, ''' + c1 + '''), MakePoint(pt, ''' + c2 + ''') });
            try { MethodInfo lk = MethodByShape(fn.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(fn, null); } catch { }
            // A bare "-W1" would become "=+-W1" (empty structures): give it
            // the page's own plant/location like the GUI does.
            string cableName = "''' + cs_escape(name) + '''";
            if (!cableName.Contains("=") && !cableName.Contains("+"))
            {
                object pprops = TryRead(page, "Properties", null);
                string plant = PropText(pprops, "DESIGNATION_PLANT") ?? "";
                string loc = PropText(pprops, "DESIGNATION_LOCATION") ?? "";
                cableName = "=" + plant + "+" + loc + cableName;
            }
            GetWritable(fn.GetType(), "Name").SetValue(fn, cableName, null);
            object props = TryRead(fn, "Properties", null);
            string text = "''' + text_cs + '''";
            string part = "''' + part_cs + '''";
            if (text != "") SetProp(props, "FUNC_TEXT", text);
            if (part != "") AddPartT(fn, part, results);
            Dictionary<string, string> propsIn = new Dictionary<string, string>();
''' + props_cs + '''
            Dictionary<string, object> written = new Dictionary<string, object>();
            foreach (KeyValuePair<string, string> kv in propsIn) written[kv.Key] = SetProp(props, kv.Key, kv.Value);
            if (written.Count > 0) results["properties"] = written;
            {
''' + _CABLE_DICT + '''
                foreach (KeyValuePair<string, object> kv in d) results[kv.Key] = kv.Value;
            }
            results["success"] = true;
'''
    r = _execute_script(
        live._script("LiveCableDef_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_TERM),
        timeout=timeout_seconds,
    )
    res = r.get("results") if isinstance(r.get("results"), dict) else r
    if generate and isinstance(res, dict) and res.get("success"):
        a = live_assign_cable_connections(page, res.get("handle"), generate=True,
                                          reassign_from_part=bool(part),
                                          allow_real_project=allow_real_project,
                                          timeout_seconds=timeout_seconds)
        a_res = a.get("results") if isinstance(a.get("results"), dict) else a
        if isinstance(a_res, dict):
            res["crossed"] = a_res.get("crossed")
            res["conductors"] = a_res.get("conductors") or []
            res["connectionsGenerated"] = a_res.get("connectionsGenerated")
            if "reassignedFromPart" in a_res:
                res["reassignedFromPart"] = a_res.get("reassignedFromPart")
            if not a_res.get("success"):
                res["assignError"] = a_res.get("error") or a_res.get("errors")
    return r
