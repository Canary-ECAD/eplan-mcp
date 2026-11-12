"""
Parts Management API actions.
Complete implementation for exporting and importing parts, addresses,
constructions, terminals, accessory lists and accessory placements.
"""

from typing import List, Dict, Optional
from ._base import _get_connected_manager, _build_action, _quote_param


def partsmanagement_export(
    export_file: str,
    format: str = "XPamExportXml",
    part_numbers: List[str] = None,
    manufacturers: List[str] = None,
    constructions: List[str] = None,
    connection_patterns: List[str] = None,
    accessory_lists: List[str] = None,
    accessory_placements: List[str] = None,
    filter_scheme: str = None
) -> dict:
    """
    Export parts and other parts management items.
    Action: partsmanagementapi

    Args:
        export_file: Output file path (extension added automatically)
        format: Export format - "XPamExportXml" (default), "IXPartsImportExportEdz"
        part_numbers: List of part numbers to export (use ["*"] for all)
        manufacturers: List of manufacturer long names
        constructions: List of construction names
        connection_patterns: List of terminal/connection pattern names
        accessory_lists: List of accessory list names
        accessory_placements: List of accessory placement names
        filter_scheme: Filter scheme name for filtering export

    Example:
        partsmanagement_export(
            export_file="C:/temp/parts.xml",
            part_numbers=["A-B.100-C09EJ01", "A-B.140M-C-AFA11"],
            manufacturers=["LAPP", "Rittal"]
        )
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["partsmanagementapi", "/TYPE:EXPORT", _quote_param("EXPORTFILE", export_file)]

    if format:
        parts.append(f"/FORMAT:{format}")
    if filter_scheme:
        parts.append(_quote_param("FILTERSCHEME", filter_scheme))

    # Add part numbers
    if part_numbers:
        for i, pn in enumerate(part_numbers, 1):
            parts.append(f"/PARTNUMBER{i}:{pn}")

    # Add manufacturers
    if manufacturers:
        for i, m in enumerate(manufacturers, 1):
            parts.append(_quote_param(f"MANUFACTURER{i}", m))

    # Add constructions
    if constructions:
        for i, c in enumerate(constructions, 1):
            parts.append(_quote_param(f"CONSTRUCTION{i}", c))

    # Add connection patterns
    if connection_patterns:
        for i, cp in enumerate(connection_patterns, 1):
            parts.append(_quote_param(f"CONNECTIONPOINTPATTERN{i}", cp))

    # Add accessory lists
    if accessory_lists:
        for i, al in enumerate(accessory_lists, 1):
            parts.append(_quote_param(f"ACCESSORYLIST{i}", al))

    # Add accessory placements
    if accessory_placements:
        for i, ap in enumerate(accessory_placements, 1):
            parts.append(_quote_param(f"ACCESSORYPLACEMENT{i}", ap))

    return manager.execute_action(" ".join(parts))


def partsmanagement_import(
    import_file: str,
    format: str = "XPamImportXml",
    mode: int = 0,
    additional_language: bool = False,
    filter_scheme: str = None
) -> dict:
    """
    Import parts and other parts management items.
    Action: partsmanagementapi

    Args:
        import_file: Path to import file
        format: Import format - "XPamImportXml" (default), "IXPartsImportExportEdz"
        mode: Import mode:
              0 = Append new records only (default)
              1 = Update existing records only
              2 = Update existing records and append new ones
              3 = Replace existing records and append new ones
        additional_language: If True, multi-language properties are updated
                           with another language rather than replaced
        filter_scheme: Filter scheme for filtering import

    Example:
        partsmanagement_import(
            import_file="C:/temp/parts.xml",
            mode=2  # Update and append
        )
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["partsmanagementapi", "/TYPE:IMPORT", _quote_param("IMPORTFILE", import_file)]

    if format:
        parts.append(f"/FORMAT:{format}")
    parts.append(f"/MODE:{mode}")
    if additional_language:
        parts.append("/ADDITIONAL_LANGUAGE:1")
    if filter_scheme:
        parts.append(_quote_param("FILTERSCHEME", filter_scheme))

    return manager.execute_action(" ".join(parts))


def partsmanagement_export_by_properties(
    export_type: str,
    export_file: str,
    properties: Dict[int, str],
    format: str = "XPamExportXml"
) -> dict:
    """
    Export parts management items by property values.
    Action: partsmanagementapi

    Args:
        export_type: Type of export:
                    - "EXPORTPARTS" - Export parts
                    - "EXPORTMANUFACTURERS" - Export manufacturers
                    - "EXPORTCONSTRUCTIONS" - Export constructions
                    - "EXPORTCONNECTIONPATTERNS" - Export connection patterns
                    - "EXPORTACCESSORYLISTS" - Export accessory lists
                    - "EXPORTACCESSORYPLACEMENTS" - Export accessory placements
        export_file: Output file path
        properties: Dict of property_id -> value pairs
                   e.g., {22024: "2", 22007: "ABB"}
        format: Export format - "XPamExportXml" or "IXPartsImportExportEdz"

    Example:
        # Export every part with variant '2' or manufacturer 'ABB'
        partsmanagement_export_by_properties(
            export_type="EXPORTPARTS",
            export_file="C:/temp/parts.xml",
            properties={22024: "2", 22007: "ABB"}
        )

        # Export constructions with specific names
        partsmanagement_export_by_properties(
            export_type="EXPORTCONSTRUCTIONS",
            export_file="C:/temp/constructions.xml",
            properties={22931: "FES.130642"}
        )
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["partsmanagementapi", f"/TYPE:{export_type}", _quote_param("EXPORTFILE", export_file)]

    if format:
        parts.append(f"/FORMAT:{format}")

    # Add property pairs
    for i, (prop_id, value) in enumerate(properties.items(), 1):
        parts.append(f"/PROPERTYID{i}:{prop_id}")
        parts.append(f"/PROPERTYVALUE{i}:{value}")

    return manager.execute_action(" ".join(parts))


def partsmanagement_export_all(
    export_file: str,
    format: str = "XPamExportXml"
) -> dict:
    """
    Export all parts.
    Action: partsmanagementapi

    Args:
        export_file: Output file path
        format: Export format

    Example:
        partsmanagement_export_all("C:/temp/all_parts.edz", format="IXPartsImportExportEdz")
    """
    return partsmanagement_export(
        export_file=export_file,
        format=format,
        part_numbers=["*"]
    )
