"""
New projects from a template, through the object model.

`projectmanagement` (the action) copies and reads projects but never creates
one; the GUI's "Proyecto > Nuevo" is
`Eplan.EplApi.DataModel.ProjectManager.CreateProject(linkFilePath,
templateFilePath)`, which takes a basic project (.zw9), a project template
(.ept) or a .epb and leaves the new project open. Learned on 2026.0.3.

The new project's path is guarded on the Python side (it does not exist yet,
so the C# scratch guard cannot read it): it must sit under the scratch root
unless allow_real_project is passed - a real project directory is the
designer's decision.
"""

import glob
import os
import uuid

from ._base import cs_escape
from .fixtures import SCRATCH_ROOT
from .scripted import _execute_script, pathmap_substitute
from . import live, schematic, target
from .schematic import _err
from .schematic_model import cs_text, SchematicValueError


_TEMPLATE_EXT = (".zw9", ".ept", ".epb")


def _under_scratch(path: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(SCRATCH_ROOT)]) \
            == os.path.abspath(SCRATCH_ROOT)
    except ValueError:
        return False


def live_project_templates(directory: str = None) -> dict:
    """
    The project templates and basic projects a new project can start from.
    Read-only.

    Lists .zw9 (basic project: pages, forms, settings - the house style's
    starting point), .ept (template: settings only) and .epb files under the
    templates master-data folder, $(MD_TEMPLATES), or under `directory`.

    Args:
        directory: Folder to scan instead of $(MD_TEMPLATES). Scanned
            recursively.

    Returns:
        {"success", "directory", "templates": [{"path", "name", "kind"
        ("basic project" | "template"), "sizeKB", "modified"}]}.
    """
    d = directory
    if not d:
        try:
            r = pathmap_substitute("$(MD_TEMPLATES)")
            d = (r.get("results") or r).get("substituted") or (r.get("results") or r).get("path")
        except Exception:
            d = None
        if not d or "$(" in str(d):
            d = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "EPLAN", "Data", "Plantillas")
    if not os.path.isdir(d):
        return {"success": False, "error": "Templates folder not found: %s" % d}
    out = []
    for path in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        ext = os.path.splitext(path)[1].lower()
        if ext not in _TEMPLATE_EXT or not os.path.isfile(path):
            continue
        st = os.stat(path)
        out.append({"path": path, "name": os.path.basename(path),
                    "kind": "basic project" if ext == ".zw9" else "template",
                    "sizeKB": round(st.st_size / 1024),
                    "modified": __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(st.st_mtime))})
    return {"success": True, "directory": d, "templates": out, "count": len(out)}


def live_create_project(project_path: str, template_path: str,
                        set_target: bool = True, allow_real_project: bool = False,
                        timeout_seconds: float = 600.0) -> dict:
    """
    Create a new project from a basic project or template and open it.
    WRITES a new project directory.

    Same as "Proyecto > Nuevo" with the template chosen: the .elk and .edb
    are created next to each other at `project_path`, the template's pages,
    forms, symbol libraries and settings are copied in, and the project is
    left open in EPLAN. With set_target (default) the live tools point at it
    afterwards, so the next call works on the new project.

    Args:
        project_path: Full path of the new .elk (e.g. "D:/EPLAN/Test/P1.elk").
            Must be under the scratch root unless allow_real_project; the
            directory is created if missing. Refused when the .elk exists.
        template_path: A .zw9 basic project (preferred: it carries the forms
            and pages), .ept template or .epb. See live_project_templates.
        set_target: Point the live tools at the new project (default True).
        allow_real_project: Must be True to create outside the scratch root.
        timeout_seconds: Default 600 - unpacking a basic project is slow.

    Returns:
        {"success", "project" (name), "path", "pages" (count), "template"}.
    """
    try:
        project_path = cs_text(project_path, "project_path")
        template_path = cs_text(template_path, "template_path")
    except SchematicValueError as exc:
        return _err(exc)
    project_path = os.path.abspath(project_path)
    if not project_path.lower().endswith(".elk"):
        project_path += ".elk"
    if os.path.exists(project_path):
        return {"success": False, "error": "Project already exists: %s" % project_path}
    if not os.path.isfile(template_path):
        return {"success": False, "error": "Template not found: %s" % template_path}
    if os.path.splitext(template_path)[1].lower() not in _TEMPLATE_EXT:
        return {"success": False, "error": "template_path must be a .zw9, .ept or .epb file."}
    if not allow_real_project and not _under_scratch(project_path):
        return {"success": False,
                "error": "project_path %s is outside the scratch root %s. Pass "
                         "allow_real_project=True to create a real project there."
                         % (project_path, SCRATCH_ROOT)}
    os.makedirs(os.path.dirname(project_path), exist_ok=True)

    body = '''
            Type pmT = FindType("Eplan.EplApi.DataModel.ProjectManager");
            object pm = Activator.CreateInstance(pmT);
            object np = null;
            try
            {
                MethodInfo create = RequireMethod(pmT, "CreateProject", new string[] { "String", "String" }, false);
                np = Call(create, pm, new object[] { "''' + cs_escape(project_path) + '''", "''' + cs_escape(template_path) + '''" });
            }
            finally { try { pmT.GetMethod("Dispose").Invoke(pm, null); } catch { } }
            if (np == null) throw new Exception("CreateProject returned null.");
            results["project"] = PropText(np, "ProjectName");
            results["path"] = PropText(np, "ProjectLinkFilePath") ?? PropText(np, "ProjectFullName");
            int pages = 0;
            try { foreach (object pg in (IEnumerable)TryRead(np, "Pages", null)) pages++; } catch { }
            results["pages"] = pages;
            results["template"] = "''' + cs_escape(template_path) + '''";
            results["success"] = true;
'''
    # The script scaffold resolves the target project first and refuses to
    # run when that project is not open; creating a project needs no
    # project at all, so the target is cleared for the call and restored
    # (or moved to the new project) afterwards.
    previous = target.get()
    target.set_target("")
    try:
        r = _execute_script(
            live._script("LiveCreateProject_" + uuid.uuid4().hex[:6], body,
                         extra_helpers=schematic._HELPERS_SCHEMATIC),
            timeout=timeout_seconds,
        )
    finally:
        target.set_target(previous)
    res = r.get("results") if isinstance(r.get("results"), dict) else r
    if isinstance(res, dict) and res.get("success") and set_target:
        target.set_target(project_path)
        r["target"] = project_path
    return r
