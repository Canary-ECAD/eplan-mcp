"""
Renumber actions (devices, pages, cables, terminals, connections).
Complete implementation with all documented parameters.
"""

from typing import List, Dict, Optional
from ._base import _get_connected_manager, _build_action, _quote_param


def renumber_devices(
    project_name: str = None,
    start_value: int = 1,
    step_value: int = 1,
    config_scheme: str = None,
    filter_scheme: str = None,
    identifier: str = None,
    use_selection: bool = False,
    post_numerate: bool = True,
    also_numerated_by_plc: bool = False,
    numerate_cables: bool = False
) -> dict:
    """
    Renumber devices in project.
    Action: renumber

    Args:
        project_name: Project path (optional)
        start_value: Start value (default 1)
        step_value: Increment value (default 1)
        config_scheme: Configuration scheme name
        filter_scheme: Filter scheme name
        identifier: Device identifier pattern (e.g., "X*", "V")
        use_selection: Only renumber selected objects
        post_numerate: Only renumber invalid tags with "?" (default True)
        also_numerated_by_plc: Include devices influenced by PLC numbering
        numerate_cables: Also numerate cables with source/target info
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "renumber",
        TYPE="DEVICES",
        PROJECTNAME=project_name,
        STARTVALUE=start_value,
        STEPVALUE=step_value,
        CONFIGSCHEME=config_scheme,
        FILTERSCHEME=filter_scheme,
        IDENTIFIER=identifier,
        USESELECTION=use_selection,
        POSTNUMERATE=post_numerate,
        ALSONUMERATEDBYPLC=also_numerated_by_plc,
        NUMERATECABLES=numerate_cables
    )
    return manager.execute_action(action)


def renumber_pages(
    project_name: str = None,
    start_value: int = 1,
    step_value: int = 1,
    structure_oriented: bool = False,
    keep_interval: bool = False,
    keep_text: bool = False,
    subpages: int = 0,
    use_selection: bool = False
) -> dict:
    """
    Renumber pages in project.
    Action: renumber

    Args:
        project_name: Project path (optional)
        start_value: Start value (default 1)
        step_value: Increment value (default 1)
        structure_oriented: Number per structure identifier
        keep_interval: Retain increments between selected pages
        keep_text: Don't overwrite alphabetic part of page name
        subpages: 0=Retain, 1=ConsecutiveNumbering, 2=ConvertIntoMainPages
        use_selection: Only renumber selected pages
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "renumber",
        TYPE="PAGES",
        PROJECTNAME=project_name,
        STARTVALUE=start_value,
        STEPVALUE=step_value,
        STRUCTUREORIENTED=structure_oriented,
        KEEPINTERVAL=keep_interval,
        KEEPTEXT=keep_text,
        SUBPAGES=subpages,
        USESELECTION=use_selection
    )
    return manager.execute_action(action)


def renumber_cables(
    project_name: str = None,
    start_value: int = 1,
    step_value: int = 1,
    config_scheme: str = None,
    use_selection: bool = False,
    keep_existing: bool = False,
    keep_identifier: bool = False
) -> dict:
    """
    Renumber cables in project.
    Action: renumber

    Args:
        project_name: Project path (optional)
        start_value: Start value (default 1)
        step_value: Increment value (default 1)
        config_scheme: Configuration scheme name
        use_selection: Only renumber selected cables
        keep_existing: Keep existing cable DTs (only renumber new/copied)
        keep_identifier: Keep identifier, only reassign counters
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "renumber",
        TYPE="CABLES",
        PROJECTNAME=project_name,
        STARTVALUE=start_value,
        STEPVALUE=step_value,
        CONFIGSCHEME=config_scheme,
        USESELECTION=use_selection,
        KEEPEXISTING=keep_existing,
        KEEPIDENTIFIER=keep_identifier
    )
    return manager.execute_action(action)


def renumber_terminals(
    project_name: str = None,
    start_value: int = 1,
    step_value: int = 1,
    config_scheme: str = None,
    use_selection: bool = False,
    sequence: int = 0,
    extent: int = 0,
    prefix: str = None,
    suffix: str = None,
    post_numerate: bool = True,
    also_numerated_by_plc: bool = False,
    permit_sort_change: bool = False,
    fill_gaps: bool = False,
    potential_n: int = 0,
    potential_pe: int = 0,
    potential_sh: int = 0,
    multiple_terminals: int = 0,
    keep_alpha: int = 0
) -> dict:
    """
    Renumber terminals in project.
    Action: renumber

    Args:
        project_name: Project path (optional)
        start_value: Start value (default 1)
        step_value: Increment value (default 1)
        config_scheme: Configuration scheme name
        use_selection: Only renumber selected terminals
        sequence: 0=Like sorting, 1=Page oriented, 2=Cable oriented, 3=Level oriented
        extent: 0=Selected only, 1=All selected terminal strips
        prefix: Prefix for terminal designation
        suffix: Suffix for terminal designation
        post_numerate: Only renumber invalid tags with "?" (default True)
        also_numerated_by_plc: Include terminals influenced by PLC numbering
        permit_sort_change: Allow sort change
        fill_gaps: Fill gaps in numbering
        potential_n: N terminals: 0=Ignore, 1=DoNotModify, 2=Renumber
        potential_pe: PE terminals: 0=Ignore, 1=DoNotModify, 2=Renumber
        potential_sh: SH terminals: 0=Ignore, 1=DoNotModify, 2=Renumber
        multiple_terminals: 0=DontModify, 1=NumberSame, 2=NumberIndividually
        keep_alpha: 0=DontModify, 1=KeepAlphaElements, 2=Number
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "renumber",
        TYPE="TERMINALS",
        PROJECTNAME=project_name,
        STARTVALUE=start_value,
        STEPVALUE=step_value,
        CONFIGSCHEME=config_scheme,
        USESELECTION=use_selection,
        SEQUENCE=sequence,
        EXTENT=extent,
        PREFIX=prefix,
        SUFFIX=suffix,
        POSTNUMERATE=post_numerate,
        ALSONUMERATEDBYPLC=also_numerated_by_plc,
        PERMITSORTCHANGE=permit_sort_change,
        FILLGAPS=fill_gaps,
        POTENTIAL_N=potential_n,
        POTENTIAL_PE=potential_pe,
        POTENTIAL_SH=potential_sh,
        MULTIPLETERMINALS=multiple_terminals,
        KEEPALPHA=keep_alpha
    )
    return manager.execute_action(action)


def renumber_connections(
    project_name: str = None,
    config_scheme: str = None,
    use_selection: bool = False,
    groups: Dict[int, dict] = None,
    overwrite: int = 0,
    avoid_identical_designations: int = 0,
    visibility: int = 0,
    mark_as_manual: bool = False
) -> dict:
    """
    Renumber connections in project.
    Action: renumber

    Args:
        project_name: Project path (optional)
        config_scheme: Configuration scheme name
        use_selection: Only renumber selected connections
        groups: Dict of group configurations, e.g.:
                {1: {"start": 1, "step": 1}, 2: {"start": 10, "step": 5}}
        overwrite: 0=All (always overwrite), 1=ExceptManuals, 2=None (never)
        avoid_identical_designations: 0=InProject, 1=InSelection, 2=None, 3=PerRange
        visibility: 0=AllVisible, 1=DoNotModify, 2=OncePerPageAndRange
        mark_as_manual: Mark renumbered connections as "manually set"

    Example:
        renumber_connections(
            config_scheme="ConnectionOriented",
            groups={1: {"start": 1, "step": 1}},
            overwrite=1,
            use_selection=True
        )
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["renumber", "/TYPE:CONNECTIONS"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if config_scheme:
        parts.append(_quote_param("CONFIGSCHEME", config_scheme))
    if use_selection:
        parts.append("/USESELECTION:1")

    # Add group configurations
    if groups:
        for group_num, config in groups.items():
            parts.append(f"/GROUP_{group_num}:{group_num}")
            if "start" in config:
                parts.append(f"/STARTVALUE_{group_num}:{config['start']}")
            if "step" in config:
                parts.append(f"/STEPVALUE_{group_num}:{config['step']}")

    parts.append(f"/OVERWRITE:{overwrite}")
    parts.append(f"/AVOIDIDENTICALDESIGNATIONS:{avoid_identical_designations}")
    parts.append(f"/VISIBILITY:{visibility}")
    parts.append(f"/MARKASMANUAL:{1 if mark_as_manual else 0}")

    return manager.execute_action(" ".join(parts))
