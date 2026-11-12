"""
Preplanning / detail engineering actions.

These bridge EPLAN Preplanning (planning objects, segments) and the detailed
engineering in the schematic: they push planning data down into the placed
macros, functions and pipe definitions.
"""

from ._base import _get_connected_manager, _build_action


def update_detail_engineering(
    project_name: str = None,
    update_macros: bool = None,
    update_identifier: bool = None,
    update_placeholder: bool = None,
    update_pipedata: bool = None,
    update_parts: bool = None
) -> dict:
    """
    NOT VERIFIED on the reference machine - read the block below before use.
    Update the detail engineering for the selected planning objects.
    ======================================================================
    !!! NOT VERIFIED - the live behaviour of this wrapper could not be
    tested on the reference machine (EPLAN Electric P8 2027.0.1,
    2026-09-02/03). Read this before relying on it. !!!
    ======================================================================

    The EPLAN action was executed and every call FAILED with a message of the
    form:
        "...action ... of the PlanningLog module has failed"

    This is a MISSING FIXTURE, not a proven licence limit. The Preplanning
    module IS present on the reference machine and ActionManager.FindAction
    resolves XPlaUpdateDetailAction (module PlanningLog). The failures
    happened because no available project contains any preplanning objects,
    so the action had nothing to operate on. Note that resolving is in
    general NOT proof of a licence either - module licensing is enforced at
    run time - but here the blocker observed was the absent test data, and no
    licence limit was demonstrated one way or the other.

    To verify: retest against a project that actually contains preplanning
    data, with planning objects selected in the preplanning navigator, and
    confirm the detail engineering is updated.

    What IS covered: the command-string construction (parameter names, exact
    casing, bool rendering, quoting, omission of None) is exercised offline by
    tests/test_new_actions_offline.py. Only the live EPLAN behaviour is
    unverified.
    ======================================================================

    Action: XPlaUpdateDetailAction

    Operates on the planning objects currently selected in the preplanning
    navigator. All update flags default to off (0) in EPLAN, so at least one of
    them should normally be set to True for the call to do anything.

    Args:
        project_name: Full path to the project to be updated (optional)
        update_macros: Remove and re-place the macros related to the planning
            object
        update_identifier: Write the structure identifiers, symbolic addresses
            and pipe names to the functions or pipe definitions
        update_placeholder: Update the placeholder records from macros related
            to the planning object
        update_pipedata: Write the pipe class and substance to the pipe
            definition points and the related connections and functions
        update_parts: Synchronize the pre-planning parts with the parts in the
            detailed planning. If True, the part information at the main
            functions in the detailed planning is deleted and replaced with the
            part information of the assigned segments.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "XPlaUpdateDetailAction",
        PROJECTNAME=project_name,
        UpdateMacros=update_macros,
        UpdateIdentifier=update_identifier,
        UpdatePlaceholder=update_placeholder,
        UpdatePipedata=update_pipedata,
        UpdateParts=update_parts
    )
    return manager.execute_action(action)
