"""Offline tests for EPLAN_MCP_MODE=discovery.

Discovery mode exists purely to cut the per-request cost of the tool
definitions, so the size claim is asserted here (computed, not hard-coded)
alongside the wiring: full mode must be unchanged, discovery mode must publish
only the core + meta set, and the three meta-tools must actually find,
document and dispatch the hidden wrappers.

Everything here runs with EPLAN closed - nothing connects or imports EPLAN.
"""

import asyncio
import json

import pytest


@pytest.fixture(scope="module")
def server():
    import server as srv
    return srv


def _tools(app):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(app.list_tools())
    finally:
        loop.close()


def _names(app):
    return {t.name for t in _tools(app)}


def _definition_chars(app):
    """Same formula the README's measurement uses: name + description + schema."""
    total = 0
    for t in _tools(app):
        schema = t.inputSchema if isinstance(t.inputSchema, dict) else {}
        total += len(t.name) + len(t.description or "") + len(json.dumps(schema))
    return total


@pytest.fixture(scope="module")
def full_app(server):
    app, registry, _ = server.build_app("full")
    return app, registry


@pytest.fixture(scope="module")
def discovery_app(server):
    app, registry, _ = server.build_app("discovery")
    return app, registry


# ---------------------------------------------------------------- mode wiring

def test_default_mode_is_full(server):
    assert server._resolve_mode(None) == "full"
    assert server._resolve_mode("") == "full"
    assert server._resolve_mode("FULL") == "full"
    assert server._resolve_mode("Discovery") == "discovery"


def test_invalid_mode_falls_back_to_full_with_warning(server, capsys):
    assert server._resolve_mode("disco") == "full"
    err = capsys.readouterr().err
    assert "EPLAN_MCP_MODE" in err
    assert "full" in err


def test_invalid_mode_builds_a_full_server(server, capsys):
    app, registry, _ = server.build_app("nonsense")
    capsys.readouterr()
    names = _names(app)
    assert "eplan_export_pdf_project" in names
    assert "eplan_tools_search" not in names
    assert len(names) == len(registry)


# ------------------------------------------------------- registration content

def test_full_mode_publishes_everything_indexed(full_app):
    app, registry = full_app
    names = _names(app)
    # The real no-regression invariant: in full mode every indexed tool is a
    # published MCP tool. A literal count would rot the moment a wrapper lands.
    assert len(names) == len(registry)
    assert names == set(registry.published_names())
    assert not registry.hidden_names()
    # Spot-check the tiers that must survive the refactor.
    for expected in ("eplan_status", "eplan_test", "eplan_list_extensions",
                     "eplan_export_pdf_project", "eplan_action_catalog"):
        assert expected in names


def test_full_mode_has_no_meta_tools(full_app):
    app, _ = full_app
    assert not {n for n in _names(app) if n.startswith("eplan_tools_")}


def test_discovery_mode_publishes_only_core_and_meta(discovery_app, server):
    app, _ = discovery_app
    expected = set(server.DISCOVERY_CORE_TOOLS) | set(server.DISCOVERY_META_TOOLS)
    assert _names(app) == expected
    assert len(expected) == 15


def test_discovery_mode_hides_a_known_wrapper(discovery_app):
    app, registry = discovery_app
    assert "eplan_export_pdf_project" not in _names(app)
    # ...but it is still indexed and callable through the meta-tools.
    assert "eplan_export_pdf_project" in registry
    assert "eplan_export_pdf_project" in registry.hidden_names()


def test_discovery_indexes_everything_full_mode_publishes(full_app, discovery_app):
    _, full_registry = full_app
    _, disc_registry = discovery_app
    # Same tools indexed either way, plus the three discovery-only meta-tools.
    assert set(full_registry.names()) <= set(disc_registry.names())
    extra = set(disc_registry.names()) - set(full_registry.names())
    assert extra == {"eplan_tools_search", "eplan_tools_describe", "eplan_tools_call"}


# ------------------------------------------------------------- the size claim

def test_discovery_mode_saves_at_least_80_percent(full_app, discovery_app):
    full_chars = _definition_chars(full_app[0])
    disc_chars = _definition_chars(discovery_app[0])
    saved = 1.0 - (disc_chars / full_chars)
    assert saved >= 0.80, (
        "discovery mode only saves %.1f%% of tool-definition characters "
        "(%d -> %d); the README claim needs updating"
        % (saved * 100, full_chars, disc_chars))


# ------------------------------------------------------------- tools_search

def test_search_finds_tool_by_name(discovery_app):
    _, registry = discovery_app
    res = registry.search("export_pdf_project")
    assert res["success"] is True
    assert "eplan_export_pdf_project" in [t["name"] for t in res["tools"]]


def test_search_finds_tool_by_docstring_word(discovery_app):
    _, registry = discovery_app
    res = registry.search("grayscale")
    assert "eplan_export_pdf_project" in [t["name"] for t in res["tools"]]


def test_search_returns_names_not_schemas(discovery_app):
    _, registry = discovery_app
    row = next(t for t in registry.search("export_pdf_project")["tools"]
               if t["name"] == "eplan_export_pdf_project")
    assert "export_file" in row["params"]
    assert all(isinstance(p, str) for p in row["params"])
    assert row["summary"]
    # A full schema here would rebuild the very problem discovery mode solves.
    assert "schema" not in row and "doc" not in row


def test_search_total_is_true_count_when_truncated(discovery_app):
    _, registry = discovery_app
    everything = registry.search("export", limit=200)
    truncated = registry.search("export", limit=3)
    assert truncated["total_matches"] == everything["total_matches"]
    assert truncated["total_matches"] > 3
    assert len(truncated["tools"]) == 3
    assert truncated["truncated"] is True
    assert everything["truncated"] is False


def test_search_without_query_returns_grouped_overview(discovery_app):
    _, registry = discovery_app
    res = registry.search()
    assert res["query"] is None
    assert "tools" not in res
    assert res["total_tools"] == len(registry)
    groups = res["groups"]
    assert len(groups) > 1
    assert sum(g["count"] for g in groups.values()) == len(registry)
    assert "eplan_export_pdf_project" in groups["export_"]["tools"]


def test_search_miss_offers_near_matches(discovery_app):
    _, registry = discovery_app
    res = registry.search("expotr_pdf_projekt")
    assert res["total_matches"] == 0
    assert res["did_you_mean"]


# ------------------------------------------------------------ tools_describe

def test_describe_returns_full_docstring(discovery_app):
    _, registry = discovery_app
    res = registry.describe("eplan_export_pdf_project")
    assert res["success"] is True
    tool = res["tools"][0]
    assert tool["name"] == "eplan_export_pdf_project"
    assert "Action: export" in tool["doc"]
    assert "black_white" in tool["doc"]
    assert tool["signature"].startswith("eplan_export_pdf_project(")
    required = [p["name"] for p in tool["parameters"] if p["required"]]
    assert required == ["export_file"]


def test_describe_accepts_a_list_and_a_bare_name(discovery_app):
    _, registry = discovery_app
    res = registry.describe(["eplan_export_pdf_project", "backup_project"])
    assert [t["name"] for t in res["tools"]] == [
        "eplan_export_pdf_project", "eplan_backup_project"]
    assert res["not_found"] == []


def test_describe_unknown_name_yields_near_matches(discovery_app):
    _, registry = discovery_app
    res = registry.describe("eplan_export_pdf_projekt")
    assert res["success"] is False
    assert res["tools"] == []
    miss = res["not_found"][0]
    assert miss["name"] == "eplan_export_pdf_projekt"
    assert "eplan_export_pdf_project" in miss["did_you_mean"]


# ---------------------------------------------------------------- tools_call

def test_call_dispatches_to_the_real_function(discovery_app, monkeypatch):
    _, registry = discovery_app
    import api.actions as actions

    seen = {}

    def fake_export_pdf_project(export_file: str, project_name: str = None) -> dict:
        """Fake."""
        seen["args"] = (export_file, project_name)
        return {"success": True, "faked": True}

    monkeypatch.setattr(actions, "export_pdf_project", fake_export_pdf_project)

    res = registry.call("eplan_export_pdf_project",
                        {"export_file": "C:/out.pdf", "project_name": "Demo"})
    assert res == {"success": True, "faked": True}
    assert seen["args"] == ("C:/out.pdf", "Demo")


def test_call_accepts_a_bare_name_and_a_json_string(discovery_app, monkeypatch):
    _, registry = discovery_app
    import api.actions as actions

    def fake(export_file: str) -> dict:
        """Fake."""
        return {"success": True, "path": export_file}

    monkeypatch.setattr(actions, "export_pdf_project", fake)
    res = registry.call("export_pdf_project", '{"export_file": "C:/a.pdf"}')
    assert res == {"success": True, "path": "C:/a.pdf"}


def test_call_rejects_unknown_tool_name(discovery_app):
    _, registry = discovery_app
    res = registry.call("eplan_export_pdf_projekt", {})
    assert res["success"] is False
    assert "Unknown tool" in res["error"]
    assert "eplan_export_pdf_project" in res["did_you_mean"]


def test_call_rejects_unknown_argument_naming_the_valid_ones(discovery_app):
    _, registry = discovery_app
    res = registry.call("eplan_export_pdf_project",
                        {"export_file": "C:/a.pdf", "exprot_scheme": "x"})
    assert res["success"] is False
    assert "exprot_scheme" in res["error"]
    assert "export_scheme" in res["valid_parameters"]
    assert "export_file" in res["valid_parameters"]
    assert "export_scheme" in res["did_you_mean"]["exprot_scheme"]


def test_call_reports_missing_required_argument(discovery_app):
    _, registry = discovery_app
    res = registry.call("eplan_export_pdf_project", {})
    assert res["success"] is False
    assert "export_file" in res["error"]
    assert res["required_parameters"] == ["export_file"]


def test_call_rejects_non_object_arguments(discovery_app):
    _, registry = discovery_app
    res = registry.call("eplan_export_pdf_project", ["C:/a.pdf"])
    assert res["success"] is False
    assert "arguments must be an object" in res["error"]


def test_call_wraps_a_raising_tool_instead_of_propagating(discovery_app, monkeypatch):
    _, registry = discovery_app
    import api.actions as actions

    def boom(export_file: str) -> dict:
        """Fake."""
        raise RuntimeError("kaboom")

    monkeypatch.setattr(actions, "export_pdf_project", boom)
    res = registry.call("eplan_export_pdf_project", {"export_file": "C:/a.pdf"})
    assert res == {"success": False, "tool": "eplan_export_pdf_project",
                   "error": "kaboom"}


def test_call_decodes_json_string_returning_tools(discovery_app, server):
    """The server-level core tools return a JSON string, not a dict."""
    _, registry = discovery_app
    res = registry.call("eplan_list_extensions")
    assert isinstance(res, dict)
    assert "extensions" in res


# ------------------------------------------------------------- extensions

def test_extension_tools_are_searchable_in_discovery_mode(server, tmp_path):
    (tmp_path / "disc_ext.py").write_text(
        'TOOL_PREFIX = "dsc_"\n'
        '__all__ = ["special_widget_probe"]\n'
        'def special_widget_probe(target: str = None) -> dict:\n'
        '    """Probe a flurbulator widget."""\n'
        '    return {"success": True}\n'
    )
    app, registry, loaded = server.build_app("discovery")
    server.load_extensions(str(tmp_path), app=app, registry=registry,
                           mode="discovery")

    # Searchable and callable, but NOT a published MCP tool definition.
    assert "dsc_special_widget_probe" not in _names(app)
    assert "dsc_special_widget_probe" in registry
    hits = [t["name"] for t in registry.search("flurbulator")["tools"]]
    assert hits == ["dsc_special_widget_probe"]
    assert registry.call("dsc_special_widget_probe") == {"success": True}


def test_extension_tools_still_publish_in_full_mode(server, tmp_path):
    (tmp_path / "full_ext.py").write_text(
        'TOOL_PREFIX = "fll_"\n'
        '__all__ = ["another_probe"]\n'
        'def another_probe() -> dict:\n'
        '    """Still published in full mode."""\n'
        '    return {"success": True}\n'
    )
    app, registry, _ = server.build_app("full")
    server.load_extensions(str(tmp_path), app=app, registry=registry, mode="full")
    assert "fll_another_probe" in _names(app)


# ---------------------------------------------------------------------------
# strip_schema_boilerplate
#
# Pydantic auto-generates a "title" for every schema node and a "default": null
# for every optional argument. Neither tells the model anything, and both ship
# on every request (and again on every on-demand schema load in a client that
# defers schemas). Stripping them was measured at 31,268 characters, ~7,800
# tokens, 15.8% of the whole tool payload, with no loss of meaning.
# These pin that it stays lossless AND stays effective.
# ---------------------------------------------------------------------------


def _schema_chars(app):
    return sum(len(json.dumps(getattr(t, "parameters", {}) or {}))
               for t in app._tool_manager._tools.values())


def _nodes(app):
    out = []

    def walk(node):
        if isinstance(node, dict):
            out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for tool in app._tool_manager._tools.values():
        walk(getattr(tool, "parameters", {}) or {})
    return out


def test_strip_removes_every_title_and_null_default(server, monkeypatch):
    monkeypatch.delenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", raising=False)
    nodes = _nodes(server.build_app("full")[0])
    assert not [n for n in nodes if "title" in n], "a schema title survived"
    assert not [n for n in nodes if "default" in n and n["default"] is None],         "a null default survived"


def test_strip_preserves_informative_defaults(server, monkeypatch):
    """0, False and "" are real information - only None may be dropped."""
    monkeypatch.delenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", raising=False)
    kept = [n["default"] for n in _nodes(server.build_app("full")[0]) if "default" in n]
    assert kept, "every default was dropped - the strip is too aggressive"
    assert all(d is not None for d in kept)
    assert any(d is False or d == 0 or d == "" for d in kept),         "expected at least one falsy-but-meaningful default to survive"


def test_strip_saves_a_meaningful_share_of_the_schema_bytes(server, monkeypatch):
    """Guards the measured saving: if FastMCP stops emitting the boilerplate or
    the pass silently breaks, this fails instead of quietly saving nothing."""
    monkeypatch.setenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", "1")
    before = _schema_chars(server.build_app("full")[0])
    monkeypatch.delenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", raising=False)
    after = _schema_chars(server.build_app("full")[0])
    assert after < before
    share = (before - after) / before
    assert share > 0.30, f"expected >30% of schema bytes to be boilerplate, got {share:.1%}"


def test_strip_can_be_disabled(server, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", "1")
    assert [n for n in _nodes(server.build_app("full")[0]) if "title" in n],         "escape hatch did not keep titles"


def test_stripped_tool_behaves_identically_to_unstripped(server, monkeypatch):
    """The safety argument for the strip is that Tool.parameters is serialised
    out to the client but is NOT what validates or dispatches a call (that goes
    through Tool.fn_metadata). So observable behaviour must be identical with
    and without the strip. That equivalence is the real invariant - assert it
    directly rather than guessing at any one error shape.

    Note a PRE-EXISTING FastMCP behaviour this pins down: an unknown argument is
    silently DROPPED, not rejected, in both modes. That is not caused by the
    strip (verified here by comparing the two), but it is why
    catalog.action_run does its own parameter validation instead of trusting
    the schema layer.
    """
    loop = asyncio.new_event_loop()
    try:
        def run(keep_titles):
            if keep_titles:
                monkeypatch.setenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", "1")
            else:
                monkeypatch.delenv("EPLAN_MCP_KEEP_SCHEMA_TITLES", raising=False)
            app, _, _ = server.build_app("full")
            good = loop.run_until_complete(app._tool_manager.call_tool(
                "eplan_action_catalog", {"search": "backup", "limit": 2}))
            unknown = loop.run_until_complete(app._tool_manager.call_tool(
                "eplan_action_catalog", {"no_such_argument": 1}))
            return str(good), str(unknown)

        kept = run(True)
        stripped = run(False)
        assert kept == stripped, "stripping the schema changed observable behaviour"
        assert "backup" in stripped[0], "the tool did not actually run"
    finally:
        loop.close()


def test_prune_does_not_delete_a_parameter_literally_named_title(server):
    """
    Audit #42 item 11. prune() popped "title" from every dict it walked
    without tracking whether that dict was a SCHEMA NODE (where "title" is
    pydantic's auto-generated, safe to drop) or a "properties"/"$defs" MAP
    (where "title" is a parameter/definition NAME - a dict KEY, not a schema
    keyword). A tool parameter literally named `title` had its entire schema
    entry deleted from `properties` while `required` still named it.
    """
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("prune-test")

    @app.tool()
    def rename_page(title: str, page_name: str = "=A1") -> dict:
        """A tool with a parameter that collides with the schema keyword."""
        return {"success": True, "title": title, "page_name": page_name}

    tool = next(iter(app._tool_manager._tools.values()))
    before = tool.parameters
    assert "title" in before["properties"], "test setup: pydantic must have generated it"

    server.strip_schema_boilerplate(app)

    after = tool.parameters
    assert "title" in after["properties"], (
        "the `title` PARAMETER's whole schema was deleted, not just the "
        "auto-generated title KEYWORD inside some node"
    )
    assert after["properties"]["title"].get("type") == "string"
    assert "title" in after.get("required", []), "required must still name it"
    # The actual boilerplate this pass exists to remove must still be gone:
    # the ROOT schema's own auto-generated title, a sibling of "properties",
    # not the parameter living one level down inside it.
    assert "title" not in after
