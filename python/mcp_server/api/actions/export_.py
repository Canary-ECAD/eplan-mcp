"""
Export actions (PDF, DXF, DWG, graphics, PXF, 3D, etc.)
Complete implementation with all documented parameters.
"""

from typing import List, Optional
from ._base import (_get_connected_manager, _build_action, _execute_with_quiet_mode,
                    _quote_param, _execute_and_report_written)


def export_pdf_project(
    export_file: str,
    project_name: str = None,
    export_scheme: str = None,
    black_white: int = 0,
    language: str = None,
    use_zoom: bool = False,
    zoom_level: int = None,
    use_simple_link: bool = False,
    fast_web_view: bool = False,
    read_only: bool = False,
    use_print_margins: bool = None,
    export_model: bool = False
) -> dict:
    """
    Export project to PDF format (with QuietMode - no dialogs).
    Action: export

    WARNING - omitting export_scheme can silently change where the PDF goes.
    Measured 2026-09-03 on EPLAN 2027.0.1, reproduced 3x: with export_scheme
    omitted this returned {"success": true} and wrote "-1.pdf" instead of the
    requested filename. Per EPLAN's docs an absent EXPORTSCHEME makes it use
    "the most recently used" export scheme, and that scheme's own output
    settings override EXPORTFILE's basename. Supplying a valid scheme honoured
    the requested path exactly.

    The fallback scheme is readable, so you do not have to guess: list the
    schemes with settings_list_children("USER.PDFExportGUI.SCHEMAS") and read
    which one EPLAN will fall back to with
    settings_get_string("USER.PDFExportGUI.SCHEMAS.LastUsed"). Pass an
    explicit export_scheme whenever the output filename matters, and verify
    the file on disk afterwards rather than trusting success:true.

    The result says which files were really written. requestedFile is what you
    asked for, requestedFileWritten says whether that exact basename appeared
    or changed, and writtenFiles lists every file that changed in the target
    directory during the call. When the requested basename is absent, note
    explains it. If the directory could not be listed, verification says so
    rather than claiming nothing was written.

    Args:
        export_file: Output PDF file path. The directory is honoured; the
            basename can be overridden by the scheme (see WARNING above).
        project_name: Project path (optional)
        export_scheme: PDF export scheme name. Optional to EPLAN, but treat
            it as required whenever you care about the output filename.
        black_white: 0=Color, 1=B&W, 2=Grayscale, 3=White Inverted
        language: Language code (e.g., "en_US")
        use_zoom: Enable zoom window for navigation
        zoom_level: Zoom level in mm (1-3500)
        use_simple_link: Only create simple links in PDF (no three-way jumps)
        fast_web_view: Enable fast web display
        read_only: Make PDF write-protected
        use_print_margins: Use print margins (None=from scheme)
        export_model: Export 3D models along with pages
    """
    params = {
        # PDFPROJECTSCHEME is correct and deliberate: API Reference/Actions/
        # export.md lists no scheme-less project-PDF TYPE. ProjectAction.md's
        # own example does show /TYPE:PDFPROJECT passed through to this
        # action, so EPLAN's docs are self-inconsistent - do not "fix" this
        # to PDFPROJECT on the strength of that example. The wrong-filename
        # behaviour documented above comes from the absent EXPORTSCHEME, not
        # from this TYPE.
        "TYPE": "PDFPROJECTSCHEME",
        "PROJECTNAME": project_name,
        "EXPORTFILE": export_file,
        "EXPORTSCHEME": export_scheme,
        "BLACKWHITE": black_white,
        "LANGUAGE": language,
        "USEZOOM": use_zoom,
        "ZOOMLEVEL": zoom_level,
        "USESIMPLELINK": use_simple_link,
        "FASTWEBVIEW": fast_web_view,
        "READONLYEXPORT": read_only,
        "EXPORTMODEL": export_model,
    }

    if use_print_margins is not None:
        params["USEPRINTMARGINS"] = use_print_margins

    action = _build_action("export", **params)
    return _execute_and_report_written(action, export_file)


def export_pdf_pages(
    export_file: str,
    page_names: List[str] = None,
    page_identifiers: List[str] = None,
    project_name: str = None,
    export_scheme: str = None,
    black_white: int = 0,
    language: str = None,
    use_zoom: bool = False,
    zoom_level: int = None,
    use_simple_link: bool = False,
    fast_web_view: bool = False,
    read_only: bool = False,
    use_print_margins: bool = None,
    export_model: bool = False
) -> dict:
    """
    Export specific pages to PDF format (with QuietMode - no dialogs).
    Action: export

    WARNING - same scheme hazard as export_pdf_project: with export_scheme
    omitted EPLAN falls back to "the most recently used" export scheme, whose
    output settings can override EXPORTFILE's basename while the call still
    returns success:true. Also observed on a production project (2026-09-01),
    where the written basename came from the scheme, not from the request, and
    the caller only found out by listing the directory. Read the fallback with
    settings_get_string("USER.PDFExportGUI.SCHEMAS.LastUsed"), pass an explicit
    export_scheme when the filename matters, and check the file on disk.

    The result says which files were really written. requestedFile is what you
    asked for, requestedFileWritten says whether that exact basename appeared
    or changed, and writtenFiles lists every file that changed in the target
    directory during the call. When the requested basename is absent, note
    explains it. If the directory could not be listed, verification says so
    rather than claiming nothing was written.

    Args:
        export_file: Output PDF file path. Directory honoured; basename can be
            overridden by the scheme (see WARNING above).
        page_names: List of page names (e.g., ["=AP+ST1/2", "=AP+ST1/4"])
        page_identifiers: List of page identifiers from StorableObject.ToStringIdentifier()
        project_name: Project path (optional)
        export_scheme: PDF export scheme name. Optional to EPLAN, but treat as
            required whenever you care about the output filename.
        black_white: 0=Color, 1=B&W, 2=Grayscale, 3=White Inverted
        language: Language code
        use_zoom: Enable zoom window
        zoom_level: Zoom level in mm (1-3500)
        use_simple_link: Only simple links
        fast_web_view: Enable fast web display
        read_only: Write-protected PDF
        use_print_margins: Use print margins
        export_model: Export 3D models
    """
    parts = ["export", "/TYPE:PDFPAGESSCHEME", _quote_param("EXPORTFILE", export_file)]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if export_scheme:
        parts.append(_quote_param("EXPORTSCHEME", export_scheme))

    parts.append(f"/BLACKWHITE:{black_white}")

    if language:
        parts.append(f"/LANGUAGE:{language}")
    if use_zoom:
        parts.append("/USEZOOM:1")
    if zoom_level:
        parts.append(f"/ZOOMLEVEL:{zoom_level}")
    if use_simple_link:
        parts.append("/USESIMPLELINK:1")
    if fast_web_view:
        parts.append("/FASTWEBVIEW:1")
    if read_only:
        parts.append("/READONLYEXPORT:1")
    if use_print_margins is not None:
        parts.append(f"/USEPRINTMARGINS:{1 if use_print_margins else 0}")
    if export_model:
        parts.append("/EXPORTMODEL:1")

    # Add page names
    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    # Add page identifiers (SELn)
    if page_identifiers:
        for i, sel in enumerate(page_identifiers, 1):
            parts.append(f"/SEL{i}:{sel}")

    return _execute_and_report_written(" ".join(parts), export_file)


def export_dxf_project(
    destination_path: str,
    project_name: str = None,
    export_scheme: str = None,
    language: str = None,
    target: str = None
) -> dict:
    """
    Export project to DXF format.
    Action: export

    Args:
        destination_path: Output directory
        project_name: Project path (optional)
        export_scheme: DXF export scheme
        language: Language code (case-sensitive, e.g., "en_US")
        target: "Disk" or "FromSettings"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "export",
        TYPE="DXFPROJECT",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        EXPORTSCHEME=export_scheme,
        LANGUAGE=language,
        TARGET=target
    )
    return manager.execute_action(action)


def export_dxf_pages(
    destination_path: str = None,
    page_name: str = None,
    page_names: List[str] = None,
    project_name: str = None,
    export_scheme: str = None,
    language: str = None,
    target: str = None
) -> dict:
    """
    Export pages to DXF format.
    Action: export

    Args:
        destination_path: Output directory (ignored if using PAGENAMEn with scheme)
        page_name: Single page name
        page_names: List of page names for multiple export
        project_name: Project path (optional)
        export_scheme: DXF export scheme
        language: Language code
        target: "Disk" or "FromSettings"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["export", "/TYPE:DXFPAGE"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if destination_path:
        parts.append(_quote_param("DESTINATIONPATH", destination_path))
    if export_scheme:
        parts.append(_quote_param("EXPORTSCHEME", export_scheme))
    if language:
        parts.append(f"/LANGUAGE:{language}")
    if target:
        parts.append(f"/TARGET:{target}")

    if page_name:
        parts.append(_quote_param("PAGENAME", page_name))

    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    return manager.execute_action(" ".join(parts))


def export_dwg_project(
    destination_path: str,
    project_name: str = None,
    export_scheme: str = None,
    language: str = None,
    target: str = None
) -> dict:
    """
    Export project to DWG format.
    Action: export

    Args:
        destination_path: Output directory
        project_name: Project path (optional)
        export_scheme: DWG export scheme
        language: Language code
        target: "Disk" or "FromSettings"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "export",
        TYPE="DWGPROJECT",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        EXPORTSCHEME=export_scheme,
        LANGUAGE=language,
        TARGET=target
    )
    return manager.execute_action(action)


def export_dwg_pages(
    destination_path: str = None,
    page_name: str = None,
    page_names: List[str] = None,
    project_name: str = None,
    export_scheme: str = None,
    language: str = None,
    target: str = None
) -> dict:
    """
    Export pages to DWG format.
    Action: export

    Args:
        destination_path: Output directory
        page_name: Single page name
        page_names: List of page names
        project_name: Project path (optional)
        export_scheme: DWG export scheme
        language: Language code
        target: "Disk" or "FromSettings"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["export", "/TYPE:DWGPAGE"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if destination_path:
        parts.append(_quote_param("DESTINATIONPATH", destination_path))
    if export_scheme:
        parts.append(_quote_param("EXPORTSCHEME", export_scheme))
    if language:
        parts.append(f"/LANGUAGE:{language}")
    if target:
        parts.append(f"/TARGET:{target}")

    if page_name:
        parts.append(_quote_param("PAGENAME", page_name))

    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    return manager.execute_action(" ".join(parts))


def export_dxfdwg_project_scheme(
    project_name: str = None,
    export_scheme: str = None,
    language: str = None,
    target: str = "FromSettings"
) -> dict:
    """
    Export project to DXF or DWG format using scheme settings.
    Format (DXF or DWG) is determined by the scheme.
    Action: export

    Args:
        project_name: Project path (optional)
        export_scheme: Export scheme (determines DXF or DWG)
        language: Language code
        target: "Disk" or "FromSettings" (default)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "export",
        TYPE="DXFDWGPROJECTSCHEME",
        PROJECTNAME=project_name,
        EXPORTSCHEME=export_scheme,
        LANGUAGE=language,
        TARGET=target
    )
    return manager.execute_action(action)


def export_dxfdwg_pages_scheme(
    page_names: List[str] = None,
    page_identifiers: List[str] = None,
    project_name: str = None,
    export_scheme: str = None,
    language: str = None,
    target: str = "FromSettings"
) -> dict:
    """
    Export pages to DXF or DWG format using scheme settings.
    Format is determined by the scheme.
    Action: export

    Args:
        page_names: List of page names
        page_identifiers: List of page identifiers (SELn)
        project_name: Project path (optional)
        export_scheme: Export scheme
        language: Language code
        target: "Disk" or "FromSettings"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["export", "/TYPE:DXFDWGPPAGESSCHEME"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if export_scheme:
        parts.append(_quote_param("EXPORTSCHEME", export_scheme))
    if language:
        parts.append(f"/LANGUAGE:{language}")
    if target:
        parts.append(f"/TARGET:{target}")

    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    if page_identifiers:
        for i, sel in enumerate(page_identifiers, 1):
            parts.append(f"/SEL{i}:{sel}")

    return manager.execute_action(" ".join(parts))


def export_graphics_project(
    destination_path: str,
    project_name: str = None,
    format: str = "PNG",
    color_depth: int = 24,
    image_width: int = 1024,
    black_white: bool = False,
    compression: str = "NONE"
) -> dict:
    """
    Export project to graphical format (PNG, TIF, GIF, JPG, BMP).
    Action: export

    Args:
        destination_path: Output directory
        project_name: Project path (optional)
        format: Image format - "PNG", "TIF", "GIF", "JPG", "BMP"
        color_depth: 1, 4, 8, 16, 24, or 32
        image_width: Image width in pixels
        black_white: Black and white output
        compression: For TIF - "LZW", "RLE", "CCITT3", "CCITT4", "NONE"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "export",
        TYPE="GRAPHICPROJECT",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        FORMAT=format,
        COLORDEPTH=color_depth,
        IMAGEWIDTH=image_width,
        BLACKWHITE=black_white,
        IMAGECOMPRESSION=compression
    )
    return manager.execute_action(action)


def export_graphics_pages(
    destination_path: str,
    page_name: str = None,
    project_name: str = None,
    format: str = "PNG",
    color_depth: int = 24,
    image_width: int = 1024,
    black_white: bool = False,
    compression: str = "NONE",
    use_page_filter: bool = False
) -> dict:
    """
    Export pages to graphical format (PNG, TIF, GIF, JPG, BMP).
    Action: export

    Args:
        destination_path: Output directory
        page_name: Specific page name (optional, if not set uses filter or all)
        project_name: Project path (optional)
        format: Image format - "PNG", "TIF", "GIF", "JPG", "BMP"
        color_depth: 1, 4, 8, 16, 24, or 32
        image_width: Image width in pixels
        black_white: Black and white output
        compression: For TIF - "LZW", "RLE", "CCITT3", "CCITT4", "NONE"
        use_page_filter: Use active page filter (ignored if page_name is set)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "export",
        TYPE="GRAPHICPAGE",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        PAGENAME=page_name,
        FORMAT=format,
        COLORDEPTH=color_depth,
        IMAGEWIDTH=image_width,
        BLACKWHITE=black_white,
        IMAGECOMPRESSION=compression,
        USEPAGEFILTER=use_page_filter
    )
    return manager.execute_action(action)


def export_pxf_project(
    export_file: str,
    project_name: str = None,
    export_masterdata: bool = True,
    export_connections: bool = False
) -> dict:
    """
    Export project in EPJ/PXF format.
    Action: export

    EPLAN appends the extension itself, so the file on disk is normally NOT
    the basename you passed. The result reports the difference rather than
    echoing the request back: requestedFile, requestedFileWritten, and
    writtenFiles - every file that changed in the target directory during
    the call. Unlike the PDF wrappers this has not been measured live; the
    shape of the mutation is taken from EPLAN's own documented behaviour.

    Args:
        export_file: Output file path (extension added automatically)
        project_name: Project path (optional)
        export_masterdata: Include master data (default True)
        export_connections: Include connections (default False)
    """
    # The _get_connected_manager() guard that stood here is gone, not
    # moved: _execute_and_report_written performs the same check, and
    # holding a manager here only to ignore it left the wrapper looking
    # like it still executed the action itself. Same shape as the two
    # PDF wrappers now.
    action = _build_action(
        "export",
        TYPE="PXFPROJECT",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file,
        EXPORTMASTERDATA=export_masterdata,
        EXPORTCONNECTIONS=export_connections
    )
    return _execute_and_report_written(action, export_file)


def export_3d(
    destination_path: str,
    type: str,
    project_name: str = None,
    installation_space: str = None,
    export_scheme: str = None,
    separate_files: bool = None,
    filename: str = None
) -> dict:
    """
    Export installation spaces to 3D formats.
    Action: export3d

    Live-verified 2026-09-04 (2025.0.3, Pro Panel licensed): the previous
    wrapper sent FORMAT/INSTALLATIONSPACE, neither a real export3d parameter,
    and never sent the mandatory TYPE - EPLAN answered every call with
    "Este proceso no es compatible." and nothing was written. See Audit #42
    item 1.

    Args:
        destination_path: Output directory. Created if it does not exist.
        type: "STEP" or "JT". Mandatory - the action has no default and
            silently rejects the call without it.
        project_name: Project path (optional). Required if there is no
            project with focus in the EPLAN GUI.
        installation_space: Name of the layout space to export. If omitted,
            the entire project is exported.
        export_scheme: Export scheme (optional). Only effective with
            type="STEP"; if omitted the last-used scheme applies.
        separate_files: Write one file per installation space instead of a
            single combined file (optional). Only effective with type="STEP".
        filename: Output file name (optional). Only effective with
            type="JT".
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    if type not in ("STEP", "JT"):
        return {"success": False,
                "error": f"type must be 'STEP' or 'JT', got {type!r}."}

    action = _build_action(
        "export3d",
        TYPE=type,
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        INSTALLATIONSPACENAME=installation_space,
        EXPORTSCHEME=export_scheme,
        SEPARATEFILES=separate_files,
        FILENAME=filename
    )
    return manager.execute_action(action)


def export_to_graphics(
    destination_path: str,
    type: str = "GRAPHICPROJECT",
    project_name: str = None,
    page_name: str = None,
    export_scheme: str = None,
    format: str = None,
    color_depth: int = None,
    image_width: int = None,
    image_compression: str = None,
    black_white: bool = None,
    use_page_filter: bool = None
) -> dict:
    """
    Export pages or a whole project to a graphical format (TIF, GIF, PNG, JPG, BMP).
    Action: exportToGraphics

    How this differs from export_graphics_project / export_graphics_pages
    (which drive the generic "export" action with TYPE=GRAPHICPROJECT /
    TYPE=GRAPHICPAGE): both reach the same graphical export, but the generic
    "export" wrappers take no EXPORTSCHEME and therefore hard-code FORMAT,
    COLORDEPTH and IMAGEWIDTH on every call. exportToGraphics is the dedicated,
    scheme-driven entry point: pass export_scheme and leave the image options
    None so the scheme supplies them, and it additionally exposes USEPAGEFILTER
    for project-level exports.

    Use export_to_graphics when a graphical export scheme is configured in the
    project (the normal case) or when you need USEPAGEFILTER. Use the older
    export_graphics_project / export_graphics_pages when you want to state every
    image option explicitly with no scheme involved.

    Note the documented default of BLACKWHITE is 1 - leaving black_white None
    yields a black/white image, unlike export_graphics_project whose
    black_white defaults to False (color).

    Args:
        destination_path: Target directory. Created if missing. For a project
                          export a subdirectory named after the project is
                          created below it.
        type: "GRAPHICPROJECT" (whole project) or "GRAPHICPAGE" (pages)
        project_name: Project path with full path (optional; selected project if omitted)
        page_name: Page to export - only effective with type="GRAPHICPAGE"
        export_scheme: Graphical export scheme; supplies defaults for the other
                       optional parameters. Most recently used scheme if omitted.
        format: Output format - "BMP", "TIF", "GIF", "PNG", "JPG"
        color_depth: 1, 8, 16, 24 or 32 (format dependent)
        image_width: Image width in pixels; height follows the page dimensions
        image_compression: TIF only - "LZW", "RLE", "CCITT3", "CCITT4", "NONE".
                           CCITT3/CCITT4/RLE force color depth 1.
        black_white: Output in black and white. Documented default: 1 (true).
        use_page_filter: Export only filtered pages instead of all project pages
                         (matches the "Active" check box in the page navigator).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "exportToGraphics",
        TYPE=type,
        PROJECTNAME=project_name,
        PAGENAME=page_name,
        EXPORTSCHEME=export_scheme,
        DESTINATIONPATH=destination_path,
        FORMAT=format,
        COLORDEPTH=color_depth,
        IMAGEWIDTH=image_width,
        IMAGECOMPRESSION=image_compression,
        BLACKWHITE=black_white,
        USEPAGEFILTER=use_page_filter
    )
    return manager.execute_action(action)
