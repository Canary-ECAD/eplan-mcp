"""
Settings and configuration actions.
"""

from ._base import _get_connected_manager, _build_action


def export_settings(
    xml_file: str,
    node: str = None,
    project: str = None
) -> dict:
    """
    Export settings to an XML file.
    Action: XSettingsExport

    Args:
        xml_file: Full name of the target XML file (parameter XMLFile).
        node: Path of a setting node, e.g. "USER", "STATION", "COMPANY",
              "USER.DIALOGSETTINGS" (parameter node, without PROJECT).
        project: Project (must be open) for exporting project settings
                 (parameter prj).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XSettingsExport",
        XMLFile=xml_file,
        node=node,
        prj=project
    )
    return manager.execute_action(action)


def import_settings(
    xml_file: str,
    node: str = None,
    project: str = None
) -> dict:
    """
    Import project-, station-, company- or user settings from an XML file.
    Action: XSettingsImport

    Args:
        xml_file: Full name of the XML file (parameter XmlFile). If empty,
                  a file selection dialog appears.
        node: Node of settings to import (parameter Node), e.g.
              "User.XSbGui.CustomSymbols".
        project: Full name of the target project for project settings
                 (parameter Project).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XSettingsImport",
        XmlFile=xml_file,
        Node=node,
        Project=project
    )
    return manager.execute_action(action)


def set_setting(name: str, value: str, index: int = 0) -> dict:
    """
    Set the value of a setting.
    Action: XAfActionSetting

    Args:
        name: Name of the setting to set (parameter set),
              e.g. "USER.MacrosLog.Pxf.writeDebugInfo".
        value: New value of the setting (parameter value).
        index: Optional index of the setting (parameter index, default 0).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XAfActionSetting",
        set=name,
        value=value,
        index=index
    )
    return manager.execute_action(action)


def set_project_setting(name: str, value: str, project: str = None, index: int = 0) -> dict:
    """
    Set the value of a project setting.
    Action: XAfActionSettingProject

    Args:
        name: Name of the project setting to set (parameter set).
        value: New value of the setting (parameter value).
        project: Full name of the target project (parameter Project).
                 When empty, the currently selected project is used.
        index: Optional index of the setting (parameter index, default 0).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XAfActionSettingProject",
        Project=project,
        set=name,
        value=value,
        index=index
    )
    return manager.execute_action(action)


def lock_unlock_all_objects(raw_args: str = None) -> dict:
    """
    NOT VERIFIED on the reference machine - read the block below before use.
    DEPRECATED. The official 2027 action index lists this action as "This action
    is deprecated. Allows to set project settings." and its documentation page
    404s, so no parameter table exists for it.
    ======================================================================
    !!! NOT VERIFIED - the live behaviour of this wrapper could not be
    tested on the reference machine (EPLAN Electric P8 2027.0.1,
    2026-09-02/03). Read this before relying on it. !!!
    ======================================================================

    This one was tested, and IT DOES NOT WORK. Every call FAILED with:
        "Unable to gain access to the database"
    regardless of whether a project was open.

    The cause is deprecation, not licensing - do not read the failure as a
    missing module. EPLAN's own 2027 action index marks LockUnlockAllObjects
    as deprecated, and it has no documentation page.
    ActionManager.FindAction does resolve it (module
    Eplan.EplApi.CommandLineActionsNet), so the name still exists in the
    installation, but resolving only means the name is registered.

    It is shipped here for completeness only. Prefer the documented settings
    wrappers set_setting / set_project_setting.

    To verify: there is no known working invocation. If EPLAN ever documents
    this action, or a parameter set is found that avoids the database error,
    retest then.

    What IS covered: the command-string construction (bare call, and the raw
    parameter tail appended verbatim) is exercised offline by
    tests/test_new_actions_offline.py. Only the live EPLAN behaviour is
    unverified - and live, it fails.
    ======================================================================

    Action: LockUnlockAllObjects

    Because the parameters are undocumented, none are invented here: pass any
    parameters you have determined out of band through raw_args, which is
    appended to the command line verbatim. Prefer the documented settings
    wrappers (set_setting / set_project_setting) over this action.

    Args:
        raw_args: Raw parameter tail appended verbatim, e.g. '/KEY:value
                  /OTHER:"value with spaces"'. Quote values containing spaces
                  yourself. Omit for a bare "LockUnlockAllObjects" call.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action("LockUnlockAllObjects")
    if raw_args:
        action = action + " " + raw_args.strip()
    return manager.execute_action(action)
