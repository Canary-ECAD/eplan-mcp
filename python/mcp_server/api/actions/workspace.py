"""
Workspace actions.

Note: these actions need a mainframe (GUI). Under a headless/remote QuietMode
session they may not behave as in interactive mode.
"""

from ._base import _get_connected_manager, _build_action


def open_workspace(workspace_name: str, silent: bool = False) -> dict:
    """
    Open an existing workspace.
    Action: OpenWorkspaceAction

    A "workspace" here is the GUI layout (which panels/windows are docked
    where) — the visual "frontend" arrangement, not project data. Opening
    one does not modify the project.

    The LLM must always ask the user for the exact workspace name rather
    than guessing or defaulting to a name seen before (e.g. "Estándar") —
    workspace names are user/installation-specific.

    Args:
        workspace_name: Name of the workspace to open (parameter Workspacename).
                        Use "?" to list all available workspaces.
        silent: Run in silent mode, suppressing dialogs (parameter Silent).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "OpenWorkspaceAction",
        Workspacename=workspace_name,
        Silent=silent
    )
    return manager.execute_action(action)


def save_workspace(workspace_name: str, silent: bool = False) -> dict:
    """
    Save the specified workspace. Created if it does not yet exist.
    Action: SaveWorkspaceAction

    A "workspace" here is the GUI layout/canvas (which panels/windows are
    docked where) — the visual "frontend"/"lienzo" of the program, not
    project data. Saving does not modify the project.

    DESTRUCTIVE if the name already exists: this overwrites that workspace's
    saved layout with the current one, with no warning. The LLM must always
    ask the user for the exact workspace name to save under — never guess,
    reuse a name seen earlier in the conversation, or default to something
    like "Estándar" without confirming the user actually wants to overwrite it.

    Args:
        workspace_name: Name of the workspace to save (parameter Workspacename).
        silent: Run in silent mode, suppressing dialogs (parameter Silent).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "SaveWorkspaceAction",
        Workspacename=workspace_name,
        Silent=silent
    )
    return manager.execute_action(action)


def clean_workspace(workspace_name: str = None, silent: bool = False) -> dict:
    """
    Clean an existing workspace.
    Action: CleanWorkspaceAction

    DESTRUCTIVE: this deletes/removes the named workspace (the saved GUI
    layout/canvas), not just resets it. The LLM must always ask the user
    for the exact workspace name to clean — never assume or reuse a name
    seen earlier in the conversation, and never omit workspace_name/leave
    it blank: if empty, EPLAN cleans the LAST_USED workspace, which is an
    implicit state the LLM cannot query or confirm beforehand, so an
    omitted name risks deleting the wrong workspace.

    Args:
        workspace_name: Name of the workspace to clean (parameter Workspacename).
                        If empty, the LAST_USED workspace is cleaned — always
                        ask the user for an explicit name instead of omitting this.
        silent: Run in silent mode, suppressing dialogs (parameter Silent).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "CleanWorkspaceAction",
        Workspacename=workspace_name,
        Silent=silent
    )
    return manager.execute_action(action)
