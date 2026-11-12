"""
Property actions (project, page, user properties, and generic properties).
Complete implementation with all documented parameters.
"""

from typing import Optional
from ._base import _get_connected_manager, _build_action


def get_project_property(property_id: str, property_index: int = 0) -> dict:
    """
    Get a special property of the current project.
    Action: XEsGetProjectPropertyAction

    Note: This action operates on the CURRENT project (no PROJECTNAME parameter).
    The value is returned in the calling-context parameter "PropertyValue".

    Args:
        property_id: Property identifier name or number (parameter PropertyId).
                     Values defined in Eplan.EplApi.DataModel.Properties.
        property_index: Property index (default 0, parameter PropertyIndex).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEsGetProjectPropertyAction",
        PropertyId=property_id,
        PropertyIndex=property_index
    )
    return manager.execute_action(action)


def set_project_property(property_id: str, value: str, property_index: int = 0) -> dict:
    """
    Set a special property of the current project.
    Action: XEsSetProjectPropertyAction

    Note: This action operates on the CURRENT project (no PROJECTNAME parameter).

    Args:
        property_id: Property identifier name or number (parameter PropertyId).
        value: Value to set (parameter PropertyValue).
        property_index: Property index (default 0, parameter PropertyIndex).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEsSetProjectPropertyAction",
        PropertyId=property_id,
        PropertyIndex=property_index,
        PropertyValue=value
    )
    return manager.execute_action(action)


def get_page_property(property_id: str, property_index: int = 0) -> dict:
    """
    Get a special property of the first selected page.
    Action: XEsGetPagePropertyAction

    Note: This action operates on the first SELECTED page (no PAGENAME parameter).
    The value is returned in the calling-context parameter "PropertyValue".

    Args:
        property_id: Property identifier name or number (parameter PropertyId).
        property_index: Property index (default 0, parameter PropertyIndex).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEsGetPagePropertyAction",
        PropertyId=property_id,
        PropertyIndex=property_index
    )
    return manager.execute_action(action)


def set_page_property(property_id: str, value: str, property_index: int = 0) -> dict:
    """
    Set a special property of the selected pages.
    Action: XEsSetPagePropertyAction

    Note: This action operates on the SELECTED pages (no PAGENAME parameter).

    Args:
        property_id: Property identifier name or number (parameter PropertyId).
        value: Value to set (parameter PropertyValue).
        property_index: Property index (default 0, parameter PropertyIndex).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEsSetPagePropertyAction",
        PropertyId=property_id,
        PropertyIndex=property_index,
        PropertyValue=value
    )
    return manager.execute_action(action)


def get_property(
    property_id: str = None,
    property_ident_name: str = None,
    property_index: int = 0
) -> dict:
    """
    Get a property from selected objects.
    Action: XEsGetPropertyAction

    Args:
        property_id: Property identifier number (from Eplan.EplApi.DataModel.Properties)
        property_ident_name: Property identifier name (for user-defined properties)
        property_index: Property index (default 0)

    Note:
        Either property_id or property_ident_name must be provided.
        Returns the property value in the result.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    if property_id:
        action = _build_action(
            "XEsGetPropertyAction",
            PropertyId=property_id,
            PropertyIndex=property_index
        )
    elif property_ident_name:
        action = _build_action(
            "XEsGetPropertyAction",
            PropertyIdentName=property_ident_name,
            PropertyIndex=property_index
        )
    else:
        return {"success": False, "message": "Either property_id or property_ident_name must be provided"}

    return manager.execute_action(action)


def set_property(
    value: str,
    property_id: str = None,
    property_ident_name: str = None,
    property_index: int = 0
) -> dict:
    """
    Set a property on selected objects.
    Action: XEsSetPropertyAction

    Args:
        value: Value to set
        property_id: Property identifier number
        property_ident_name: Property identifier name (for user-defined properties)
        property_index: Property index (default 0)

    Note:
        Either property_id or property_ident_name must be provided.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    if property_id:
        action = _build_action(
            "XEsSetPropertyAction",
            PropertyId=property_id,
            PropertyIndex=property_index,
            PropertyValue=value
        )
    elif property_ident_name:
        action = _build_action(
            "XEsSetPropertyAction",
            PropertyIdentName=property_ident_name,
            PropertyIndex=property_index,
            PropertyValue=value
        )
    else:
        return {"success": False, "message": "Either property_id or property_ident_name must be provided"}

    return manager.execute_action(action)


def export_user_properties(export_file: str, project_name: str = None) -> dict:
    """
    Export user properties to file.
    Action: XEsUserPropertiesExportAction

    Live-verified 2026-09-04: the previous wrapper sent PROJECTNAME/EXPORTFILE,
    neither a real parameter of this action - it documents XMLFile and
    Project. Audit #42 item 2.

    Args:
        export_file: Output XML file path.
        project_name: Full project name/path (optional). If omitted, the
            selected project is used or EPLAN shows a project picker.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEsUserPropertiesExportAction",
        Project=project_name,
        XMLFile=export_file
    )
    return manager.execute_action(action)


def import_user_properties(import_file: str, project_name: str = None,
                           overwrite: bool = None) -> dict:
    """
    Import user properties from file.
    Action: XEsUserPropertiesImportAction

    Live-verified 2026-09-04: the previous wrapper sent PROJECTNAME/IMPORTFILE,
    neither a real parameter of this action - it documents XMLFile and
    Project. Audit #42 item 2.

    Args:
        import_file: Input XML file path. If omitted, EPLAN shows a file
            picker.
        project_name: Full project name/path (optional). If omitted, the
            selected project is used or EPLAN shows a project picker.
        overwrite: Overwrite existing properties (optional). If omitted,
            EPLAN shows a confirmation dialog - pass this explicitly for an
            unattended call.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEsUserPropertiesImportAction",
        Project=project_name,
        XMLFile=import_file,
        Overwrite=overwrite
    )
    return manager.execute_action(action)
