"""
Print actions.
"""

from ._base import _get_connected_manager, _build_action


def print_project(
    project_name: str = None,
    printer_name: str = None,
    copies: int = 1,
    collate: bool = True,
    reverse: bool = False,
    destination_file: str = None
) -> dict:
    """
    Print a project.
    Action: print

    Args:
        project_name: Project path (optional)
        printer_name: Printer name (optional, uses default)
        copies: Number of copies
        collate: Sorted order
        reverse: Reverse order
        destination_file: Output to file instead of printer
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "print",
        TYPE="PROJECT",
        PROJECTNAME=project_name,
        PRINTERNAME=printer_name,
        NUMBER=copies,
        PRINTCOLLATE=collate,
        PRINTREVERSE=reverse,
        DESTINATIONFILE=destination_file
    )
    return manager.execute_action(action)


def print_pages(
    page_name: str = None,
    project_name: str = None,
    printer_name: str = None,
    copies: int = 1,
    use_page_filter: bool = False,
    print_changed_only: bool = False
) -> dict:
    """
    Print specific pages.
    Action: print

    Args:
        page_name: Page name to print (optional)
        project_name: Project path (optional)
        printer_name: Printer name
        copies: Number of copies
        use_page_filter: Use active page filter
        print_changed_only: Print only changed pages
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "print",
        TYPE="PAGES",
        PAGENAME=page_name,
        PROJECTNAME=project_name,
        PRINTERNAME=printer_name,
        NUMBER=copies,
        USEPAGEFILTER=use_page_filter,
        PRINTCHANGEDPAGES=print_changed_only
    )
    return manager.execute_action(action)
