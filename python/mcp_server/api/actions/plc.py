"""
PLC import/export actions (plcservice).
"""

from ._base import _get_connected_manager, _build_action


def plc_export(
    destination_file: str,
    converter_id: str,
    project_name: str = None,
    configuration_project: str = None,
    language: str = None,
    overwrite: bool = False,
    format: str = None
) -> dict:
    """
    Export PLC bus data using the specified converter.
    Action: plcservice (TYPE=BUSDATAEXPORT)

    Args:
        destination_file: Destination file for the export (parameter DESTINATIONFILE).
        converter_id: PLC data converter ID (parameter CONVERTERID), e.g.
                      "PlcDcXMLExchangerSiemens", "PlcDcAMLExchangerGeneral",
                      "PlcDcXMLExchangerSchneider", etc.
        project_name: Project path (optional).
        configuration_project: Name of the PLC configuration data set to export.
        language: Language identifier (e.g. "en_US", "de_DE").
        overwrite: Overwrite the output file if it already exists.
        format: Export format (only for converters with multiple formats),
                e.g. "AutomationML AR APC V1.4.0".
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "plcservice",
        TYPE="BUSDATAEXPORT",
        PROJECTNAME=project_name,
        CONFIGURATIONPROJECT=configuration_project,
        DESTINATIONFILE=destination_file,
        CONVERTERID=converter_id,
        LANGUAGE=language,
        OVERWRITE=overwrite,
        FORMAT=format
    )
    return manager.execute_action(action)


def plc_import(
    source_file: str,
    converter_id: str,
    project_name: str = None,
    language: str = None,
    import_match: int = None
) -> dict:
    """
    Import PLC bus data using the specified converter.
    Action: plcservice (TYPE=BUSDATAIMPORT)

    Args:
        source_file: Source file for the import (parameter SOURCEFILE).
        converter_id: PLC data converter ID (parameter CONVERTERID).
        project_name: Project path (optional).
        language: Language identifier (e.g. "en_US", "de_DE").
        import_match: Matching options for PLC data import (parameter IMPORTMATCH):
                      0 = Match by internal object ids,
                      1 = Match by identifying names (may show a compare dialog),
                      2 = Don't match (create new functions for all imported objects).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "plcservice",
        TYPE="BUSDATAIMPORT",
        PROJECTNAME=project_name,
        SOURCEFILE=source_file,
        CONVERTERID=converter_id,
        LANGUAGE=language,
        IMPORTMATCH=import_match
    )
    return manager.execute_action(action)
