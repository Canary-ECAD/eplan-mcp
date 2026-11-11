"""
Import actions (PXF, DWG, DXF, 3D, PDF comments, etc.)
Complete implementation with all documented parameters.
"""

from typing import Optional
from ._base import _get_connected_manager, _build_action


def import_pxf_project(
    import_file: str,
    project_name: str,
    balance_articles: bool = False,
    generate_auto_cables: bool = False,
    verify: bool = False
) -> dict:
    """
    Import a PXF/EPJ project.
    Action: import

    Args:
        import_file: Path to PXF file
        project_name: Target project path
        balance_articles: Sync parts with database
        generate_auto_cables: Generate automatic cables
        verify: Run project check after import
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "import",
        TYPE="PXFPROJECT",
        IMPORTFILE=import_file,
        PROJECTNAME=project_name,
        BALANCEARTICLES=balance_articles,
        GENERATEAUTOMATICCABLES=generate_auto_cables,
        VERIFY=verify
    )
    return manager.execute_action(action)


def import_dwg_page(
    import_file: str,
    page_name: str,
    project_name: str = None,
    import_scheme: str = None,
    x_scale: float = 1.0,
    y_scale: float = 1.0,
    x_offset: float = 0.0,
    y_offset: float = 0.0
) -> dict:
    """
    Insert DWG drawing into a page.
    Action: import

    Args:
        import_file: Path to DWG file
        page_name: Target page name
        project_name: Project path (optional)
        import_scheme: DWG import scheme name (without path)
        x_scale: Scaling in X direction (default 1.0)
        y_scale: Scaling in Y direction (default 1.0)
        x_offset: Move in X direction (default 0.0)
        y_offset: Move in Y direction (default 0.0)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "import",
        TYPE="DWGPAGE",
        IMPORTFILE=import_file,
        PAGENAME=page_name,
        PROJECTNAME=project_name,
        IMPORTSCHEME=import_scheme,
        XSCALE=x_scale,
        YSCALE=y_scale,
        XOFFSET=x_offset,
        YOFFSET=y_offset
    )
    return manager.execute_action(action)


def import_dxf_page(
    import_file: str,
    page_name: str,
    project_name: str = None,
    import_scheme: str = None,
    x_scale: float = 1.0,
    y_scale: float = 1.0,
    x_offset: float = 0.0,
    y_offset: float = 0.0
) -> dict:
    """
    Insert DXF drawing into a page.
    Action: import

    Args:
        import_file: Path to DXF file
        page_name: Target page name
        project_name: Project path (optional)
        import_scheme: DXF import scheme name
        x_scale: Scaling in X direction
        y_scale: Scaling in Y direction
        x_offset: Move in X direction
        y_offset: Move in Y direction
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "import",
        TYPE="DXFPAGE",
        IMPORTFILE=import_file,
        PAGENAME=page_name,
        PROJECTNAME=project_name,
        IMPORTSCHEME=import_scheme,
        XSCALE=x_scale,
        YSCALE=y_scale,
        XOFFSET=x_offset,
        YOFFSET=y_offset
    )
    return manager.execute_action(action)


def import_dxfdwg_files(
    source_path: str,
    destination_path: str,
    project_name: str = None,
    import_scheme: str = None,
    macro_project: str = None,
    only_macro_project: bool = False,
    code_page: int = 437
) -> dict:
    """
    Import DXF/DWG drawings as macros.
    The import is not made via the project, but the DXF/DWG files are
    directly imported from a directory into macros.
    Action: import

    Args:
        source_path: Directory where DXF/DWG files are located
        destination_path: Directory where imported macros are stored
        project_name: Project path (optional)
        import_scheme: DXF/DWG import scheme name
        macro_project: Full path of new macro project (.elk)
        only_macro_project: Only create macro project without auto export
        code_page: Code page (default 437)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "import",
        TYPE="DXFDWGFILES",
        SOURCEPATH=source_path,
        DESTINATIONPATH=destination_path,
        PROJECTNAME=project_name,
        IMPORTSCHEME=import_scheme,
        MACROPROJECT=macro_project,
        ONLYMACROPROJECT=only_macro_project,
        CODEPAGE=code_page
    )
    return manager.execute_action(action)


def import_pdf_comments(
    import_file: str,
    project_name: str
) -> dict:
    """
    Import PDF comments into project.
    Note: Some settings need to be configured before importing.
    Action: import

    Args:
        import_file: Path to PDF file with comments
        project_name: Project path (required)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "import",
        TYPE="PDFCOMMENTS",
        IMPORTFILE=import_file,
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)


def import_3d(
    import_file: str,
    type: str,
    project_name: str = None,
    import_scheme: str = None
) -> dict:
    """
    Import 3D data.
    Action: import3d

    Live-verified 2026-09-04 (2025.0.3, Pro Panel licensed): the previous
    wrapper never sent the mandatory TYPE and sent IMPORTSCHEME, which is not
    a real import3d parameter (the action documents SCHEME) - EPLAN answered
    every call with "Este proceso no es compatible." and nothing was
    imported. See Audit #42 item 4.

    Args:
        import_file: Path to the 3D file to import.
        type: "STEP", "DESIGNSPACE" (a design space, itself a STEP file), or
            "JT". Mandatory - the action has no default and silently rejects
            the call without it.
        project_name: Project path (optional). Required if there is no
            project with focus in the EPLAN GUI.
        import_scheme: Import scheme (optional). If omitted, the last-used
            scheme applies.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    if type not in ("STEP", "DESIGNSPACE", "JT"):
        return {"success": False,
                "error": f"type must be 'STEP', 'DESIGNSPACE' or 'JT', got {type!r}."}

    action = _build_action(
        "import3d",
        TYPE=type,
        IMPORTFILE=import_file,
        PROJECTNAME=project_name,
        SCHEME=import_scheme
    )
    return manager.execute_action(action)
