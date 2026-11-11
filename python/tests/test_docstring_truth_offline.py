"""
Guards against docstrings that tell the model the server is less capable than
it is.

Background. Before the message-tree capture landed, several wrappers honestly
documented that EPLAN's error text was unreachable and that the user had to go
read EPLAN's own message window. The capture then landed and those passages
became not merely stale but harmful: they steer the model away from data that
is already sitting in the result it was handed. Measured 2026-09-03 on EPLAN
2027.0.1, `projectmanagement /TYPE:READPROJECTINFO` with PROJECTNAME omitted --
the exact case one of those passages described as silently swallowed -- returns

    {"success": false, "eplanMessages": ["No file found. (Parameter 'FILENAME')"]}

So this module pins the negative: no wrapper docstring may claim diagnostics
are unavailable, and no docstring may name a result field that does not exist.

Whitespace normalisation is the point, not a detail. The phrases being banned
are wrapped across source lines inside triple-quoted strings, so each carries a
newline plus indentation in the middle of it. A naive `phrase in docstring`
check passes vacuously and would never have caught the passages that motivated
this file.

Offline: imports the wrapper modules but never connects to EPLAN.
"""

import inspect
import re

import pytest

from mcp_server.api.actions import (  # noqa: F401
    addons,
    backup,
    cabinet,
    catalog,
    data_exchange,
    devicelist,
    discovery,
    e3d,
    export_,
    import_,
    interaction,
    labels,
    layers,
    live,
    macros,
    parts,
    partsmanagement,
    planning,
    plc,
    print_,
    production,
    project,
    properties,
    renumber,
    reports,
    ribbon,
    scripted,
    scripts,
    search,
    settings,
    translate,
)

MODULES = [
    addons, backup, cabinet, catalog, data_exchange, devicelist, discovery,
    e3d, export_, import_, interaction, labels, layers, live, macros, parts,
    partsmanagement, planning, plc, print_, production, project, properties,
    renumber, reports, ribbon, scripted, scripts, search, settings, translate,
]

# Claims that were true before the capture shipped and are now misleading.
# Each is matched against whitespace-normalised text, so line wrapping inside a
# docstring cannot hide it.
BANNED_CLAIMS = [
    "no diagnostic detail available here",
    "check EPLAN's message window directly",
    "swallows that exception silently",
    "no error detail anywhere in this MCP",
]

# Deliberately NOT checked here: whether a docstring names a result field that
# exists. It was tried and removed. Wrappers legitimately document their own
# return shapes ("id", "categories", "tabs", "errors"), and quoted strings in a
# docstring are as often enum VALUES as field names - "SYSTEMPARTSTOPROJECT",
# min_level="Error". Every pattern narrow enough to avoid those missed real
# drift, and every pattern wide enough to catch drift flagged correct
# docstrings. A test that cries wolf gets muted, and a muted test is worse than
# an absent one, so the field-name guard is left out until there is a
# non-heuristic way to do it (a declared result schema would be one).


def _normalise(text):
    """Collapse every run of whitespace, so wrapped phrases match."""
    return re.sub(r"\s+", " ", text or "")


def _public_wrappers():
    """(module_name, func_name, docstring) for every public wrapper."""
    for mod in MODULES:
        for name, obj in vars(mod).items():
            if name.startswith("_") or not inspect.isfunction(obj):
                continue
            if obj.__module__ != mod.__name__:
                continue  # re-exported helper, belongs to its own module
            yield mod.__name__.rsplit(".", 1)[-1], name, obj.__doc__ or ""


ALL_WRAPPERS = sorted(_public_wrappers())


def test_wrapper_discovery_found_something():
    """A refactor that empties the parametrisation must fail loudly, not pass."""
    assert len(ALL_WRAPPERS) > 100, (
        "expected the full wrapper surface, found %d - the discovery in this "
        "file has stopped working and every assertion below is now vacuous"
        % len(ALL_WRAPPERS)
    )


@pytest.mark.parametrize("mod,name,doc", ALL_WRAPPERS, ids=lambda v: str(v))
def test_no_docstring_claims_diagnostics_are_unavailable(mod, name, doc):
    flat = _normalise(doc)
    for claim in BANNED_CLAIMS:
        assert claim not in flat, (
            "%s.%s says %r. EPLAN's own text now arrives in the result's "
            "eplanMessages field (measured 2026-09-03, EPLAN 2027.0.1), so "
            "this steers the model off data it already has. Point it at "
            "eplanMessages instead." % (mod, name, claim)
        )


def test_the_repaired_wrappers_point_at_eplanmessages():
    """
    The positive half of the same guard.

    Banning the stale phrasing is not enough on its own - a future edit could
    delete the misleading sentence and leave nothing in its place, which passes
    the ban while telling the model nothing. These four are the wrappers whose
    docstrings were repaired because a measured failure of theirs is recoverable
    from eplanMessages, so each must actually say so.
    """
    expected = {
        (project, "project_management"),
        (project, "upgrade_projects"),
        (project, "synchronize_project"),
    }
    for mod, func_name in expected:
        doc = _normalise(getattr(mod, func_name).__doc__)
        assert "eplanMessages" in doc, (
            "%s.%s no longer mentions eplanMessages. Its documented failure "
            "mode is recoverable from that field (measured 2026-09-03); if the "
            "guidance is removed the model is back to guessing."
            % (mod.__name__.rsplit(".", 1)[-1], func_name)
        )


def test_pdf_export_wrappers_point_at_the_scheme_settings_node():
    """
    The PDF export wrappers are deliberately NOT in the list above.

    Their failure is the opposite shape: success:true with the output written
    somewhere else, and nothing in eplanMessages at all, because EPLAN did not
    consider it an error. The recovery route is the settings tree - which scheme
    EPLAN falls back to is readable at USER.PDFExportGUI.SCHEMAS.LastUsed
    (measured 2026-09-03: a site-specific scheme, name redacted - it is a 
    client's). Pointing these docstrings at
    eplanMessages would be actively wrong, so what is pinned is the node.
    """
    for func_name in ("export_pdf_project", "export_pdf_pages"):
        doc = _normalise(getattr(export_, func_name).__doc__)
        assert "USER.PDFExportGUI.SCHEMAS" in doc, (
            "export_.%s no longer names the settings node. With export_scheme "
            "omitted this wrapper can write a different filename and still "
            "report success, and the fallback scheme is only discoverable "
            "there." % func_name
        )
        assert "export_scheme" in doc


def test_banned_claims_would_actually_match_a_wrapped_docstring():
    """
    Pins the normalisation itself.

    Without it, a claim wrapped across source lines slips through and this
    whole module reports green while the defect it exists to catch sits in the
    tree. That is what happened to the passages this file was written for.
    """
    wrapped = (
        "If success is false, there is no\n"
        "        diagnostic detail available here or from eplan_status; check "
        "EPLAN's\n        message window directly for the reason."
    )
    assert "no diagnostic detail available here" not in wrapped
    assert "no diagnostic detail available here" in _normalise(wrapped)
