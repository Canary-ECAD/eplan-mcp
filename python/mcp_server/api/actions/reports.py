"""
Reports and evaluations actions.
Complete implementation with all documented parameters.
"""

from typing import List, Optional
from ._base import _get_connected_manager, _build_action, _quote_param


def update_reports(
    project_name: str = None,
    page_name: str = None,
    page_names: List[str] = None,
    page_identifiers: List[str] = None,
    use_page_filter: bool = False,
    page_filter_name: str = None
) -> dict:
    """
    Update project reports/evaluations.
    Action: reports

    Live-verified 2026-09-04: passing only use_page_filter/page_filter_name
    (no page_name/page_names/page_identifiers) left TYPE="PROJECT", where the
    action documents PAGEFILTERNAME/PAGENAMEn/SELn as "only effective with
    the PAGES ... value[s] of the TYPE parameter" - so the filter was silently
    dropped and the whole project's reports were updated instead. Audit #42
    item 3.

    Args:
        project_name: Project path (optional)
        page_name: Specific page to update (its report will be updated)
        page_names: List of page names
        page_identifiers: List of page identifiers (SELn)
        use_page_filter: Use active page filter. Selects TYPE="PAGES" on its
            own, same as page_filter_name.
        page_filter_name: Name of specific page filter. Selects TYPE="PAGES"
            on its own, same as use_page_filter.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    # Determine type based on parameters. Any of these implies a page-scoped
    # update - the filter arguments are as much a page selector as an
    # explicit page_name, and EPLAN ignores them under TYPE="PROJECT".
    report_type = "PROJECT"
    if (page_name or page_names or page_identifiers
            or use_page_filter or page_filter_name):
        report_type = "PAGES"

    parts = ["reports", f"/TYPE:{report_type}"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if page_name:
        parts.append(_quote_param("PAGENAME", page_name))
    if use_page_filter:
        parts.append("/USEPAGEFILTER:1")
    if page_filter_name:
        parts.append(_quote_param("PAGEFILTERNAME", page_filter_name))

    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    if page_identifiers:
        for i, sel in enumerate(page_identifiers, 1):
            parts.append(f"/SEL{i}:{sel}")

    return manager.execute_action(" ".join(parts))


def update_model_view_pages(
    project_name: str = None,
    page_name: str = None,
    page_names: List[str] = None,
    page_identifiers: List[str] = None,
    use_page_filter: bool = False,
    page_filter_name: str = None
) -> dict:
    """
    Update model views on given pages.
    Action: reports

    Args:
        project_name: Project path (optional)
        page_name: Specific page to update
        page_names: List of page names
        page_identifiers: List of page identifiers
        use_page_filter: Use active page filter
        page_filter_name: Name of specific page filter
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["reports", "/TYPE:UPDATEMODELVIEWPAGES"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if page_name:
        parts.append(_quote_param("PAGENAME", page_name))
    if use_page_filter:
        parts.append("/USEPAGEFILTER:1")
    if page_filter_name:
        parts.append(_quote_param("PAGEFILTERNAME", page_filter_name))

    if page_names:
        for i, page in enumerate(page_names, 1):
            parts.append(_quote_param(f"PAGENAME{i}", page))

    if page_identifiers:
        for i, sel in enumerate(page_identifiers, 1):
            parts.append(f"/SEL{i}:{sel}")

    return manager.execute_action(" ".join(parts))


def create_model_views(
    project_name: str = None,
    templates: List[str] = None,
    replace_existing: bool = False
) -> dict:
    """
    Create model views.
    Action: reports

    Args:
        project_name: Project path (optional)
        templates: List of template names
        replace_existing: Replace existing model views
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["reports", "/TYPE:CREATEMODELVIEWS"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if replace_existing:
        parts.append("/REPLACEEXISTING:1")

    if templates:
        for i, t in enumerate(templates, 1):
            parts.append(_quote_param(f"TEMPLATE{i}", t))

    return manager.execute_action(" ".join(parts))


def create_copper_unfolds(
    project_name: str = None,
    templates: List[str] = None,
    replace_existing: bool = False
) -> dict:
    """
    Create copper unfolds.
    Action: reports

    Args:
        project_name: Project path (optional)
        templates: List of template names
        replace_existing: Replace existing copper unfolds
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["reports", "/TYPE:CREATECOPPERUNFOLDS"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if replace_existing:
        parts.append("/REPLACEEXISTING:1")

    if templates:
        for i, t in enumerate(templates, 1):
            parts.append(_quote_param(f"TEMPLATE{i}", t))

    return manager.execute_action(" ".join(parts))


def create_drilling_views(
    project_name: str = None,
    templates: List[str] = None,
    replace_existing: bool = False
) -> dict:
    """
    Create drilling views.
    Action: reports

    Args:
        project_name: Project path (optional)
        templates: List of template names
        replace_existing: Replace existing drilling views
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    parts = ["reports", "/TYPE:CREATEDRILLINGVIEWS"]

    if project_name:
        parts.append(_quote_param("PROJECTNAME", project_name))
    if replace_existing:
        parts.append("/REPLACEEXISTING:1")

    if templates:
        for i, t in enumerate(templates, 1):
            parts.append(_quote_param(f"TEMPLATE{i}", t))

    return manager.execute_action(" ".join(parts))
