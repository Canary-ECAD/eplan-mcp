"""
Check/verify actions.
"""

from ._base import _get_connected_manager, _build_action


def check_project(
    project_name: str = None,
    verification_scheme: str = None,
    verify_completed_only: bool = False
) -> dict:
    """
    Check/verify a project.
    Action: check

    Args:
        project_name: Project path (optional)
        verification_scheme: Verification scheme name
        verify_completed_only: Check completed messages only
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "check",
        TYPE="PROJECT",
        PROJECTNAME=project_name,
        VERIFICATIONSCHEME=verification_scheme,
        VERIFYCOMPLETEDONLY=verify_completed_only
    )
    return manager.execute_action(action)


def check_pages(
    page_name: str = None,
    project_name: str = None,
    verification_scheme: str = None,
    use_page_filter: bool = False
) -> dict:
    """
    Check specific pages.
    Action: check
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "check",
        TYPE="PAGES",
        PAGENAME=page_name,
        PROJECTNAME=project_name,
        VERIFICATIONSCHEME=verification_scheme,
        USEPAGEFILTER=use_page_filter
    )
    return manager.execute_action(action)


def check_parts(
    verification_scheme: str = None,
    verify_completed_only: bool = False
) -> dict:
    """
    Check parts in the database.
    Action: check
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "check",
        TYPE="PARTS",
        VERIFICATIONSCHEME=verification_scheme,
        VERIFYCOMPLETEDONLY=verify_completed_only
    )
    return manager.execute_action(action)
