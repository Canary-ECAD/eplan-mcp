"""
3D / Cabinet actions.
"""

from ._base import _get_connected_manager, _build_action


def calculate_cabinet_weight(project_name: str = None) -> dict:
    """
    Calculate total weight of cabinet.
    Action: XCabCalculateEnclosureTotalWeightAction
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XCabCalculateEnclosureTotalWeightAction",
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)


def update_segments_filling(project_name: str = None) -> dict:
    """
    Calculate and set segment filling values.
    Action: UpdateSegmentsFilling
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "UpdateSegmentsFilling",
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)


def topology_operation(
    operation_type: str,
    project_name: str = None
) -> dict:
    """
    Perform topology-related operations.
    Action: Topology
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "Topology",
        TYPE=operation_type,
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)


def import_preplanning_data(
    import_file: str,
    scheme_name: str,
    project_name: str = None,
    table_name: str = None,
    delimiter: str = None,
    header: bool = None,
    target_name: str = None,
    skip_errors: bool = None,
    overwrite: bool = None,
    update_only: bool = None
) -> dict:
    """
    Import pre-planning data.
    Action: ImportPrePlanningData

    The previous wrapper sent IMPORTFILE (the action documents FILENAME) and
    never sent SCHEMENAME at all, though the action documents both as
    mandatory. Audit #42 item 6.

    Args:
        import_file: Full path of the source file. Mandatory.
        scheme_name: Name of the scheme mapping external data fields to
            EPLAN properties. Mandatory - EPLAN's own docs mark this
            required, same as import_file.
        project_name: Project path (optional).
        table_name: Table/data-area name within the source, for Excel
            imports (optional).
        delimiter: Column separator, for text-file imports (optional).
        header: Column names appear in the "External field" column of the
            assignment table (Excel imports only). Optional, EPLAN default
            False.
        target_name: DMPLAOBJECT_FULLDESIGNATION of the object to insert the
            imported data under (optional). If omitted, data is inserted
            under the project.
        skip_errors: Do not abort on errors/messages during import
            (optional). EPLAN's own default is True.
        overwrite: Overwrite existing planning objects that share a name
            with an imported one (optional). EPLAN's own default is True.
        update_only: Only update existing structure segments/planning
            objects, insert nothing new (optional). EPLAN's own default is
            False.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "ImportPrePlanningData",
        PROJECTNAME=project_name,
        FILENAME=import_file,
        SCHEMENAME=scheme_name,
        TABLENAME=table_name,
        DELIMITER=delimiter,
        HEADER=header,
        TARGETNAME=target_name,
        SKIPERRORS=skip_errors,
        OVERWRITE=overwrite,
        UPDATEONLY=update_only
    )
    return manager.execute_action(action)


def export_segments_template(
    export_file: str,
    project_name: str = None,
    description: str = None
) -> dict:
    """
    Export segment templates to file.
    Action: ExportSegmentsTemplate

    The previous wrapper sent EXPORTFILE; the action documents FILENAME.
    Audit #42 item 6.

    Args:
        export_file: Full path of the target file. Mandatory.
        project_name: Project path (optional).
        description: Description stored in the exported file, in
            multi-language string format (optional).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "ExportSegmentsTemplate",
        PROJECTNAME=project_name,
        FILENAME=export_file,
        DESCRIPTION=description
    )
    return manager.execute_action(action)


def import_segments_template(
    import_file: str,
    project_name: str = None
) -> dict:
    """
    Import segment templates from file.
    Action: ImportSegmentsTemplate

    The previous wrapper sent IMPORTFILE; the action documents FILENAME.
    Audit #42 item 6.

    Args:
        import_file: Full path of the source file. Mandatory.
        project_name: Project path (optional).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "ImportSegmentsTemplate",
        PROJECTNAME=project_name,
        FILENAME=import_file
    )
    return manager.execute_action(action)


def create_graving_text(complete: bool = None) -> dict:
    """
    Generate the engraving text of a cable from the DTs of its source and target.
    Action: XCCreateGravingtextAction

    By default the designation is abbreviated according to the VASS standard
    (Volkswagen Audi Seat Skoda): structure identifiers that have the same name
    on source and target are removed, starting from the left.

    This action takes no PROJECTNAME - it works on the current GUI selection
    (the selected cable) in the open project. Select the cable first; calling it
    headless with nothing selected does nothing.

    Args:
        complete: Retain mounting locations of the same name.
                  False/None (0, the default) truncates per the VASS standard;
                  True (1) keeps the identical structure identifiers.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XCCreateGravingtextAction",
        Complete=complete
    )
    return manager.execute_action(action)
