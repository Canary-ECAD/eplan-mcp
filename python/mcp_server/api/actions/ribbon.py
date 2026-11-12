"""
Ribbon bar customization actions.
"""

from ._base import _get_connected_manager, _build_action


def export_ribbon_bar(export_file: str) -> dict:
    """
    Export main ribbon bar customization to XML.
    Action: MfExportRibbonBarAction

    Args:
        export_file: Path to the file to be created by the export (parameter FileName).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "MfExportRibbonBarAction",
        FileName=export_file
    )
    return manager.execute_action(action)


def import_ribbon_bar(import_file: str) -> dict:
    """
    Import main ribbon bar customization from XML.
    Action: MfImportRibbonBarAction

    Args:
        import_file: Path to the ribbon bar file to import (parameter FileName).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "MfImportRibbonBarAction",
        FileName=import_file
    )
    return manager.execute_action(action)
