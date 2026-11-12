"""
Macro actions.
"""

from ._base import _get_connected_manager, _build_action


def generate_macros(
    project_name: str = None,
    destination_path: str = None,
    scheme: str = None
) -> dict:
    """
    Generate macros from project.
    Action: generatemacros
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "generatemacros",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        SCHEME=scheme
    )
    return manager.execute_action(action)


def prepare_macros(project_name: str = None) -> dict:
    """
    Prepare project for macro generation.
    Action: preparemacros
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "preparemacros",
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)


def update_macros(project_path: str = None, scheme_name: str = None) -> dict:
    """
    Update macros in project.
    Action: XGedUpdateMacroAction

    Args:
        project_path: Full path of the project (parameter ProjectName).
                      If the project is not open, the action opens and closes
                      it automatically. If omitted, the selected object in GED
                      is used.
        scheme_name: Concrete scheme to use (optional, parameter SchemeName).
                     If not given, the last used scheme is used.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XGedUpdateMacroAction",
        ProjectName=project_path,
        SchemeName=scheme_name
    )
    return manager.execute_action(action)
