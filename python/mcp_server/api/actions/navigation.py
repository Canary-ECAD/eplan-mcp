"""
Edit and navigation actions.
"""

from ._base import _get_connected_manager, _build_action


def edit_open_page(
    page_name: str,
    project_name: str = None,
    x: float = None,
    y: float = None
) -> dict:
    """
    Open a specific page in the editor.
    Action: edit

    Args:
        page_name: Page name to open
        project_name: Project path (optional)
        x: X coordinate to position cursor
        y: Y coordinate to position cursor
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "edit",
        PROJECTNAME=project_name,
        PAGENAME=page_name,
        X=x,
        Y=y
    )
    return manager.execute_action(action)


def edit_goto_device(
    device_name: str,
    project_name: str = None
) -> dict:
    """
    Navigate to a device in the project.
    Action: edit
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "edit",
        PROJECTNAME=project_name,
        DEVICENAME=device_name
    )
    return manager.execute_action(action)


def edit_open_layout_space(
    installation_space: str,
    project_name: str = None
) -> dict:
    """
    Open a layout/installation space.
    Action: edit
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "edit",
        PROJECTNAME=project_name,
        INSTALLATIONSPACE=installation_space
    )
    return manager.execute_action(action)


def close_pages() -> dict:
    """
    Close all selected pages in the editor.
    Action: XGedClosePage
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    return manager.execute_action("XGedClosePage")


def redraw_ged() -> dict:
    """
    Redraw the graphical editor.
    Action: gedRedraw

    Note: This action only works interactively. Under QuietMode (which this
    server always forces) the GED is not redrawn and the action returns FALSE.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    return manager.execute_action("gedRedraw")


def get_selected_pages() -> dict:
    """
    Get selected pages.
    Action: selectionset

    The result is returned in the calling context parameter "PAGES"
    (page names separated by ";", e.g. "=AP+ST1/1;=AP+ST1/2").
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "selectionset",
        TYPE="PAGES"
    )
    return manager.execute_action(action)


def preview_page(
    page_name: str = None,
    project_name: str = None,
    macro_name: str = None,
    open: bool = True
) -> dict:
    """
    Open or close the preview of a project page or macro.
    Action: XSDPreviewAction

    Args:
        page_name: Page name to preview (optional)
        project_name: Project path (optional)
        macro_name: Full path to a window/page macro (optional, with extension)
        open: True to open the preview, False to close it (maps to SHOW=1/0)

    Note: If both page_name and macro_name are empty, all project pages
    are shown in the preview.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XSDPreviewAction",
        PROJECTNAME=project_name,
        PAGENAME=page_name,
        MACRONAME=macro_name,
        SHOW="1" if open else "0"
    )
    return manager.execute_action(action)


def navigate_to_eec(object_id: str) -> dict:
    """
    Navigate to object in EPLAN Engineering Configuration.
    Action: navigateToEEC

    Args:
        object_id: Object ID in the EEC to navigate to (parameter EECOBJECTID).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "navigateToEEC",
        EECOBJECTID=object_id
    )
    return manager.execute_action(action)


def navigator_select(project: str, pages: list = None, open_page: bool = True) -> dict:
    """
    Focus an OPEN project in the page navigator and select pages there - the
    click a user would make. Selection-driven tools (eplan_set_page_property,
    eplan_close_project, eplan_get_selected_pages, ...) then act on that
    project instead of whatever the user last clicked. eplan_open_project
    cannot do this: it refuses a project that is already open.

    With a page of ANOTHER project open in the editor, the navigator selection
    alone does not move EPLAN's focus; open_page=True (default) then opens the
    first requested page and tries again. Pass False to never change the open
    page (the result then reports verified=False instead).

    Args:
        project: Name, full name or .elk path of an open project.
        pages: Page names to select (as shown in the navigator). Omit to only
            focus the project - its first page is then selected, because a bare
            project selection does not move the focus that actions read.
        open_page: Allow opening the first page when needed (see above).

    Returns:
        {"success", "project", "project_selected", "unresolved_pages",
         "opened_page", "focused_project", "selected_pages", "verified"}.
        verified is True only when EPLAN's own selection read-back shows every
        requested page AND eplan_get_current_project (the focus actions use)
        reports the target project ("action_focus").

    Runs as a one-off registered script action (registered, called, then
    unregistered): from a plain ExecuteScript script the same calls do not
    move the focus that actions read.
    """
    from ._base import cs_escape
    from .live import _script
    import uuid

    names = [str(p) for p in (pages or [])]
    want = "new string[] { " + ", ".join('"' + cs_escape(n) + '"' for n in names) + " }"
    body = '''            object target = PickProject(project, "''' + cs_escape(project or "") + '''");
            string targetName = PropText(target, "ProjectFullName");
            results["project"] = targetName;
            string[] want = ''' + want + ''';
            bool allowOpen = ''' + ("true" if open_page else "false") + ''';

            Type editType = FindType("Eplan.EplApi.HEServices.Edit");
            object edit = Activator.CreateInstance(editType);
            Type selType = FindType("Eplan.EplApi.HEServices.SelectionSet");
            bool projectSelected = false;
            try
            {
                projectSelected = (bool)Call(RequireMethod(editType, "SelectProjectInPagesNavigator",
                    new string[] { "Project" }, false), edit, new object[] { target });
            }
            catch (Exception ex) { results["project_select_err"] = Flatten(ex); }
            results["project_selected"] = projectSelected;

            Type finderType = FindType("Eplan.EplApi.DataModel.DMObjectsFinder");
            object finder = Activator.CreateInstance(finderType, new object[] { target });
            Type pfType = FindType("Eplan.EplApi.DataModel.PagesFilter");
            IEnumerable allPages = (IEnumerable)Call(RequireMethod(finderType, "GetPages",
                new string[] { pfType.Name }, false), finder, new object[] { Activator.CreateInstance(pfType) });
            List<object> hits = new List<object>();
            List<string> unresolved = new List<string>();
            foreach (string w in want)
            {
                object match = null;
                foreach (object pg in allPages)
                {
                    if (string.Equals(PropText(pg, "Name"), w, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(PropText(pg, "IdentifyingName"), w, StringComparison.OrdinalIgnoreCase))
                    { match = pg; break; }
                }
                if (match == null) unresolved.Add(w); else hits.Add(match);
            }
            results["unresolved_pages"] = unresolved;
            // Project only: still select one page. Selecting the project in the page
            // navigator moves SelectionSet inside a script, but NOT the focus that
            // actions (selectionset, project close) read - that follows the navigator
            // with the newest object selection. Measured on EPLAN 2027.
            if (want.Length == 0)
                foreach (object pg in allPages) { hits.Add(pg); break; }

            Array arr = Array.CreateInstance(FindType("Eplan.EplApi.DataModel.StorableObject"), hits.Count);
            for (int i = 0; i < hits.Count; i++) arr.SetValue(hits[i], i);
            System.Action sync = () =>
            {
                try
                {
                    Call(RequireMethod(editType, "SynchronizeObjectsToNavigators",
                        new string[] { "StorableObject[]" }, false), edit, new object[] { arr });
                }
                catch (Exception ex) { results["sync_err"] = Flatten(ex); }
            };
            Func<List<string>> selected = () =>
            {
                List<string> s = new List<string>();
                object sel = Activator.CreateInstance(selType);
                IEnumerable sp = Call(RequireMethod(selType, "GetSelectedPages", new string[] { }, false),
                    sel, new object[] { }) as IEnumerable;
                if (sp != null) foreach (object p in sp) s.Add(PropText(p, "Name"));
                return s;
            };
            Func<string> focused = () =>
            {
                object sel = Activator.CreateInstance(selType);
                object cur = Call(RequireMethod(selType, "GetCurrentProject", new string[] { "Boolean" }, false),
                    sel, new object[] { false });
                return cur == null ? null : PropText(cur, "ProjectFullName");
            };
            Func<bool> verify = () =>
            {
                if (!string.Equals(focused(), targetName, StringComparison.OrdinalIgnoreCase)) return false;
                List<string> s = selected();
                foreach (object h in hits)
                {
                    bool found = false;
                    foreach (string n in s) if (string.Equals(n, PropText(h, "Name"), StringComparison.OrdinalIgnoreCase)) found = true;
                    if (!found) return false;
                }
                return true;
            };

            if (hits.Count > 0) sync();
            bool ok = verify();
            results["opened_page"] = null;
            if (!ok && allowOpen && hits.Count > 0)
            {
                try
                {
                    Call(RequireMethod(editType, "OpenPageWithName", new string[] { "String", "String" }, false),
                        edit, new object[] { PropText(target, "ProjectLinkFilePath"), PropText(hits[0], "Name") });
                    results["opened_page"] = PropText(hits[0], "Name");
                }
                catch (Exception ex) { results["open_err"] = Flatten(ex); }
                sync();
                ok = verify();
            }

            results["focused_project"] = focused();
            results["selected_pages"] = selected();
            results["verified"] = ok && unresolved.Count == 0;
            results["success"] = true;
'''
    return _run_as_action(_script("NavigatorSelect_" + uuid.uuid4().hex[:6], body), project)


def _run_as_action(script: str, project: str) -> dict:
    """Run a [Start] script as a one-off REGISTERED action, called directly.

    Measured on EPLAN 2027: the same navigator calls made from an
    ExecuteScript script move SelectionSet inside the script but NOT the focus
    that actions read (selectionset /TYPE:PROJECT, project close). Run from an
    action context they do. So the script is registered under a unique
    [DeclareAction] name, executed through the Remote Client, and unregistered
    again; then the action-level focus is read back to confirm.
    """
    import json
    import os
    import uuid
    from cs_json import prepare_script
    from . import scripted
    from .addons import execute_raw_action
    from .project import get_current_project
    from .scripts import register_script, unregister_script

    manager, error = _get_connected_manager()
    if error:
        return error
    scripted._ensure_dirs()
    exec_id = uuid.uuid4().hex[:8]
    action = "McpNavigatorSelect_" + exec_id
    path = os.path.join(scripted.SCRIPT_DIR, action + ".cs")
    result_path = os.path.join(scripted.RESULTS_DIR, "result_" + exec_id + ".json")
    src = script.replace("{{RESULT_PATH}}", result_path.replace("\\", "\\\\"))
    src = src.replace("[Start]", '[DeclareAction("' + action + '")]', 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(prepare_script(src, getattr(manager, "target_version", None)))

    try:
        reg = register_script(path)
        if not reg.get("success"):
            return {"success": False, "error": "Could not register the selection action.",
                    "register": reg}
        try:
            run = execute_raw_action(action, direct=True)
        finally:
            unregister_script(path)
        if not os.path.exists(result_path):
            return {"success": False, "error": "The selection action wrote no result "
                    "(it did not run, or failed to compile - see eplan_get_system_messages).",
                    "action_result": run}
        with open(result_path, encoding="utf-8-sig") as f:
            results = json.load(f)
    finally:
        # One-off files: never leave them behind, whatever happened above.
        for leftover in (path, result_path):
            try:
                os.remove(leftover)
            except OSError:
                pass

    # The check that matters: what EPLAN's actions now see as the current project.
    focus = (get_current_project().get("parameters") or {}).get("PROJECT") or ""
    results["action_focus"] = focus
    target = (results.get("project") or "").lower()
    results["verified"] = bool(results.get("verified")) and bool(target) and \
        focus.lower().replace(".elk", "") == target.replace(".elk", "")
    return {"success": bool(results.get("success")), "results": results}
