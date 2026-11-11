"""
Panel-layout captions: the property texts EPLAN draws next to a panel item
(device tag, part number, type designation, legend position ...). Read them
with their boxes, hide or show them, move them, set the legend position.

Learned live on 2026.0.3 (TEST-S7-1200, +CE/0):

- The texts are the placement's `PropertyPlacements` (ContextPropertyPlacement):
  `DisplayedProperty.AsInt` is the property id (20010 device tag, 20100 part
  number, 20200 type number, 20450 legend position), `GetDisplayString()`
  the text, `IsVisible`, `IsDocked`, `Location` (relative to the placement)
  and `GetBoundingBox()` (relative to Location).
- EVERY edit must come after `Function.UseLocalPropertyPlacements = true`
  on the placement. Without it the edit hits the SHARED property
  arrangement: every placement using it (ducts, breakers, rails, other
  strips) moves by the sum of the deltas, in memory only, and closing the
  project restores them. The tools set it, always.
- Setting Location on a docked text undocks the group; afterwards each text
  has its own Location but its drawn box = Location + a per-text offset, and
  on some placements an axis runs the other way. So positions are reached
  by measure-and-correct: apply the delta, re-read the box, flip the axis
  sign if the box went the wrong way, repeat (converges in 1-3 rounds).
- Legend position (20450) has no named property-list member; it is written
  through the `Property[AnyPropertyId]` indexer with the key taken from the
  20450 text's DisplayedProperty and a PropertyValue built by op_Implicit(int).
  A placement without a 20450 text cannot take a legend position this way.

Writes are scratch-guarded like every schematic writer (see schematic.py).
"""

import uuid

from ._base import cs_escape
from .scripted import _execute_script
from . import live, schematic
from .schematic import _err, _guard_prelude
from .schematic_model import cs_bool, cs_text, SchematicValueError


_HELPERS_PANEL = r'''
    // ---- captions of one panel placement -------------------------------------
    static List<Dictionary<string, object>> CaptionBoxes(object pl)
    {
        List<Dictionary<string, object>> list = new List<Dictionary<string, object>>();
        double lx = 0, ly = 0;
        object lo = TryRead(pl, "Location", null);
        if (lo != null) { Dictionary<string, object> ld = PtDict(lo); lx = Convert.ToDouble(ld["x"]); ly = Convert.ToDouble(ld["y"]); }
        object pps = TryRead(pl, "PropertyPlacements", null);
        if (pps == null) return list;
        int i = 0;
        foreach (object pp in (IEnumerable)pps)
        {
            if (pp == null) continue;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["index"] = i++;
            int id = -1;
            try { object dp = TryRead(pp, "DisplayedProperty", null); if (dp != null) id = Convert.ToInt32(dp.GetType().GetMethod("get_AsInt", Type.EmptyTypes).Invoke(dp, null)); } catch { }
            d["id"] = id;
            string t = ""; try { t = (string)pp.GetType().GetMethod("GetDisplayString", Type.EmptyTypes).Invoke(pp, null); } catch { }
            d["text"] = t ?? "";
            object vv = TryRead(pp, "IsVisible", null); d["visible"] = vv == null ? true : (bool)vv;
            object dk = TryRead(pp, "IsDocked", null); d["docked"] = dk == null ? (object)null : (bool)dk;
            try
            {
                object tl = TryRead(pp, "Location", null);
                if (tl != null) { Dictionary<string, object> td = PtDict(tl); d["location"] = new double[] { Math.Round(Convert.ToDouble(td["x"]), 3), Math.Round(Convert.ToDouble(td["y"]), 3) }; }
            }
            catch { }
            try
            {
                MethodInfo bb = MethodByShape(pp.GetType(), "GetBoundingBox", new string[] { }, false);
                if (bb != null && !string.IsNullOrEmpty(t) && (bool)d["visible"])
                {
                    double x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
                    foreach (object p in (IEnumerable)bb.Invoke(pp, null)) { Dictionary<string, object> q = PtDict(p); double x = Convert.ToDouble(q["x"]), y = Convert.ToDouble(q["y"]); x0 = Math.Min(x0, x); x1 = Math.Max(x1, x); y0 = Math.Min(y0, y); y1 = Math.Max(y1, y); }
                    if (x0 < 1e8) d["box"] = new double[] { Math.Round(lx + x0, 2), Math.Round(ly + y0, 2), Math.Round(lx + x1, 2), Math.Round(ly + y1, 2) };
                }
            }
            catch { }
            list.Add(d);
        }
        return list;
    }

    static bool CaptionMatches(Dictionary<string, object> cap, string sel)
    {
        if (string.IsNullOrEmpty(sel)) return false;
        int id; if (int.TryParse(sel, out id) && Convert.ToInt32(cap["id"]) == id) return true;
        return string.Equals((string)cap["text"], sel, StringComparison.Ordinal);
    }

    static object FindCaption(object pl, string sel)
    {
        object pps = TryRead(pl, "PropertyPlacements", null);
        if (pps == null) return null;
        int wantId; bool isId = int.TryParse(sel, out wantId);
        foreach (object pp in (IEnumerable)pps)
        {
            if (pp == null) continue;
            if (isId)
            {
                try { object dp = TryRead(pp, "DisplayedProperty", null); if (dp != null && Convert.ToInt32(dp.GetType().GetMethod("get_AsInt", Type.EmptyTypes).Invoke(dp, null)) == wantId) return pp; } catch { }
            }
            string t = ""; try { t = (string)pp.GetType().GetMethod("GetDisplayString", Type.EmptyTypes).Invoke(pp, null); } catch { }
            if (string.Equals(t, sel, StringComparison.Ordinal)) return pp;
        }
        return null;
    }

    static List<object> FindPanelItems(object page, string wanted)
    {
        List<object> hits = new List<object>();
        foreach (object pl in PagePlacements(page))
        {
            if (pl == null) continue;
            if (string.IsNullOrEmpty(wanted)) { hits.Add(pl); continue; }
            string h = Handle(pl);
            if (h == wanted) { hits.Clear(); hits.Add(pl); return hits; }
            string n = PropText(pl, "Name") ?? ""; string v = PropText(pl, "VisibleName") ?? "";
            if (n == wanted || v == wanted) hits.Add(pl);
        }
        return hits;
    }
'''


def live_panel_captions(page: str, ref: str = None, only_visible: bool = False,
                        timeout_seconds: float = 120.0) -> dict:
    """
    The caption texts of panel items (device tag, part, type, legend index)
    with their boxes in page mm. Read-only.

    Args:
        page: The panel layout page ("+CE/0").
        ref: One item: its handle ("124/17/1409/0") or its tag ("-X1",
            "=+CE-X1"). A tag shared by several placements (the terminals of
            a strip) returns all of them. Omit for every item on the page.
        only_visible: Leave hidden texts out (default False).
        timeout_seconds: Default 120.

    Returns:
        {"success", "items": [{"handle", "name", "clrType", "useLocal",
        "location", "captions": [{"index", "id" (20010 tag, 20100 part,
        20200 type, 20450 legend position), "text", "visible", "docked",
        "location" (relative), "box" [x0, y0, x1, y1] (page mm; only for
        visible texts - a hidden one has no extent)}]}]}.
    """
    try:
        page_cs = cs_escape(cs_text(page, "page"))
        ref_cs = cs_escape(cs_text(ref, "ref")) if ref else ""
    except SchematicValueError as exc:
        return _err(exc)
    body = '''
            object page = FindPage(project, "''' + page_cs + '''");
            List<Dictionary<string, object>> items = new List<Dictionary<string, object>>();
            foreach (object pl in FindPanelItems(page, "''' + ref_cs + '''"))
            {
                List<Dictionary<string, object>> caps = CaptionBoxes(pl);
                if (''' + cs_bool(only_visible) + ''') { List<Dictionary<string, object>> vis = new List<Dictionary<string, object>>(); foreach (Dictionary<string, object> c in caps) if ((bool)c["visible"]) vis.Add(c); caps = vis; }
                if ("''' + ref_cs + '''" == "" && caps.Count == 0) continue;
                Dictionary<string, object> d = new Dictionary<string, object>();
                d["handle"] = Handle(pl); d["name"] = PropText(pl, "Name") ?? ""; d["clrType"] = pl.GetType().Name;
                object ul = TryRead(pl, "UseLocalPropertyPlacements", null); d["useLocal"] = ul == null ? (object)null : (bool)ul;
                object lo = TryRead(pl, "Location", null); if (lo != null) { Dictionary<string, object> ld = PtDict(lo); d["location"] = new double[] { Convert.ToDouble(ld["x"]), Convert.ToDouble(ld["y"]) }; }
                d["captions"] = caps;
                items.Add(d);
            }
            results["items"] = items; results["page"] = "''' + page_cs + '''"; results["success"] = true;
'''
    return _execute_script(
        live._script("LivePanelCaptions_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_PANEL),
        timeout=timeout_seconds,
    )


def live_set_panel_captions(page: str, ref: str, hide: list = None, show: list = None,
                            positions: dict = None, legend_position: int = None,
                            allow_real_project: bool = False,
                            timeout_seconds: float = 300.0) -> dict:
    """
    Hide, show, move the captions of ONE panel item, or give it a legend
    position. WRITES - scratch-only by default.

    First switches the item to a LOCAL property arrangement
    (UseLocalPropertyPlacements), so the change touches only this item and
    survives closing the project. Then, in this order: show, hide, legend
    position, moves. A move is given as the wanted TOP-LEFT of the text box
    in page mm and reached by measure-and-correct (the text is undocked,
    moved, re-measured, corrected; a few rounds).

    Args:
        page: The panel layout page ("+CE/0").
        ref: The item's handle, or a tag that matches exactly one placement
            (several -> error listing the handles; use live_panel_captions).
        hide: Captions to hide, each a property id (20100, "20100") or the
            exact text ("PXC.3244559").
        show: Captions to make visible, same selectors.
        positions: {selector: [x, y]} - wanted top-left corner of each
            caption's box, page mm.
        legend_position: Integer for property 20450 (shown in the panel as
            the small index; the legend report lists it). Needs a 20450
            caption on the item; pass "20450" in `show` to display it.
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: Default 300.

    Returns:
        {"success", "handle", "name", "useLocal", "before": [captions],
        "after": [captions], "moves": [{"selector", "target", "reached",
        "rounds"}], "log": [...]}.
    """
    try:
        page_cs = cs_escape(cs_text(page, "page"))
        ref_cs = cs_escape(cs_text(ref, "ref"))
        hide_cs = [cs_escape(cs_text(str(h), "hide[]")) for h in (hide or [])]
        show_cs = [cs_escape(cs_text(str(h), "show[]")) for h in (show or [])]
        if positions is not None and not isinstance(positions, dict):
            raise SchematicValueError("positions must be {selector: [x, y]}.")
        pos_rows = []
        for sel, xy in (positions or {}).items():
            if not isinstance(xy, (list, tuple)) or len(xy) != 2:
                raise SchematicValueError("positions[%r] must be [x, y]." % (sel,))
            pos_rows.append((cs_escape(cs_text(str(sel), "positions key")), float(xy[0]), float(xy[1])))
        legend = None if legend_position is None else int(legend_position)
    except (SchematicValueError, TypeError, ValueError) as exc:
        return _err(exc if isinstance(exc, SchematicValueError) else SchematicValueError(str(exc)))

    def arr(items):
        return "new string[] { " + ", ".join('"%s"' % i for i in items) + " }"
    pos_table = ", ".join('new string[] { "%s", "%r", "%r" }' % (s, x, y) for s, x, y in pos_rows)

    body = _guard_prelude(allow_real_project) + '''
            object page = FindPage(project, "''' + page_cs + '''");
            try { MethodInfo l0 = MethodByShape(page.GetType(), "LockObject", new string[] { }, false); if (l0 != null) l0.Invoke(page, null); } catch { }
            List<object> hits = FindPanelItems(page, "''' + ref_cs + '''");
            if (hits.Count == 0) throw new Exception("No placement matches ref ''' + ref_cs + ''' on the page.");
            if (hits.Count > 1)
            {
                List<string> hs = new List<string>(); foreach (object h in hits) hs.Add(Handle(h) + " " + (PropText(h, "Name") ?? ""));
                throw new Exception("ref ''' + ref_cs + ''' matches " + hits.Count + " placements; use a handle: " + string.Join(", ", hs.ToArray()));
            }
            object pl = hits[0];
            List<string> log = new List<string>();
            try { MethodInfo lk = MethodByShape(pl.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(pl, null); } catch { }
            results["handle"] = Handle(pl); results["name"] = PropText(pl, "Name") ?? "";
            results["before"] = CaptionBoxes(pl);

            // 1. local arrangement, always
            PropertyInfo ul = GetWritable(pl.GetType(), "UseLocalPropertyPlacements");
            if (ul == null) throw new Exception("Placement has no UseLocalPropertyPlacements; captions cannot be edited safely. " + MemberList(pl.GetType(), false));
            if (!(bool)ul.GetValue(pl, null))
            {
                try { ul.SetValue(pl, true, null); }
                catch (Exception e1) { MethodInfo sw = MethodByShape(pl.GetType(), "SwitchLocalPropertyPlacements", new string[] { }, false); if (sw == null) throw new Exception("UseLocalPropertyPlacements=true failed: " + Flatten(e1)); sw.Invoke(pl, null); }
                log.Add("UseLocalPropertyPlacements -> " + ul.GetValue(pl, null));
            }
            results["useLocal"] = (bool)ul.GetValue(pl, null);

            // 2. show / hide
            foreach (string sel in ''' + arr(show_cs) + ''')
            { object pp = FindCaption(pl, sel); if (pp == null) { log.Add("show: no caption '" + sel + "'"); continue; } try { MethodInfo lp = MethodByShape(pp.GetType(), "LockObject", new string[] { }, false); if (lp != null) lp.Invoke(pp, null); } catch { } GetWritable(pp.GetType(), "IsVisible").SetValue(pp, true, null); log.Add("shown '" + sel + "'"); }
            foreach (string sel in ''' + arr(hide_cs) + ''')
            { object pp = FindCaption(pl, sel); if (pp == null) { log.Add("hide: no caption '" + sel + "'"); continue; } try { MethodInfo lp = MethodByShape(pp.GetType(), "LockObject", new string[] { }, false); if (lp != null) lp.Invoke(pp, null); } catch { } GetWritable(pp.GetType(), "IsVisible").SetValue(pp, false, null); log.Add("hidden '" + sel + "'"); }

            // 3. legend position via the Property[AnyPropertyId] indexer
            if (''' + ("true" if legend is not None else "false") + ''')
            {
                object lt = FindCaption(pl, "20450");
                if (lt == null) throw new Exception("No legend-position (20450) caption on this item: EPLAN's property arrangement for it has none, so the value cannot be addressed. Add 'Posición de leyenda' to the arrangement in EPLAN first.");
                object key = TryRead(lt, "DisplayedProperty", null);
                object props = GetReadable(pl.GetType(), "Properties").GetValue(pl, null);
                Type apT = key.GetType(); Type pvT = FindType("Eplan.EplApi.DataModel.PropertyValue");
                MethodInfo conv = null; foreach (MethodInfo m in pvT.GetMethods(BindingFlags.Public | BindingFlags.Static)) if (m.Name == "op_Implicit" && m.ReturnType == pvT && m.GetParameters()[0].ParameterType == typeof(int)) conv = m;
                PropertyInfo idx = null;
                for (Type t = props.GetType(); t != null && idx == null; t = t.BaseType)
                    foreach (PropertyInfo pi in t.GetProperties(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
                    { ParameterInfo[] ps = pi.GetIndexParameters(); if (pi.Name == "Property" && ps.Length == 1 && ps[0].ParameterType == apT) { idx = pi; break; } }
                if (idx == null || conv == null) throw new Exception("Property[AnyPropertyId] indexer or PropertyValue.op_Implicit(int) not found.");
                idx.SetValue(props, conv.Invoke(null, new object[] { ''' + str(legend if legend is not None else 0) + ''' }), new object[] { key });
                string after = ""; try { after = (string)lt.GetType().GetMethod("GetDisplayString", Type.EmptyTypes).Invoke(lt, null); } catch { }
                log.Add("legend position = ''' + str(legend if legend is not None else 0) + ''' (text now '" + after + "')");
            }

            // 4. moves: measure-and-correct on the box's top-left corner
            List<Dictionary<string, object>> moves = new List<Dictionary<string, object>>();
            string[][] wanted = new string[][] { ''' + pos_table + ''' };
            foreach (string[] w in wanted)
            {
                Dictionary<string, object> mv = new Dictionary<string, object>();
                mv["selector"] = w[0];
                double tx = double.Parse(w[1], System.Globalization.CultureInfo.InvariantCulture), ty = double.Parse(w[2], System.Globalization.CultureInfo.InvariantCulture);
                mv["target"] = new double[] { tx, ty };
                object pp = FindCaption(pl, w[0]);
                if (pp == null) { mv["error"] = "no caption '" + w[0] + "'"; moves.Add(mv); continue; }
                try { MethodInfo lp = MethodByShape(pp.GetType(), "LockObject", new string[] { }, false); if (lp != null) lp.Invoke(pp, null); } catch { }
                try { GetWritable(pp.GetType(), "IsDocked").SetValue(pp, false, null); } catch { }
                PropertyInfo locPi = GetWritable(pp.GetType(), "Location");
                double sx = 1, sy = 1; int rounds = 0; bool reached = false; double[] cur = null;
                for (int it = 0; it < 5; it++)
                {
                    cur = null;
                    foreach (Dictionary<string, object> c in CaptionBoxes(pl)) if (CaptionMatches(c, w[0]) && c.ContainsKey("box")) { double[] b = (double[])c["box"]; cur = new double[] { b[0], b[1] }; break; }
                    if (cur == null) { mv["error"] = "caption has no box (empty text?)"; break; }
                    double dx = tx - cur[0], dy = ty - cur[1];
                    if (Math.Abs(dx) <= 0.3 && Math.Abs(dy) <= 0.3) { reached = true; break; }
                    Dictionary<string, object> ld = PtDict(locPi.GetValue(pp, null));
                    locPi.SetValue(pp, MakePoint(locPi.PropertyType, Convert.ToDouble(ld["x"]) + dx * sx, Convert.ToDouble(ld["y"]) + dy * sy), null);
                    rounds++;
                    double[] now = null;
                    foreach (Dictionary<string, object> c in CaptionBoxes(pl)) if (CaptionMatches(c, w[0]) && c.ContainsKey("box")) { double[] b = (double[])c["box"]; now = new double[] { b[0], b[1] }; break; }
                    if (now == null) break;
                    if (Math.Abs(dx) > 0.3 && (now[0] - cur[0]) * dx < 0) sx = -sx;
                    if (Math.Abs(dy) > 0.3 && (now[1] - cur[1]) * dy < 0) sy = -sy;
                }
                mv["reached"] = reached; mv["rounds"] = rounds; if (cur != null) mv["final"] = cur;
                moves.Add(mv);
            }
            results["moves"] = moves;
            results["after"] = CaptionBoxes(pl);
            results["log"] = log;
            results["success"] = true;
'''
    return _execute_script(
        live._script("LiveSetPanelCaptions_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_PANEL),
        timeout=timeout_seconds,
    )
