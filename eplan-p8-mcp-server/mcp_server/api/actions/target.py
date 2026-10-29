"""
Target project - which open project the server works on.

EPLAN's "current project" is whichever one the user last clicked in the GUI.
That is a bad address for an unattended writer: the user keeps working in
EPLAN while the model builds, so between two tool calls the current project
can become a production project, and a live write then lands there. It did,
during a real session - the scratch guard caught it, but only because the
test project happened to live under the scratch root.

So the server carries its own notion of the target project, set once with
live_set_target_project (or the EPLAN_MCP_PROJECT environment variable):

- every reflection script (live.py, schematic.py, ops.py) resolves the project
  by its .elk path from ProjectManager.OpenProjects instead of asking
  SelectionSet for the current one, and fails if that project is not open;
- every action wrapper that takes PROJECTNAME and was called without one
  sends the target instead of leaving EPLAN to pick the current project.

Unset, nothing changes: scripts use the current project, as they always did.
"""

import os

_target = os.environ.get("EPLAN_MCP_PROJECT") or ""


def get() -> str:
    """The target project path, or "" when the current project is to be used."""
    return _target


def set_target(path) -> str:
    global _target
    _target = (path or "").strip()
    return _target


def live_set_target_project(project_path: str = None) -> dict:
    """
    Pin every later tool call to ONE open project, by its .elk path.

    Without a target, live tools act on whatever project is current in the
    EPLAN GUI, which changes as soon as the user clicks another project. With
    a target, reflection scripts pick that project from EPLAN's open projects
    by path (and refuse to run if it is not open), and action wrappers fill an
    omitted PROJECTNAME with it. Set it right after opening the project you
    intend to work on; the user can then keep working in EPLAN.

    Args:
        project_path: Full path of the .elk file, as eplan_open_project or
            eplan_get_current_project report it. Pass "" (or omit) to clear
            the target and go back to the current project.

    Returns:
        {"success", "target": "<path or empty>", "previous": "<path or empty>"}
    """
    previous = get()
    wanted = (project_path or "").strip()
    if wanted and not wanted.lower().endswith(".elk"):
        return {"success": False, "error": "project_path must be the project's .elk file: %r" % wanted,
                "target": previous}
    return {"success": True, "target": set_target(wanted), "previous": previous}
