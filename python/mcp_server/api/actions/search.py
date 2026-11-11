"""
Search actions.
Complete implementation with all documented parameters.
"""

from typing import Optional
from ._base import _get_connected_manager, _build_action


def search_devices(
    search_item: str,
    project_name: str = None,
    case_sensitive: bool = False,
    whole_text: bool = False
) -> dict:
    """
    Search for devices in project.
    Action: search

    Args:
        search_item: Text to search for
        project_name: Project path (optional)
        case_sensitive: Match case
        whole_text: Find whole texts only
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "search",
        TYPE="DEVICETAG",
        SEARCHITEM=search_item,
        PROJECTNAME=project_name,
        CASESENSITIVE=case_sensitive,
        WHOLETEXT=whole_text
    )
    return manager.execute_action(action)


def search_text(
    search_item: str,
    project_name: str = None,
    case_sensitive: bool = False,
    whole_text: bool = False,
    logic_pages: bool = True,
    graphic_pages: bool = True,
    evaluation_pages: bool = True,
    not_placed_functions: bool = False,
    filter_scheme: str = None
) -> dict:
    """
    Search for text in project.
    Action: search

    Args:
        search_item: Text to search for
        project_name: Project path (optional)
        case_sensitive: Match case
        whole_text: Find whole texts only
        logic_pages: Search on logic pages
        graphic_pages: Search on graphical pages
        evaluation_pages: Search on report pages
        not_placed_functions: Search in unplaced functions
        filter_scheme: Function filter scheme name
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "search",
        TYPE="TEXTS",
        SEARCHITEM=search_item,
        PROJECTNAME=project_name,
        CASESENSITIVE=case_sensitive,
        WHOLETEXT=whole_text,
        LOGICPAGES=logic_pages,
        GRAPHICPAGES=graphic_pages,
        EVALUATIONPAGES=evaluation_pages,
        NOTPLACEDFUNCTIONS=not_placed_functions,
        FILTERSCHEME=filter_scheme
    )
    return manager.execute_action(action)


def search_all_properties(
    search_item: str,
    project_name: str = None,
    case_sensitive: bool = False
) -> dict:
    """
    Search through all properties in project.
    Action: search

    Args:
        search_item: Text to search for
        project_name: Project path (optional)
        case_sensitive: Match case
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "search",
        TYPE="ALLPROPERTIES",
        SEARCHITEM=search_item,
        PROJECTNAME=project_name,
        CASESENSITIVE=case_sensitive
    )
    return manager.execute_action(action)


def search_page_data(
    search_item: str,
    project_name: str = None,
    case_sensitive: bool = False,
    whole_text: bool = False,
    logic_pages: bool = True,
    graphic_pages: bool = True,
    evaluation_pages: bool = True,
    not_placed_functions: bool = False,
    filter_scheme: str = None
) -> dict:
    """
    Search through page data.
    Action: search

    Args:
        search_item: Text to search for
        project_name: Project path (optional)
        case_sensitive: Match case
        whole_text: Find whole texts only
        logic_pages: Search on logic pages
        graphic_pages: Search on graphical pages
        evaluation_pages: Search on report pages
        not_placed_functions: Search in unplaced functions
        filter_scheme: Function filter scheme name
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "search",
        TYPE="PAGEDATA",
        SEARCHITEM=search_item,
        PROJECTNAME=project_name,
        CASESENSITIVE=case_sensitive,
        WHOLETEXT=whole_text,
        LOGICPAGES=logic_pages,
        GRAPHICPAGES=graphic_pages,
        EVALUATIONPAGES=evaluation_pages,
        NOTPLACEDFUNCTIONS=not_placed_functions,
        FILTERSCHEME=filter_scheme
    )
    return manager.execute_action(action)


def search_project_data(
    search_item: str,
    project_name: str = None,
    case_sensitive: bool = False,
    whole_text: bool = False
) -> dict:
    """
    Search through project data.
    Action: search

    Args:
        search_item: Text to search for
        project_name: Project path (optional)
        case_sensitive: Match case
        whole_text: Find whole texts only
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "search",
        TYPE="PROJECTDATA",
        SEARCHITEM=search_item,
        PROJECTNAME=project_name,
        CASESENSITIVE=case_sensitive,
        WHOLETEXT=whole_text
    )
    return manager.execute_action(action)
