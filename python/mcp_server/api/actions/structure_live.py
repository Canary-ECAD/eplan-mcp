"""
Repeated stations: copy drawn pages into another structure designation and
retag the devices on the copies, the way "copy pages with structure change"
works in the GUI.

Learned live on 2026.0.3 (scratch copy of TEST-S7-1200):

- `Page.CopyTo(project, PagePropertyList newName, NumerationMode, overwrite)`
  copies a page inside the project; the new name comes from the property
  list (DESIGNATION_PLANT / DESIGNATION_LOCATION / PAGE_COUNTER). The
  NumerationMode enum (Ignore, None, Number, NumberWithQuestionMark,
  NumberPreferPrefix) is only reachable through the CopyTo parameter type;
  FindType("Eplan.EplApi.DataModel.NumerationMode") does not resolve.
- The devices on the copy KEEP their full identifiers ("=+CE-X1" stays
  "=+CE-X1" on page "=ST2+CE/2"): nothing follows the page structure.
  DESIGNATION_PLANT on a function is not writable (S063113) and VisibleName
  with a full designation is silently ignored; writing `Function.Name` with
  the full "=ST2+CE-X1" works (terminal designations ":1+" are kept) but
  also turns the displayed tag into the full form, so VisibleName is set
  back to "-X1" afterwards - Name stays "=ST2+CE-X1".
- Shared devices (the CPU, the 24V distributors) must NOT be retagged, or
  the copy creates a second CPU: `keep_devices` lists them.
"""

import uuid

from ._base import cs_escape
from .scripted import _execute_script
from . import live, schematic
from .schematic import _err, _guard_prelude
from .schematic_model import cs_bool, cs_text, SchematicValueError


def live_copy_pages_to_structure(pages: list, target_plants: list,
                                 location: str = None, keep_devices: list = None,
                                 retag: bool = True, overwrite: bool = False,
                                 allow_real_project: bool = False,
                                 timeout_seconds: float = 300.0) -> dict:
    """
    Copy pages into other installation designations (=ST2, =ST3 ...) and
    retag their devices, for machines with repeated stations. WRITES -
    scratch-only by default.

    For every page in `pages` and every plant in `target_plants`: copies the
    page to "=<plant><location>/<same counter>" (location: the page's own
    unless overridden) and, with `retag`, renames every device on the copy
    from "=<old>+<loc>-X1" to "=<plant>+<loc>-X1". Wire numbers, function
    texts, parts and PLC addresses are copied as they are: renumber
    connections and re-address the PLC points afterwards.

    Devices listed in `keep_devices` are left untouched - use it for what is
    shared by all stations (the CPU "-A1", the distributors "-XD1"), or the
    copy would create a second CPU with its own channels.

    Args:
        pages: Source page names, as live_query_pages reports them
            ("=ST1+CE/2"; "+CE/2" when the source has no "=").
        target_plants: Plant designations WITHOUT "=", e.g. ["ST2", "ST3"].
        location: Location designation WITHOUT "+" for the copies (default:
            each source page's own). Applies to the retagged devices too.
        keep_devices: Device tags to leave as they are, by their displayed
            name without structures ("-A1", "-XD1") or full name
            ("=+CE-A1"). Default: none kept.
        retag: Rename the devices on the copies (default True). False
            copies the drawing only, devices still pointing at the source
            station's identifiers.
        overwrite: Replace an existing target page (default False: EPLAN
            refuses and the copy is reported as failed).
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: Default 300.

    Returns:
        {"success", "copies": [{"source", "plant", "newPage", "retagged",
        "kept": [...], "errors": [...]}], "pagesCreated": [...], "failed"}.
        Sub-pages (/2.a) keep their sub-counter on the copy (=ST2+CE/2.a).
    """
    try:
        if not isinstance(pages, list) or not pages:
            raise SchematicValueError("pages must be a non-empty list of page names.")
        if not isinstance(target_plants, list) or not target_plants:
            raise SchematicValueError("target_plants must be a non-empty list (e.g. [\"ST2\", \"ST3\"]).")
        pages_cs = [cs_escape(cs_text(p, "pages[]")) for p in pages]
        plants_cs = [cs_escape(cs_text(t, "target_plants[]").lstrip("=")) for t in target_plants]
        loc_cs = cs_escape(cs_text(location, "location").lstrip("+")) if location else ""
        keep_cs = [cs_escape(cs_text(k, "keep_devices[]")) for k in (keep_devices or [])]
    except SchematicValueError as exc:
        return _err(exc)

    def arr(items):
        return "new string[] { " + ", ".join('"%s"' % i for i in items) + " }"

    body = _guard_prelude(allow_real_project) + live._FINDER + '''
            string[] srcPages = ''' + arr(pages_cs) + ''';
            string[] plants = ''' + arr(plants_cs) + ''';
            string[] keep = ''' + arr(keep_cs) + ''';
            string locOverride = "''' + loc_cs + '''";
            bool retag = ''' + cs_bool(retag) + ''';
            bool overwrite = ''' + cs_bool(overwrite) + ''';

            Type pageT = FindType("Eplan.EplApi.DataModel.Page");
            Type pplT = FindType("Eplan.EplApi.DataModel.PagePropertyList");
            MethodInfo copyTo = null;
            foreach (MethodInfo mi in pageT.GetMethods())
                if (mi.Name == "CopyTo" && mi.GetParameters().Length == 4) copyTo = mi;
            if (copyTo == null) throw new Exception("Page.CopyTo(Project, PagePropertyList, NumerationMode, bool) not found. " + MemberList(pageT, false));
            Type nmT = copyTo.GetParameters()[2].ParameterType;
            object mode = Enum.Parse(nmT, "Ignore");

            List<Dictionary<string, object>> copies = new List<Dictionary<string, object>>();
            List<string> created = new List<string>();
            int failed = 0;
            foreach (string plant in plants)
            {
                foreach (string srcName in srcPages)
                {
                    Dictionary<string, object> c = new Dictionary<string, object>();
                    c["source"] = srcName; c["plant"] = plant;
                    List<string> kept = new List<string>(); List<string> errors = new List<string>();
                    try
                    {
                        object src = FindPage(project, srcName);
                        object sprops = TryRead(src, "Properties", null);
                        string srcLoc = PropText(sprops, "DESIGNATION_LOCATION") ?? "";
                        string loc = locOverride != "" ? locOverride : srcLoc;
                        int counter = 0;
                        try { counter = int.Parse(PropText(sprops, "PAGE_COUNTER")); } catch { }
                        string sub = "";
                        try { sub = PropText(sprops, "PAGE_SUBCOUNTER") ?? ""; } catch { }

                        object ppl = Activator.CreateInstance(pplT);
                        SetProp(ppl, "DESIGNATION_PLANT", plant);
                        if (loc != "") SetProp(ppl, "DESIGNATION_LOCATION", loc);
                        SetProp(ppl, "PAGE_COUNTER", (int)counter);
                        // "+CE/2.a" keeps its sub-counter; without this the copy
                        // lands on "=ST2+CE/2" and collides with the main page.
                        if (sub != "") SetProp(ppl, "PAGE_SUBCOUNTER", sub);

                        object np = Call(copyTo, src, new object[] { project, ppl, mode, overwrite });
                        if (np == null) throw new Exception("CopyTo returned null (target page exists and overwrite=false?)");
                        string newName = PropText(np, "Name") ?? "";
                        c["newPage"] = newName; created.Add(newName);

                        int n = 0;
                        if (retag)
                        {
                            try { MethodInfo l0 = MethodByShape(np.GetType(), "LockObject", new string[] { }, false); if (l0 != null) l0.Invoke(np, null); } catch { }
                            foreach (object pl in PagePlacements(np))
                            {
                                if (pl == null) continue;
                                string tn = pl.GetType().Name;
                                if (tn == "ConnectionDefinitionPoint" || tn == "PotentialDefinition" || tn == "Text" || tn == "Dimension") continue;
                                object props = TryRead(pl, "Properties", null); if (props == null) continue;
                                string vis = PropText(props, "FUNC_IDENTDEVICETAGWITHOUTSTRUCTURES_WITHSEPARATOR") ?? "";
                                if (vis == "") continue;
                                string before = PropText(pl, "Name") ?? "";
                                string devLoc = locOverride != "" ? "+" + locOverride : (PropText(props, "FUNC_DEVICETAG_ONLYSTRUCTURES") ?? "");
                                if (Array.IndexOf(keep, vis) >= 0 || Array.IndexOf(keep, before) >= 0 || Array.IndexOf(keep, PropText(props, "FUNC_FULLDEVICETAG") ?? "") >= 0)
                                { if (!kept.Contains(before)) kept.Add(before); continue; }
                                try
                                {
                                    try { MethodInfo lk = MethodByShape(pl.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(pl, null); } catch { }
                                    PropertyInfo nameProp = GetWritable(pl.GetType(), "Name");
                                    if (nameProp == null) { errors.Add(before + ": no writable Name"); continue; }
                                    string prevVis = PropText(pl, "VisibleName") ?? "";
                                    nameProp.SetValue(pl, "=" + plant + devLoc + vis, null);
                                    // Writing Name also rewrites the DISPLAYED tag to the
                                    // full "=ST2+CE-X1"; put back what the source showed:
                                    // the short "-X1", or nothing where the tag was hidden
                                    // (the k- terminals next to the PLC line).
                                    try { PropertyInfo visProp = GetWritable(pl.GetType(), "VisibleName"); if (visProp != null) visProp.SetValue(pl, prevVis == "" ? "" : vis, null); } catch { }
                                    n++;
                                }
                                catch (Exception e) { errors.Add(before + ": " + Flatten(e)); }
                            }
                        }
                        c["retagged"] = n;
                    }
                    catch (Exception e) { c["error"] = Flatten(e); failed++; }
                    c["kept"] = kept; c["errors"] = errors;
                    copies.Add(c);
                }
            }
            results["copies"] = copies;
            results["pagesCreated"] = created;
            results["failed"] = failed;
            results["success"] = failed == 0;
'''
    return _execute_script(
        live._script("LiveCopyPages_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC),
        timeout=timeout_seconds,
    )
