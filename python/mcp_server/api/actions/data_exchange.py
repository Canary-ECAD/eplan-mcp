"""
Data exchange and synchronization actions.
Complete implementation including DC export/import and specialized exports.
"""

from typing import Optional
from ._base import _get_connected_manager, _build_action


def export_connections(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False,
    include_graphical_connections: bool = False
) -> dict:
    """
    Export connections of a project (for external editing).
    Note: Provided for backward compatibility; prefer dc_export
    (XMActionDCCommonExport) for new implementations.
    Action: XMExportConnectionsAction

    Args:
        destination: Target file (TXT, XLSX, XML; format per ConfigScheme
                     extension) (parameter Destination).
        project_name: Project path (parameter ProjectName).
        config_scheme: Configuration scheme (parameter ConfigScheme).
        language: Language code, e.g. "en_US" (parameter Language).
        complete_project: Export all connections, not only selected ones.
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return.
        immediate_import: Auto-import after edit (only for execution_mode 2).
        include_graphical_connections: Include graphical connections.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportConnectionsAction",
        ProjectName=project_name,
        Destination=destination,
        ConfigScheme=config_scheme,
        Language=language,
        CompleteProject=complete_project,
        ExecutionMode=execution_mode,
        ImmediateImport=immediate_import,
        IncludeGraphicalConnections=include_graphical_connections
    )
    return manager.execute_action(action)


def export_functions(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export functions of a project (for external editing).
    Note: Prefer dc_export (XMActionDCCommonExport) for new implementations.
    Action: XMExportFunctionAction

    Args:
        destination: Target file (TXT, XLSX, XML) (parameter Destination).
        project_name: Project path (parameter ProjectName).
        config_scheme: Configuration scheme (parameter ConfigScheme).
        language: Language code (parameter Language).
        complete_project: Export all functions, not only selected ones.
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return.
        immediate_import: Auto-import after edit (only for execution_mode 2).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportFunctionAction",
        ProjectName=project_name,
        Destination=destination,
        ConfigScheme=config_scheme,
        Language=language,
        CompleteProject=complete_project,
        ExecutionMode=execution_mode,
        ImmediateImport=immediate_import
    )
    return manager.execute_action(action)


def export_pages(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export pages of a project (for external editing).
    Note: Prefer dc_export (XMActionDCCommonExport) for new implementations.
    Action: XMExportPagesAction

    Args:
        destination: Target file (TXT, XLSX, XML) (parameter Destination).
        project_name: Project path (parameter ProjectName).
        config_scheme: Configuration scheme (parameter ConfigScheme).
        language: Language code (parameter Language).
        complete_project: Export all pages, not only selected ones.
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return.
        immediate_import: Auto-import after edit (only for execution_mode 2).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportPagesAction",
        ProjectName=project_name,
        Destination=destination,
        ConfigScheme=config_scheme,
        Language=language,
        CompleteProject=complete_project,
        ExecutionMode=execution_mode,
        ImmediateImport=immediate_import
    )
    return manager.execute_action(action)


def dc_import(
    import_file: str,
    project_name: str = None,
    progress_title: str = None
) -> dict:
    """
    Import a data configuration file into an existing EPLAN project.
    This allows the properties of functions to be changed.
    Action: XMActionDCImport

    Args:
        import_file: Path of the data configuration (.edc) file
                     (parameter DataConfigurationFile).
        project_name: Project path (parameter ProjectLink).
        progress_title: Optional progress title (parameter ProgressTitle).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMActionDCImport",
        ProjectLink=project_name,
        DataConfigurationFile=import_file,
        ProgressTitle=progress_title
    )
    return manager.execute_action(action)


def dc_export(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export project data configuration for external editing.
    This is the recommended action for connections/functions/pages/etc. export.
    Action: XMActionDCCommonExport

    Validated 2026-07-24 against EPLAN 2025 in a 467-project unattended batch
    (execution_mode=2, immediate_import=True, complete_project=True): 467/467
    returned success with no manual interaction and no errors.

    IMPORTANT — execution_mode=2 does NOT pause for manual editing here.
    Every action in this wrapper runs under QuietMode (QuietModes.ShowNoDialogs,
    see _base.py) so no EPLAN dialog can block an unattended call. Normally
    execution_mode=2 ("Edit and return") opens the exported file (e.g. in Excel)
    and waits for a human to edit and close it before continuing/reimporting.
    Under QuietMode that interactive step is suppressed — the call returns
    almost immediately, and with immediate_import=True the exported data is
    reimported essentially unchanged (a no-op roundtrip), not a human-edited
    result. If you actually need a human to edit the data before reimport, this
    wrapper cannot provide that; use execution_mode=0 (plain export, no
    reimport) and handle editing/reimport as separate steps outside QuietMode.

    A batch across many projects with immediate_import=True writes back into
    each project (even if effectively a no-op roundtrip) — treat it as a
    write operation requiring the same care as any other project mutation
    (backups, off-hours, etc.), not as a read-only export.

    Args:
        destination: Target file (TXT, XLSX, XML; format per CONFIGSCHEME
                     extension) (parameter DESTINATION). Must be unique per
                     call when batching multiple projects.
        project_name: Project path (parameter PROJECTNAME). The action opens
                      the referenced project internally; it does not need to
                      already be open in the EPLAN GUI.
        config_scheme: Configuration scheme (parameter CONFIGSCHEME). If not set,
                       a dialog asks for it — under QuietMode this likely hangs
                       or fails silently instead. Always pass this explicitly.
        language: Language code, e.g. "en_US" or "??_??" for all (parameter LANGUAGE).
        complete_project: Export the whole project, not only selected objects.
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return (see
                        QuietMode caveat above — mode 2 behaves like a
                        roundtrip export+reimport under this wrapper, not a
                        real interactive edit).
        immediate_import: Auto-import after edit (only for execution_mode 2).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMActionDCCommonExport",
        PROJECTNAME=project_name,
        DESTINATION=destination,
        CONFIGSCHEME=config_scheme,
        LANGUAGE=language,
        COMPLETEPROJECT=complete_project,
        EXECUTIONMODE=execution_mode,
        IMMEDIATEIMPORT=immediate_import
    )
    return manager.execute_action(action)


def export_dc_article_data(
    destination: str,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export article data for external editing.
    Action: XMExportDCArticleDataAction

    Args:
        destination: Target file (TXT, XLSX, XML based on scheme)
        config_scheme: Configuration scheme (dialog shown if not set)
        language: Language code (e.g., "en_US")
        complete_project: Export whole database, not just selected objects
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return
        immediate_import: Auto-import after edit (only for mode 2)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportDCArticleDataAction",
        DESTINATION=destination,
        CONFIGSCHEME=config_scheme,
        LANGUAGE=language,
        COMPLETEPROJECT=complete_project,
        EXECUTIONMODE=execution_mode,
        IMMEDIATEIMPORT=immediate_import
    )
    return manager.execute_action(action)


def import_dc_article_data(
    import_file: str,
    show_import_messages: bool = None,
    import_mode: int = None,
    identify_by_name: bool = None,
    progress_title: str = None
) -> dict:
    """
    Import a data configuration (.edc) file into the article database.
    Action: XMImportDCArticleDataAction

    The previous wrapper sent PROJECTNAME/IMPORTFILE, neither a real
    parameter of this action - it targets the ARTICLE DATABASE, not a
    project, and its file parameter is DATACONFIGURATIONFILE. Live-verified
    2026-09-04: with the old parameters EPLAN logged "attempted to start the
    XMPxfArticleImportDialog dialog in batch mode" and returned
    success:false; with the corrected parameters AND show_import_messages=
    False it ran to completion instead. show_import_messages defaults to
    True in EPLAN itself (an info dialog), which is a strong candidate for
    the same block if left unset here - pass False for an unattended call.
    Audit #42 item 5.

    Args:
        import_file: Path to the .edc data configuration file.
        show_import_messages: Show the info dialog with the added-part count
            (optional; EPLAN's own default is True - see above). Pass False
            for an unattended call.
        import_mode: 0 = only create new objects, 1 = only update existing
            objects, 2 = create new and update objects (optional; if
            omitted, EPLAN may show a question dialog when new objects are
            found).
        identify_by_name: Identify objects by name instead of ID (optional;
            EPLAN's default is by ID).
        progress_title: Title for the progress dialog (optional).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMImportDCArticleDataAction",
        DATACONFIGURATIONFILE=import_file,
        SHOWIMPORTMESSAGES=show_import_messages,
        IMPORTMODE=import_mode,
        IDENTIFYBYNAMEINSTEADOFID=identify_by_name,
        PROGRESSTITLE=progress_title
    )
    return manager.execute_action(action)


def export_location_boxes(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export location boxes of a project.
    Note: Use dc_export (XMActionDCCommonExport) for new implementations.
    Action: XMExportLocationBoxesAction

    Args:
        destination: Target file (TXT, XLS, XML)
        project_name: Project path (optional)
        config_scheme: Configuration scheme
        language: Language code
        complete_project: Export all pages, not just selected
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return
        immediate_import: Auto-import after edit (only for mode 2)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportLocationBoxesAction",
        ProjectName=project_name,
        Destination=destination,
        ConfigScheme=config_scheme,
        Language=language,
        CompleteProject=complete_project,
        ExecutionMode=execution_mode,
        ImmediateImport=immediate_import
    )
    return manager.execute_action(action)


def export_potential_definitions(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export potential definitions of a project.
    Note: Use dc_export (XMActionDCCommonExport) for new implementations.
    Action: XMExportPotentialDefsAction

    Args:
        destination: Target file (TXT, XLS, XML)
        project_name: Project path (optional)
        config_scheme: Configuration scheme
        language: Language code
        complete_project: Export all pages, not just selected
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return
        immediate_import: Auto-import after edit (only for mode 2)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportPotentialDefsAction",
        ProjectName=project_name,
        Destination=destination,
        ConfigScheme=config_scheme,
        Language=language,
        CompleteProject=complete_project,
        ExecutionMode=execution_mode,
        ImmediateImport=immediate_import
    )
    return manager.execute_action(action)


def export_pipeline_definitions(
    destination: str,
    project_name: str = None,
    config_scheme: str = None,
    language: str = None,
    complete_project: bool = False,
    execution_mode: int = 0,
    immediate_import: bool = False
) -> dict:
    """
    Export pipeline definitions of a project.
    Action: XMExportPipeLineDefsAction

    Args:
        destination: Target file (TXT, XLS, XML)
        project_name: Project path (optional)
        config_scheme: Configuration scheme
        language: Language code
        complete_project: Export all pages, not just selected
        execution_mode: 0=Export, 1=Export and edit, 2=Edit and return
        immediate_import: Auto-import after edit (only for mode 2)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMExportPipeLineDefsAction",
        ProjectName=project_name,
        Destination=destination,
        ConfigScheme=config_scheme,
        Language=language,
        CompleteProject=complete_project,
        ExecutionMode=execution_mode,
        ImmediateImport=immediate_import
    )
    return manager.execute_action(action)


def delete_representation_type(
    representation_type: int,
    source: str,
    destination: str
) -> dict:
    """
    Remove a representation type from macro files, written to a new location.
    Action: XMDeleteReprTypeAction

    This is a macro-file utility, not a project action: the previous wrapper
    only sent PROJECTNAME, but the action's real (and only) parameters are
    RepresentationType/Source/Destination - project_name never had anything
    to do with it. Audit #42 item 7.

    EPLAN's docs mark this action "can only be used interactively", and
    that is confirmed, not theoretical: live-verified 2026-09-04 with
    correct parameters (a real macro as Source, an empty scratch directory
    as Destination) - the call returns success:true, logs no error, and
    Destination stays empty. Under this server's forced QuietMode the
    action is a genuine no-op, not a wrapper bug. There is no known
    workaround; this is documented so a caller does not spend time
    debugging parameters that were never the problem.

    Source is read from, not modified; the result is written under
    Destination (a directory), so the input macro(s) are left untouched.

    Args:
        representation_type: Representation type to remove, 0-13: 0 Neutral,
            1 MultiLine, 2 SingleLine, 3 PairCrossReference, 4 Overview,
            5 Graphics, 6 ArticlePlacement, 7 PI_FlowChart, 8 Fluid_MultiLine,
            9 Cabling, 10 ArticlePlacement3D, 11 Functional, 12 Planning,
            13 FluidFunctionalOverview.
        source: A file, directory, or wildcard pattern selecting the macro(s)
            to process (e.g. "C:/macros/*.ema").
        destination: Output directory the processed macro(s) are written to.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XMDeleteReprTypeAction",
        RepresentationType=representation_type,
        Source=source,
        Destination=destination
    )
    return manager.execute_action(action)


def correct_connections() -> dict:
    """
    Merge graphical properties of connection definition points.
    Action: EsCorrectConnections
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    return manager.execute_action("EsCorrectConnections")


def remove_unnecessary_ndps() -> dict:
    """
    Remove unnecessary net definition points.
    Action: XCMRemoveUnnecessaryNDPsAction
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    return manager.execute_action("XCMRemoveUnnecessaryNDPsAction")


def unite_net_definition_points() -> dict:
    """
    Unite net definition points on the same net.
    Action: XCMUniteNetDefinitionPointsAction
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    return manager.execute_action("XCMUniteNetDefinitionPointsAction")


def export_subproject(
    destination_path: str = None,
    project_name: str = None,
    subproject_number: str = None,
    extend_only: bool = None
) -> dict:
    """
    Export (split off) a subproject.
    Action: subprojects (TYPE=FILEOFF)

    Note: The project must be opened in exclusive mode. After this action the
    source project object becomes invalid.

    Args:
        destination_path: Target directory (parameter DESTINATIONPATH).
                          Default is "$(MD_PROJECTS)".
        project_name: Project path (parameter PROJECTNAME).
        subproject_number: Subproject number (parameter SPNR).
        extend_only: Extend subproject only (parameter EXTENDONLY).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "subprojects",
        TYPE="FILEOFF",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        SPNR=subproject_number,
        EXTENDONLY=extend_only
    )
    return manager.execute_action(action)


def import_subproject(
    project_name: str = None,
    subproject_number: str = None,
    subproject_dir: str = None
) -> dict:
    """
    Import (store back) a subproject.
    Action: subprojects (TYPE=STORE)

    Note: The project must be opened in exclusive mode.

    Args:
        project_name: Project path (parameter PROJECTNAME).
        subproject_number: Subproject number (parameter SPNR).
        subproject_dir: Directory where the subproject is placed
                        (parameter SUBPROJECTDIR, STORE only). Default is
                        taken from the alias.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "subprojects",
        TYPE="STORE",
        PROJECTNAME=project_name,
        SPNR=subproject_number,
        SUBPROJECTDIR=subproject_dir
    )
    return manager.execute_action(action)


def masterdata_operation(
    operation_type: str,
    source_path: str = None,
    destination_path: str = None
) -> dict:
    """
    Perform master data operations.
    Action: masterdata
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "masterdata",
        TYPE=operation_type,
        SOURCEPATH=source_path,
        DESTINATIONPATH=destination_path
    )
    return manager.execute_action(action)
