"""
Terminal strips as EPLAN sees them: which strips the project has, whether
each one has its TERMINAL STRIP DEFINITION (the function that carries the
strip's own part, text and sorting, without which the terminal diagram
report has nothing to head the page with), and a writer that adds the
missing definition.

Learned live on 2026.0.3 (scratch copy of TEST-S7-1200):

- The definition is an `EObjects.TerminalStrip` function (function category
  TerminalDefText, group 1, id 1 = "Definición de regleta de bornes"). It is
  either placed on a page as the SPECIAL/TDEF symbol or left unplaced
  (visible in the terminal strip navigator only). Both are the same thing to
  the reports.
- Terminals (`EObjects.Terminal`) carry their strip in the name before the
  ":" ("=+CE-X1:3"), so a strip is "every terminal whose name shares that
  prefix" and a definition is matched to it by its full Name.
- Creating an unplaced definition: `new TerminalStrip()` then the INSTANCE
  `Create(Project, FunctionDefinition)` with the definition built from
  `new FunctionDefinition(project, FunctionCategory.TerminalDefText, 1, 1)`,
  then lock and write `Name`. A placed one takes `Create(Page, SymbolVariant,
  PointD, PointD)` with SPECIAL/TDEF and the insertion point twice.
"""

import uuid

from ._base import cs_escape
from .scripted import _execute_script
from . import live, schematic
from .schematic import _err, _guard_prelude
from .schematic_model import cs_bool, cs_text, SchematicValueError


_HELPERS_TERM = r'''
    // A fresh SymbolLibrary + Symbol + SymbolVariant per use (a variant
    // instance cannot be reused for a second Create).
    static object MakeVariantT(object project, string lib, string sym, int v)
    {
        Type libType = FindType("Eplan.EplApi.DataModel.MasterData.SymbolLibrary");
        Type symType = FindType("Eplan.EplApi.DataModel.MasterData.Symbol");
        Type varType = FindType("Eplan.EplApi.DataModel.MasterData.SymbolVariant");
        object library = libType.GetConstructor(new Type[] { project.GetType(), typeof(string) }).Invoke(new object[] { project, lib });
        object symbol = symType.GetConstructor(new Type[] { libType, typeof(string) }).Invoke(new object[] { library, sym });
        return varType.GetConstructor(new Type[] { symType, typeof(int) }).Invoke(new object[] { symbol, v });
    }

    static object MakeFunctionDefinition(object project, string category, short group, short id)
    {
        Type fdType = FindType("Eplan.EplApi.DataModel.FunctionDefinition");
        ConstructorInfo ctor = null;
        foreach (ConstructorInfo c in fdType.GetConstructors())
        {
            ParameterInfo[] ps = c.GetParameters();
            if (ps.Length == 4 && ps[1].ParameterType.Name == "FunctionCategory" && ps[2].ParameterType == typeof(short)) ctor = c;
        }
        if (ctor == null) throw new Exception("FunctionDefinition has no (Project, FunctionCategory, short, short) ctor.");
        object cat = Enum.Parse(ctor.GetParameters()[1].ParameterType, category);
        return ctor.Invoke(new object[] { project, cat, group, id });
    }

    static string StripOf(string name)
    {
        int i = name.IndexOf(':');
        return i < 0 ? name : name.Substring(0, i);
    }

    static string ShortTag(string full)
    {
        // "=+CE-X1" -> "-X1"
        int i = full.IndexOf('-');
        return i < 0 ? full : full.Substring(i);
    }

    static IEnumerable AllFunctions(object project)
    {
        Type finderType = FindType("Eplan.EplApi.DataModel.DMObjectsFinder");
        object finder = Activator.CreateInstance(finderType, new object[] { project });
        Type filterType = FindType("Eplan.EplApi.DataModel.FunctionsFilter");
        object filter = Activator.CreateInstance(filterType);
        MethodInfo getFunctions = finderType.GetMethod("GetFunctions", new Type[] { filterType });
        return (IEnumerable)getFunctions.Invoke(finder, new object[] { filter });
    }

    static void AddPartT(object fn, string part, Dictionary<string, object> r)
    {
        object ars = TryRead(fn, "ArticleReferences", null);
        if (ars != null) foreach (object ar in (IEnumerable)ars)
            if (PropText(ar, "PartNr") == part) { r["part"] = "already present"; return; }
        MethodInfo add = fn.GetType().GetMethod("AddArticleReference", new Type[] { typeof(string) });
        Call(add, fn, new object[] { part });
        r["part"] = part;
    }
'''


def _strip_dict_cs():
    return '''
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
'''


def live_terminal_strips(contains: str = None, timeout_seconds: float = 120.0) -> dict:
    """
    The project's terminal strips, their terminals and whether each strip has
    a terminal strip definition. Read-only.

    A strip without a definition still draws and still gets a terminal
    diagram, but the diagram header has no part, no text and no sorting
    behind it, and "Check project" reports it. Run this before the reports.

    Args:
        contains: Only strips whose name contains this ("-X1", "+CE").
        timeout_seconds: Default 120.

    Returns:
        {"success", "strips": [{"strip" (full name "=+CE-X1"), "terminals"
        (count), "designations": [...first 60...], "definition": {"handle",
        "name", "text", "page" (None when unplaced), "parts"} or None}],
        "definitionsWithoutTerminals": [...]}.
    """
    try:
        contains_cs = cs_escape(cs_text(contains, "contains")) if contains else ""
    except SchematicValueError as exc:
        return _err(exc)

    body = '''
            string contains = "''' + contains_cs + '''";
            Dictionary<string, Dictionary<string, object>> strips = new Dictionary<string, Dictionary<string, object>>();
            Dictionary<string, List<string>> designations = new Dictionary<string, List<string>>();
            Dictionary<string, Dictionary<string, object>> defs = new Dictionary<string, Dictionary<string, object>>();
            foreach (object fn in AllFunctions(project))
            {
                if (fn == null) continue;
                string tn = fn.GetType().Name;
                string name = PropText(fn, "Name") ?? "";
                if (tn == "TerminalStrip")
                {
                    if (contains != "" && name.IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0) continue;
''' + _strip_dict_cs() + '''
                    defs[name] = d;
                }
                else if (tn == "Terminal" && (PropText(fn, "FunctionCategory") ?? "") == "Terminal")
                {
                    // PLC connection points are EObjects.Terminal too, with
                    // category PLCTerminal: they are not strip terminals.
                    string strip = StripOf(name);
                    if (contains != "" && strip.IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    if (!designations.ContainsKey(strip)) designations[strip] = new List<string>();
                    string desig = name.Length > strip.Length ? name.Substring(strip.Length + 1) : "";
                    if (!designations[strip].Contains(desig)) designations[strip].Add(desig);
                }
            }
            List<Dictionary<string, object>> outStrips = new List<Dictionary<string, object>>();
            foreach (KeyValuePair<string, List<string>> kv in designations)
            {
                Dictionary<string, object> s = new Dictionary<string, object>();
                s["strip"] = kv.Key;
                s["terminals"] = kv.Value.Count;
                s["designations"] = kv.Value.Count > 60 ? kv.Value.GetRange(0, 60) : kv.Value;
                s["definition"] = defs.ContainsKey(kv.Key) ? defs[kv.Key] : null;
                outStrips.Add(s);
            }
            List<Dictionary<string, object>> orphans = new List<Dictionary<string, object>>();
            foreach (KeyValuePair<string, Dictionary<string, object>> kv in defs)
                if (!designations.ContainsKey(kv.Key)) orphans.Add(kv.Value);
            results["strips"] = outStrips;
            results["definitionsWithoutTerminals"] = orphans;
            results["success"] = true;
'''
    return _execute_script(
        live._script("LiveTerminalStrips_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_TERM),
        timeout=timeout_seconds,
    )


def live_set_terminal_strip_definition(strip: str, text: str = None, part: str = None,
                                       properties: dict = None, page: str = None,
                                       x: float = None, y: float = None,
                                       allow_real_project: bool = False,
                                       timeout_seconds: float = 120.0) -> dict:
    """
    Give a terminal strip its definition, creating it when the strip has none.
    WRITES - scratch-only by default.

    Finds the strip's definition by its full name and updates it, or creates
    one: unplaced (the terminal strip navigator shows it) unless `page` is
    given, in which case the SPECIAL/TDEF symbol is placed at x, y like
    "Insertar > Definición de regleta" does. Either way the reports and the
    project check are satisfied.

    Args:
        strip: Full strip name, e.g. "=+CE-X1". A short "-X1" is accepted
            when exactly one strip ends with it.
        text: Function text for the strip ("es_ES@Bornes de campo;en_US@Field
            terminals;" for both languages).
        part: Part number of the strip itself when the house style assigns
            one (end bracket, rail section); usually none.
        properties: Extra {"PROPERTY_NAME": value} written on the definition.
        page, x, y: Place the definition symbol on this page (page name as
            live_query_pages reports it). Omit for an unplaced definition.
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: Default 120.

    Returns:
        {"success", "strip", "created" (bool), "placed" (bool), "handle",
        "name", "text", "part"?, "properties"?}.
    """
    try:
        strip = cs_text(strip, "strip")
        text_cs = cs_escape(cs_text(text, "text")) if text else ""
        part_cs = cs_escape(cs_text(part, "part")) if part else ""
        page_cs = cs_escape(cs_text(page, "page")) if page else ""
        if page and (x is None or y is None):
            raise SchematicValueError("x and y are required when page is given.")
        if properties is not None and not isinstance(properties, dict):
            raise SchematicValueError("properties must be a dict of {name: value}.")
    except SchematicValueError as exc:
        return _err(exc)
    props_cs = "".join('            propsIn["%s"] = "%s";\n' % (cs_escape(str(k)), cs_escape(str(v)))
                       for k, v in (properties or {}).items())

    body = _guard_prelude(allow_real_project) + '''
            string wanted = "''' + cs_escape(strip) + '''";
            string text = "''' + text_cs + '''";
            string part = "''' + part_cs + '''";
            string pageName = "''' + page_cs + '''";
            Dictionary<string, string> propsIn = new Dictionary<string, string>();
''' + props_cs + '''
            // Resolve the strip: full name, or a unique short tag.
            List<string> stripNames = new List<string>();
            object existing = null;
            foreach (object fn in AllFunctions(project))
            {
                if (fn == null) continue;
                string tn = fn.GetType().Name;
                string name = PropText(fn, "Name") ?? "";
                if (tn == "Terminal" && (PropText(fn, "FunctionCategory") ?? "") == "Terminal") { string s = StripOf(name); if (!stripNames.Contains(s)) stripNames.Add(s); }
                else if (tn == "TerminalStrip" && (name == wanted || ShortTag(name) == wanted)) existing = fn;
            }
            string full = wanted;
            if (!stripNames.Contains(wanted))
            {
                List<string> hits = new List<string>();
                foreach (string s in stripNames) if (ShortTag(s) == wanted || s.EndsWith(wanted)) hits.Add(s);
                if (hits.Count == 1) full = hits[0];
                else if (hits.Count > 1) throw new Exception("Ambiguous strip '" + wanted + "': " + string.Join(", ", hits));
                else if (existing == null) throw new Exception("No terminals belong to strip '" + wanted + "'. Known strips: " + string.Join(", ", stripNames));
            }
            results["strip"] = full;

            object def = existing;
            bool created = false, placed = false;
            if (def == null)
            {
                Type tsT = FindType("Eplan.EplApi.DataModel.EObjects.TerminalStrip");
                def = Activator.CreateInstance(tsT);
                if (pageName != "")
                {
                    // Function.Create(Page, SymbolVariant, PointD, PointD) is
                    // NotImplemented for TerminalStrip; its own Create(Page)
                    // places the default definition symbol, then Location moves it.
                    object page = FindPage(project, pageName);
                    MethodInfo create = RequireMethod(tsT, "Create", new string[] { "Page" }, false);
                    Call(create, def, new object[] { page });
                    PropertyInfo locP = RequireWritable(tsT, "Location");
                    locP.SetValue(def, MakePoint(locP.PropertyType, ''' + repr(float(x or 0)) + ''', ''' + repr(float(y or 0)) + '''), null);
                    placed = true;
                }
                else
                {
                    object fd = MakeFunctionDefinition(project, "TerminalDefText", (short)1, (short)1);
                    MethodInfo create = RequireMethod(tsT, "Create", new string[] { "Project", "FunctionDefinition" }, false);
                    Call(create, def, new object[] { project, fd });
                }
                created = true;
                try { MethodInfo lk = MethodByShape(def.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(def, null); } catch { }
                GetWritable(def.GetType(), "Name").SetValue(def, full, null);
            }
            else
            {
                try { MethodInfo lk = MethodByShape(def.GetType(), "LockObject", new string[] { }, false); if (lk != null) lk.Invoke(def, null); } catch { }
                placed = TryRead(def, "Page", null) != null;
            }
            object props = TryRead(def, "Properties", null);
            if (text != "") SetProp(props, "FUNC_TEXT", text);
            if (part != "") AddPartT(def, part, results);
            Dictionary<string, object> written = new Dictionary<string, object>();
            foreach (KeyValuePair<string, string> kv in propsIn) written[kv.Key] = SetProp(props, kv.Key, kv.Value);
            if (written.Count > 0) results["properties"] = written;
            results["created"] = created;
            results["placed"] = placed;
            results["handle"] = Handle(def);
            results["name"] = PropText(def, "Name");
            results["text"] = props == null ? "" : (PropText(props, "FUNC_TEXT") ?? "");
            results["success"] = true;
'''
    return _execute_script(
        live._script("LiveStripDef_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC + _HELPERS_TERM),
        timeout=timeout_seconds,
    )
