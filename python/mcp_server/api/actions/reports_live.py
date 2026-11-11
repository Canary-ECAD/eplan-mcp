"""
Report pages through the live object model: create the cover sheet, the
parts list, the terminal diagrams, the panel legend ... as report blocks on
the open project, the way the "Reports" dialog does, and generate them.

Why this exists: the action layer only has `update_reports` (refresh what the
project already contains). Creating a report in the first place is
`Eplan.EplApi.HEServices.Reports.CreateReport(ReportBlock, firstPageName)`,
which the action surface does not wrap. Learned live on 2026.0.3:

- `ReportBlock.Create(project)`, then `Type` (a
  `DocumentTypeManager.DocumentType`, e.g. PartsList, PanelLayoutCaption,
  TerminalDiagram) and `FormName` ("F18_001") - the form must ALREADY BE IN
  THE PROJECT (project master data). Otherwise EPLAN throws S029153 and the
  API has no form synchronisation: the designer copies the form in with
  "Sincronizar proyecto actual" in the GUI first.
- `Reports.CreateReport(block, pageName)` needs a NON-EMPTY first page name
  (S029035 otherwise) and uses it when that page is free ("/1" gave /1;
  the terminal diagrams then followed as /2, /2.a, /3 ...); when it is
  taken the pages land on the next free counters (the panel legend asked
  for +CE/0.a landed on +CE/5 and +CE/6, one per mounting surface). So the
  tool reads the page list before and after and reports what was actually
  created, rather than echoing the requested name.
- `Reports.GenerateProject(project)` refreshes every report block.

Writes are scratch-guarded like every schematic writer (see schematic.py).
"""

import uuid

from ._base import cs_escape
from .scripted import _execute_script
from . import live, schematic
from .schematic import _err, _guard_prelude
from .schematic_model import cs_bool, cs_text, SchematicValueError


_PAGE_SNAPSHOT = '''
            List<string> %(var)s = new List<string>();
            {
                Type pfT = FindType("Eplan.EplApi.DataModel.PagesFilter");
                object pf = Activator.CreateInstance(pfT);
                MethodInfo gp = finderType.GetMethod("GetPages", new Type[] { pfT });
                foreach (object pg in (IEnumerable)gp.Invoke(finder, new object[] { pf }))
                    if (pg != null) %(var)s.Add(PropText(pg, "Name") ?? "");
            }
'''


def live_report_types(timeout_seconds: float = 60.0) -> dict:
    """
    The report types EPLAN can generate, by their API names. Read-only.

    Lists the DocumentTypeManager.DocumentType enum (the value that
    live_create_report takes as report_type) and the report pages the open
    project already has (every page whose type is not a drawing type, with
    its form), so a second parts list is not created by accident.
    Forms available on the workstation come from eplan_list_report_templates;
    which of them are inside the project is not readable through the API.

    Returns:
        {"success", "types": [{"name", "value"}], "existing": [{"page",
        "type", "form"}]}.
    """
    body = live._FINDER + '''
            Type dtmType = FindType("Eplan.EplApi.DataModel.DocumentTypeManager");
            Type docEnum = dtmType.GetNestedType("DocumentType");
            List<Dictionary<string, object>> types = new List<Dictionary<string, object>>();
            foreach (string n in Enum.GetNames(docEnum))
            {
                Dictionary<string, object> d = new Dictionary<string, object>();
                d["name"] = n;
                d["value"] = Convert.ToInt32(Enum.Parse(docEnum, n));
                types.Add(d);
            }
            results["types"] = types;

            // There is no ReportBlocksFilter in the object model (verified on
            // 2026.0.3), so "what reports does the project already have" is
            // read off the PAGES: every page whose type is not a drawing
            // type is a generated report page.
            List<Dictionary<string, object>> existing = new List<Dictionary<string, object>>();
            {
                string[] drawing = new string[] { "Circuit", "CircuitSingleLine", "Overview", "Graphics", "PanelLayout", "CircuitFluid", "ExternalDocument", "ProcessAndInstrumentationDiagram", "PanelLayout3D", "ModelView", "Topology", "Undefined" };
                Type pfT = FindType("Eplan.EplApi.DataModel.PagesFilter");
                object pf = Activator.CreateInstance(pfT);
                MethodInfo gp = finderType.GetMethod("GetPages", new Type[] { pfT });
                foreach (object pg in (IEnumerable)gp.Invoke(finder, new object[] { pf }))
                {
                    if (pg == null) continue;
                    string pt = PropText(pg, "PageType") ?? "";
                    if (Array.IndexOf(drawing, pt) >= 0) continue;
                    Dictionary<string, object> d = new Dictionary<string, object>();
                    d["page"] = PropText(pg, "Name") ?? "";
                    d["type"] = pt;
                    object ppl = TryRead(pg, "Properties", null);
                    d["form"] = ppl == null ? "" : (PropText(ppl, "PAGE_FORMULAR") ?? "");
                    existing.Add(d);
                }
            }
            results["existing"] = existing;
            results["success"] = true;
'''
    return _execute_script(
        live._script("LiveReportTypes_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC),
        timeout=timeout_seconds,
    )


def live_create_report(report_type: str, form_name: str = None,
                       page_name: str = None, generate: bool = True,
                       allow_real_project: bool = False,
                       timeout_seconds: float = 300.0) -> dict:
    """
    Add a report (cover sheet, parts list, terminal diagram, panel legend ...)
    to the open project and generate its pages. WRITES - scratch-only by default.

    Creates a report block of the given type with the given form, the same
    thing the "Informes > Nuevo" dialog does, and then generates the project
    reports so the pages appear. The pages' names are READ BACK: EPLAN uses
    the requested first-page name when it is free and the next free counters
    otherwise (a panel legend came out as +CE/5 and +CE/6).

    Args:
        report_type: A DocumentTypeManager.DocumentType name; get the list
            from live_report_types. The ones used by the house style:
            TitlePage (portada), PartsList (lista de artículos), DeviceTagList,
            TerminalDiagram (plano de bornes), TerminalStripOverview,
            CableDiagram / CableOverview, PanelLayoutCaption (leyenda de
            armarios), TableOfContents (índice), PotentialOverview,
            ConnectionList, PLCDiagram, PLCCardOverview.
        form_name: The form to use, e.g. "F26_003", "F18_001". MUST already be
            in the project's master data: EPLAN answers S029153 otherwise and
            the API cannot copy a form in - the designer syncs it in the GUI
            first. Omit to let EPLAN pick the project's default form for the
            type (settings), which also fails when none is set.
        page_name: First page name (e.g. "/0", "/1000", "+CE/5"). Used when
            free, else EPLAN takes the next free counter. Must not be empty
            (S029035); the tool passes "/1" when omitted.
        generate: Run GenerateProject after creating the block (default
            True). Without it the block exists but has no pages yet.
        allow_real_project: Must be True to write outside the scratch root.
        timeout_seconds: Default 300 - generating a large project's reports
            is slow.

    Returns:
        {"success", "created" (bool from CreateReport), "pagesBefore",
        "pagesAfter", "pagesCreated": [names], "reportType", "formName"}.
        An S029153 failure comes back with a "hint" naming the form to sync.
    """
    try:
        report_type = cs_text(report_type, "report_type")
        form_cs = cs_escape(cs_text(form_name, "form_name")) if form_name else ""
        # EPLAN refuses an EMPTY first-page name (S029035, strFirstPageName)
        # and then ignores a non-empty one; "/1" is a harmless placeholder.
        page_cs = cs_escape(cs_text(page_name, "page_name")) if page_name else "/1"
    except SchematicValueError as exc:
        return _err(exc)

    body = _guard_prelude(allow_real_project) + live._FINDER + (_PAGE_SNAPSHOT % {"var": "before"}) + '''
            Type dtmType = FindType("Eplan.EplApi.DataModel.DocumentTypeManager");
            Type docEnum = dtmType.GetNestedType("DocumentType");
            object docType = null;
            try { docType = Enum.Parse(docEnum, "''' + cs_escape(report_type) + '''", false); }
            catch
            {
                string[] names = Enum.GetNames(docEnum);
                Array.Sort(names);
                throw new Exception("Unknown report_type ''' + cs_escape(report_type) + '''. Valid values: " +
                    string.Join(", ", names));
            }

            Type projType = FindType("Eplan.EplApi.DataModel.Project");
            Type rbType = FindType("Eplan.EplApi.DataModel.ReportBlock");
            object block = Activator.CreateInstance(rbType);
            Call(RequireMethod(rbType, "Create", new string[] { "Project" }, false), block, new object[] { project });
            GetWritable(rbType, "Type").SetValue(block, docType, null);
            if ("''' + form_cs + '''" != "")
                GetWritable(rbType, "FormName").SetValue(block, "''' + form_cs + '''", null);

            Type repType = FindType("Eplan.EplApi.HEServices.Reports");
            object reports = Activator.CreateInstance(repType);
            MethodInfo createReport = RequireMethod(repType, "CreateReport", new string[] { "ReportBlock", "String" }, false);
            object okObj = Call(createReport, reports, new object[] { block, "''' + page_cs + '''" });
            results["created"] = okObj is bool ? (bool)okObj : true;

            if (''' + cs_bool(generate) + ''')
            {
                MethodInfo gen = RequireMethod(repType, "GenerateProject", new string[] { "Project" }, false);
                Call(gen, reports, new object[] { project });
                results["generated"] = true;
            }
            else results["generated"] = false;
''' + (_PAGE_SNAPSHOT % {"var": "after"}) + '''
            List<string> created = new List<string>();
            foreach (string n in after) if (!before.Contains(n)) created.Add(n);
            results["pagesBefore"] = before.Count;
            results["pagesAfter"] = after.Count;
            results["pagesCreated"] = created;
            results["reportType"] = "''' + cs_escape(report_type) + '''";
            results["formName"] = "''' + form_cs + '''";
            results["success"] = true;
'''
    r = _execute_script(
        live._script("LiveCreateReport_" + uuid.uuid4().hex[:6], body,
                     extra_helpers=schematic._HELPERS_SCHEMATIC),
        timeout=timeout_seconds,
    )
    err = ""
    if isinstance(r, dict):
        err = str(r.get("error") or (r.get("results") or {}).get("error") or "")
    if "S029153" in err:
        r["hint"] = ("EPLAN could not find form '%s' in the PROJECT master data. The API "
                     "cannot copy forms into a project: in EPLAN run Utilidades > Datos "
                     "maestros > Sincronizar proyecto actual (or Finalizar proyecto) so the "
                     "form is in the project, then call this again." % (form_name or "<default>"))
    return r
