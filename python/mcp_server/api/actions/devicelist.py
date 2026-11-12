"""
Device list actions.
"""

from ._base import _get_connected_manager, _build_action


def export_device_list(
    export_file: str,
    project_name: str = None,
    format: str = "XDLXmlExporter"
) -> dict:
    """
    Export device list from project.
    Action: devicelist

    Args:
        export_file: Output file path
        project_name: Project path (optional)
        format: Export format - "XDLXmlExporter", "XDLTxtImporterExporter", "XDLCsvImporterExporter"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "devicelist",
        TYPE="EXPORT",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file,
        FORMAT=format
    )
    return manager.execute_action(action)


def import_device_list(
    import_file: str,
    project_name: str = None,
    format: str = "XDLXmlExporter"
) -> dict:
    """
    Import device list into project.
    Action: devicelist
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "devicelist",
        TYPE="IMPORT",
        PROJECTNAME=project_name,
        IMPORTFILE=import_file,
        FORMAT=format
    )
    return manager.execute_action(action)


def delete_device_list(project_name: str = None) -> dict:
    """
    Delete device list from project.
    Action: devicelist
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "devicelist",
        TYPE="DELETE",
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)
