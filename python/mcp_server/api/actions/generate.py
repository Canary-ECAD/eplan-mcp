"""
Generate actions (connections, cables).
Complete implementation with all documented parameters.
"""

from typing import List, Optional
from ._base import _get_connected_manager, _build_action, _quote_param


def generate_connections(
    project_name: str = None,
    page_name: str = None,
    page_names: List[str] = None,
    page_identifiers: List[str] = None,
    rebuild_all: bool = False,
    use_page_filter: bool = False,
    page_filter_name: str = None
) -> dict:
    """
    Generate connections in project.
    Action: generate

    Args:
        project_name: Project path (optional)
        page_name: Specific page (optional)
        page_names: List of page names (e.g., ["=AP+ST1/2", "=AP+ST1/4"])
        page_identifiers: List of page identifiers from StorableObject.ToStringIdentifier()
        rebuild_all: Rebuild all connections vs update only
        use_page_filter: Use active page filter
        page_filter_name: Name of specific page filter to use
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["generate", "/TYPE:CONNECTIONS"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if page_name:
        parts.append(_quote_param("PAGENAME", page_name))
    if rebuild_all:
        parts.append("/REBUILDALLCONNECTIONS:1")
    if use_page_filter:
        parts.append("/USEPAGEFILTER:1")
    if page_filter_name:
        parts.append(_quote_param("PAGEFILTERNAME", page_filter_name))

    # Multiple page names
    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    # Page identifiers (SELn)
    if page_identifiers:
        for i, sel in enumerate(page_identifiers, 1):
            parts.append(f"/SEL{i}:{sel}")

    return manager.execute_action(" ".join(parts))


def generate_cables(
    project_name: str = None,
    creation_scheme: str = None,
    numbering_scheme: str = None,
    autoselect_scheme: str = None,
    keep_old_names: bool = True,
    start_value: int = 1,
    step_value: int = 1,
    only_auto_cables: bool = True
) -> dict:
    """
    Generate cables in project.
    Action: generate

    Args:
        project_name: Project path (optional)
        creation_scheme: Cable creation scheme
        numbering_scheme: Cable numbering scheme
        autoselect_scheme: Auto cable selection scheme
        keep_old_names: Preserve existing cable names
        start_value: Start value for DT counter
        step_value: Increment value
        only_auto_cables: Only select for auto cables
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "generate",
        TYPE="CABLES",
        PROJECTNAME=project_name,
        CREATIONSCHEME=creation_scheme,
        NUMBERINGSCHEME=numbering_scheme,
        AUTOSELECTSCHEME=autoselect_scheme,
        KEEPOLDNAMES=keep_old_names,
        STARTVALUE=start_value,
        STEPVALUE=step_value,
        ONLYAUTOCABLES=only_auto_cables
    )
    return manager.execute_action(action)
