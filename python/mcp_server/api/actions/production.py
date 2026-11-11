"""
NC data and production wiring actions.
"""

from ._base import _get_connected_manager, _build_action


def export_nc_data(
    export_file: str,
    project_name: str = None
) -> dict:
    """
    Export NC data for machines.
    Action: ExportNCData
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "ExportNCData",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file
    )
    return manager.execute_action(action)


def export_production_wiring(
    export_file: str,
    project_name: str = None
) -> dict:
    """
    Export production wiring data for machines.
    Action: ExportProductionWiring
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "ExportProductionWiring",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file
    )
    return manager.execute_action(action)
