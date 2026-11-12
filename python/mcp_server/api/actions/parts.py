"""
Parts management actions.
"""

from ._base import _get_connected_manager, _build_action


def export_parts_list(
    export_file: str,
    project_name: str = None,
    format: str = None
) -> dict:
    """
    Export the project's raw parts data, for re-import or external processing.
    Action: partslist

    Not the tool for a formatted deliverable. If the user wants a parts list
    they will print, hand to a shop, or build from a template - a label
    sheet, a titled and sorted list, an .xls someone reads - use
    create_labels instead, which is template-driven and takes
    config/filter/sort schemes. This tool emits the underlying data.

    Args:
        export_file: Output file path.
        project_name: Project path. Ask the user rather than reusing a path
            seen earlier in the conversation.
        format: Output format. NOTE: EPLAN's own partslist action ignores
            CONFIGSCHEME on TYPE:EXPORT, so there is no scheme parameter
            here on purpose - if the user needs scheme-driven output, that is
            another signal they want create_labels.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "partslist",
        TYPE="EXPORT",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file,
        FORMAT=format
    )
    return manager.execute_action(action)


def import_parts_list(
    import_file: str,
    project_name: str = None,
    format: str = None
) -> dict:
    """
    Import parts list into project.
    Action: partslist
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "partslist",
        TYPE="IMPORT",
        PROJECTNAME=project_name,
        IMPORTFILE=import_file,
        FORMAT=format
    )
    return manager.execute_action(action)


def select_part() -> dict:
    """
    Start the part selection dialog.
    Action: XPamSelectPart
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    return manager.execute_action("XPamSelectPart")


def set_parts_data_source(data_source: str) -> dict:
    """
    Change the parts management database type.
    Action: XPartsSetDataSourceAction
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XPartsSetDataSourceAction",
        DATASOURCE=data_source
    )
    return manager.execute_action(action)
