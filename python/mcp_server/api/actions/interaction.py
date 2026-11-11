"""
Graphical-editor (GED) interaction-start actions.

Every action here STARTS AN INTERACTIVE PLACEMENT in EPLAN's graphical editor:
it puts the GED into a mode that would normally be completed by a human
clicking in the drawing area.

MEASURED BEHAVIOUR (EPLAN 2027.0.1 Premium, scratch project, 2026-09-02) -
all four actions here were run live under QuietModes.ShowNoDialogs:
  - Each returned IMMEDIATELY. None blocked the caller.
  - A dismiss watch armed across all four recorded ZERO modal dialogs, so in
    practice these do not raise a blocking prompt.
  - start_ged_interaction returns success=False when no page is open in the
    editor, and success=True once one is. Open a page first (edit_open_page).
  - insert_device opens the configured parts database READ-ONLY to resolve the
    part number.

So these are safe to call unattended, with one caveat worth keeping in mind:
the call returning does not mean the interaction FINISHED - it means the
interaction was STARTED, and EPLAN is left in that mode. QuietMode suppresses
modal *dialogs*; it does not itself cancel a placement waiting for a click.
The two are different mechanisms, so a future EPLAN build or an interaction
name not covered above could still leave the editor parked in a mode.

Recommended when calling these in an unattended loop:
  1. If a call returns errorType EplanBlockedByDialog (or EplanBusy), call
     eplan_list_dialogs to see the prompt and eplan_click_dialog_button to
     dismiss it - that turns a surprise modal into evidence instead of a hang.
  2. Check eplan_get_system_messages afterwards - a hung EPLAN call is almost
     always a live interaction or a modal left on screen.
"""

from ._base import _get_connected_manager, _build_action


def start_ged_interaction(
    name: str,
    filename: str = None,
    variant: int = None
) -> dict:
    """
    Start an interaction of the graphical editor.
    Action: XGedStartInteractionAction

    INTERACTIVE: this arms a GED interaction that waits for
    user input in the graphical editor. Verified live: returns immediately and raises
    no modal; needs a page open in the editor first. See the module docstring.

    The official docs document only the "Name" parameter and give no list of
    valid interaction names. The names below were mined from the live install's
    GUI action map (Cfg/MFTools.xml) and are grouped by the entry-point action
    that actually dispatches them - passing a 2D/3D/comment name to this base
    action will not work.

    Names dispatched by THIS action (XGedStartInteractionAction):
        XMIaInsertMacro                  - insert a window/symbol macro
                                           (takes /filename and /variant)
        XMIaSetMacroBoxInsertionPoint    - set macro box insertion point
        XGedIaCenterViewPlacement        - center a view placement
        XGedIaFormatText                 - format text properties
        XGedIaFormatSymbol               - format symbol text properties
        XGedIaFormatGraphic              - format graphical element properties
        XGedIaFormatDefPoints            - format definition points

    Sibling entry points (dispatch these via eplan_execute_raw_action, not this
    wrapper - the action name itself differs):
        XGedStartInteractionAction2D     - XGedIaInsertLine, XGedIaInsertPolyline,
            XGedIaInsertClosedPolyline, XGedIaInsertRectangle,
            XGedIaInsertRectByCenter, XGedIaInsertCircle,
            XGedIaInsertCircleBy3Points, XGedIaInsertArc,
            XGedIaInsertArcBy3Points, XGedIaInsertEllipse, XGedIaInsertSector,
            XGedIaInsertSpline, XGedIaInsertText, XGedIaInsertImage,
            XGedIaInsertHyperlink, XGedIaInsertQRCode, XGedIaBuildBlock,
            XGedIaExplodeBlock, XGedIaRotate, XGedIaScale, XGedIaMirror,
            XGedIaStretchRectSelection, XGedIaMoveViewPlacement,
            XGedIaMoveSymbolTexts, XGedIaDockText, XGedIaUndockText,
            XGedIaToForeground, XGedIaToBackground, XGedIaEditChamfer,
            XGedIaEditCutOff, XGedIaEditRoundOff,
            XGedIaReferenceSymbolProperties, XDimIaInsertPointToMultipleDim
        XGedStartInteractionAction3D     - XGedIaMeasureDistance
        XGedStartInteractionActionComment - XGedIaInsertComment,
            XGedIaInsertBoxComment, XGedIaInsertPolylineComment

    Further interaction names appear in MFTools.xml but their dispatching action
    is unverified (do not assume they run through this action): the XCabIa*
    cabinet/3D family (XCabIaInsertMountingPlate, XCabIaInsertCabinet,
    XCabIaInsertDrillRound, XCabIaInsertMountingrail, ...), the XMEdIa* macro
    editor family (XMEdIaMoveSourcePlane, XMEdIaRotateSourcePlane, ...), and
    XMIaInsertPlaceHolder / XMIaSwapMacro / XMIaClipboardPaste.

    Args:
        name: Name of the interaction to be started (see the lists above),
            e.g. "XMIaInsertMacro"
        filename: Macro file path. Observed in MFTools.xml for XMIaInsertMacro
            only; note the lowercase parameter casing. Not in the official docs.
        variant: Macro variant number (0-based). Observed for XMIaInsertMacro
            only; lowercase casing. Not in the official docs.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XGedStartInteractionAction",
        Name=name,
        filename=filename,
        variant=variant
    )
    return manager.execute_action(action)


def insert_device(
    part_nr: str = None,
    part_variant: str = None,
    project_id: str = None,
    property_index: int = None
) -> dict:
    """
    Start the interaction for inserting a device.
    Action: XDLInsertDeviceAction

    INTERACTIVE: this starts a device placement interaction
    in the graphical editor and waits for the user to click an insertion point.
    Verified live: the call returns immediately and raised no modal, so it is
    safe unattended; if one ever returns EplanBlockedByDialog, use
    eplan_list_dialogs / eplan_click_dialog_button (see module docstring).

    Args:
        part_nr: Article part number
        part_variant: Variant of the article (e.g. "1")
        project_id: Project ID
        property_index: Index of the project article, must be in range 1-50.
            If 0, no project article is set.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XDLInsertDeviceAction",
        PartNr=part_nr,
        PartVariant=part_variant,
        ProjectId=project_id,
        PropertyIndex=property_index
    )
    return manager.execute_action(action)


def insert_symbol_reference(
    symbol_lib_name: str = None,
    symbol_id: int = None,
    variant_id: int = None,
    fct_def_tag: str = None,
    placement_mode: str = None,
    symbol_type: int = None,
    custom_symbols: str = None,
    cursor: str = None
) -> dict:
    """
    Find a symbol reference and start the interaction for inserting it.
    Action: XEGActionInsertSymRef

    INTERACTIVE: this arms a symbol placement interaction
    in the graphical editor and waits for the user to click a placement point.
    Verified live: the call returns immediately and raised no modal, so it is
    safe unattended; if one ever returns EplanBlockedByDialog, use
    eplan_list_dialogs / eplan_click_dialog_button (see module docstring).

    Two addressing styles are used in practice. The GUI ribbon overwhelmingly
    uses the function-definition style, e.g.
        XEGActionInsertSymRef /FctDefTag:1302.1.1 /Cursor:ENDTERMINAL
    while the symbol-library style addresses a symbol directly via
        /SymbolLibName /SymbolId /VariantId

    Args:
        symbol_lib_name: Name of the symbol library containing the symbol
        symbol_id: Number of the symbol to insert
        variant_id: Number of the symbol variant, if the symbol has one
        fct_def_tag: Function definition tag identifying the symbol to insert
            (e.g. "1302.1.1", "10.1.1")
        placement_mode: Placement type of the symbol; valid values depend on the
            DocumentType. Passed through as the /Placementmode key.
        symbol_type: Symbol type identifier used to find the symbol
        custom_symbols: Name of the setting holding the identifiers of a
            user-created symbol, e.g. "XSbGui.CustomSymbols.CustomSymbol". If
            set, the custom symbol is used and symbol_lib_name / symbol_id /
            variant_id are ignored.
        cursor: Cursor / placement helper mode. Observed in MFTools.xml, not in
            the official docs. Values seen: PARTDEFPOINT, ENDTERMINAL,
            ENDTERMINALBOTHSIDE, WIRINGDEFINITION, DIAGONALCONNETION (sic -
            EPLAN's own spelling in MFTools.xml).
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XEGActionInsertSymRef",
        SymbolLibName=symbol_lib_name,
        SymbolId=symbol_id,
        VariantId=variant_id,
        FctDefTag=fct_def_tag,
        Placementmode=placement_mode,
        SymbolType=symbol_type,
        CustomSymbols=custom_symbols,
        Cursor=cursor
    )
    return manager.execute_action(action)


def select_device(
    project_name: str = None,
    mode: str = None,
    keep_swapped_conn_point_information: bool = None
) -> dict:
    """
    Select a device for existing objects, or update their device information.
    The affected object can be a project, function or connection.
    Action: XPamsDeviceSelectionAction

    INTERACTIVE: this opens EPLAN's device selection
    interaction and waits for the user to pick a device. QuietMode suppresses
    dialogs but does NOT cancel this interaction. Unattended, on
    EplanBlockedByDialog call eplan_list_dialogs / eplan_click_dialog_button
    (see module docstring).

    Args:
        project_name: Full path of the project (optional). If the project is not
            open, the action opens it and closes it again automatically. If
            omitted, the selected project is used when called from the GUI
            (script or ribbon bar); from the Windows command line this must be
            set or ProjectAction must be run first.
        mode: "selectDevice" (default) selects a new device for the existing
            objects, deleting and reassigning all device data including part
            reference data. "updateDevice" updates only the device data of the
            existing parts, keeping the part numbers and part reference data.
        keep_swapped_conn_point_information: Keep swapped connection point
            designations / wire colors relative to the order in the function
            templates. Only effective if all connection point designations or
            wire colors match as a set.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XPamsDeviceSelectionAction",
        ProjectName=project_name,
        Mode=mode,
        KeepSwappedConnPointInformation=keep_swapped_conn_point_information
    )
    return manager.execute_action(action)
