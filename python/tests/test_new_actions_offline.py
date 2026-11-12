"""Offline tests for the newly added typed action wrappers.

What matters about a wrapper is the COMMAND STRING it emits: the action name,
the verbatim parameter casing, which params are dropped, how bools and spaces
render. All of that is decided before EPLAN is ever contacted, so
`_get_connected_manager` is replaced by a stub that hands back a fake manager
recording the command - the same "swap the one boundary function" approach
tests/test_scripted_offline.py and tests/test_live_offline.py use for
`_execute_script`. No EPLAN needed.
"""

import inspect
import json
import os
import re
from types import SimpleNamespace

import pytest

from api.actions import _base, addons, cabinet, catalog, data_exchange, e3d, export_, import_
from api.actions import interaction, planning, project, properties, reports, settings


# The modules whose wrappers this file covers. Each imported
# `_get_connected_manager` into its own namespace, so each needs its own patch.
WRAPPER_MODULES = (export_, import_, e3d, project, addons, cabinet, settings,
                   interaction, planning, properties, reports, data_exchange)

# Same regex tools/validate_actions.py parses docstrings with.
ACTION_RE = re.compile(r"Action:\s*([A-Za-z0-9_]+)")

# /KEY: occurrences in an emitted command line.
KEY_RE = re.compile(r"/([A-Za-z0-9_]+):")

_OFFICIAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "data", "official_actions_2027.json",
)

# Parameter keys that are deliberately NOT in the official docs - the wrappers'
# docstrings say so explicitly (mined from the live install's MFTools.xml).
OBSERVED_ONLY_KEYS = {
    "XGedStartInteractionAction": {"filename", "variant"},
    "XEGActionInsertSymRef": {"Cursor"},
}


@pytest.fixture
def capture(monkeypatch):
    """Patch _get_connected_manager in every wrapper module.

    The fake manager echoes the command back, so a wrapper call reads as
    `fn(...)["command"]`.
    """
    manager = SimpleNamespace(
        execute_action=lambda command, *a, **kw: {"success": True, "command": command}
    )
    for module in WRAPPER_MODULES:
        monkeypatch.setattr(module, "_get_connected_manager", lambda: (manager, None))
    return manager


@pytest.fixture
def disconnected(monkeypatch):
    """Force the real _get_connected_manager down its not-connected branch."""
    fake = SimpleNamespace(connected=False)
    monkeypatch.setattr(_base, "get_manager", lambda *a, **kw: fake)
    monkeypatch.setattr(catalog, "get_manager", lambda *a, **kw: fake)


def cmd(result) -> str:
    """The command string a stubbed wrapper call produced."""
    assert result.get("success") is True, result
    return result["command"]


def keys(command: str):
    return KEY_RE.findall(command)


# ---------------------------------------------------------------------------
# The wrapper table: each entry is (function, minimal-valid kwargs).
# Values are space-free so key extraction stays unambiguous.
# ---------------------------------------------------------------------------

WRAPPERS = [
    (export_.export_to_graphics, {"destination_path": "C:/out"}),
    (e3d.insert_model_view,
     {"layout_space": "LS1", "page_name": "=A1+B1/1", "dx": 100.0, "dy": 50.0}),
    (e3d.export_production_data_ras_center, {}),
    (e3d.export_production_data_smart_mounting, {}),
    (project.run_project_action, {"project_name": "C:/p.elk", "action": "export"}),
    (project.convert_base_projects, {}),
    (addons.load_api_module_net, {}),
    (addons.register_custom_property_editor, {}),
    (cabinet.create_graving_text, {}),
    (cabinet.import_preplanning_data,
     {"import_file": "C:/pp.xlsx", "scheme_name": "config_scheme"}),
    (cabinet.export_segments_template, {"export_file": "C:/segs.xml"}),
    (cabinet.import_segments_template, {"import_file": "C:/segs.xml"}),
    (settings.lock_unlock_all_objects, {}),
    (interaction.start_ged_interaction, {"name": "XMIaInsertMacro"}),
    (interaction.insert_device, {}),
    (interaction.insert_symbol_reference, {}),
    (interaction.select_device, {}),
    (planning.update_detail_engineering, {}),
    (properties.export_user_properties, {"export_file": "C:/out.xml"}),
    (properties.import_user_properties, {"import_file": "C:/in.xml"}),
    (data_exchange.delete_representation_type,
     {"representation_type": 0, "source": "C:/macros/*.ema", "destination": "C:/out"}),
    (data_exchange.import_dc_article_data, {"import_file": "C:/data.edc"}),
]

WRAPPER_IDS = [fn.__name__ for fn, _ in WRAPPERS]

# Wrappers that take no mandatory arguments - a bare call must therefore emit
# (almost) nothing but the action name.
ALL_OPTIONAL = [(fn, kw) for fn, kw in WRAPPERS if not kw]
ALL_OPTIONAL_IDS = [fn.__name__ for fn, _ in ALL_OPTIONAL]


def docstring_action(fn) -> str:
    match = ACTION_RE.search(fn.__doc__ or "")
    assert match, f"{fn.__name__} has no 'Action: <Name>' line in its docstring"
    return match.group(1)


# ---------------------------------------------------------------------------
# 1. The emitted action name must be the one the docstring promises
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", WRAPPERS, ids=WRAPPER_IDS)
def test_emitted_action_matches_docstring(capture, fn, kwargs):
    command = cmd(fn(**kwargs))
    assert command.split()[0] == docstring_action(fn)


@pytest.mark.parametrize("fn,kwargs", WRAPPERS, ids=WRAPPER_IDS)
def test_docstring_documents_every_parameter(fn, kwargs):
    """Each wrapper argument gets a line in the Args: block."""
    doc = fn.__doc__ or ""
    args_block = doc.split("Args:", 1)
    assert len(args_block) == 2, f"{fn.__name__} has no Args: block"
    body = args_block[1]
    for param in inspect.signature(fn).parameters:
        assert re.search(r"^\s*" + re.escape(param) + r"\s*:", body, re.M), \
            f"{fn.__name__}: '{param}' is undocumented"


# ---------------------------------------------------------------------------
# 2. Parameter casing survives verbatim. This is the assertion that matters:
#    EPLAN silently ignores a key whose case is wrong, so drift here is a
#    live failure with no error message.
# ---------------------------------------------------------------------------

def test_project_action_keeps_mixed_casing(capture):
    command = cmd(project.run_project_action(
        project_name="C:/p.elk", action="export",
        no_close=True, open_mode="ReadOnly", enable_dialogs="TRUE"))
    assert "/PROJECTNAME:C:/p.elk" in command
    assert "/Action:export" in command
    assert "/NOCLOSE:1" in command          # SCREAMING, not /NoClose
    assert "/OpenMode:ReadOnly" in command  # mixed, not /OPENMODE
    assert "/EnableDialogs:TRUE" in command
    assert "/NoClose" not in command and "/OPENMODE" not in command


def test_insert_device_keeps_part_nr_casing(capture):
    command = cmd(interaction.insert_device(
        part_nr="SIE.3RV2011", part_variant="1", project_id="P1", property_index=3))
    assert "/PartNr:SIE.3RV2011" in command   # not /PARTNR, not /partnr
    assert "/PartVariant:1" in command
    assert "/ProjectId:P1" in command
    assert "/PropertyIndex:3" in command
    assert "/PARTNR" not in command


def test_register_custom_property_editor_keeps_register_casing(capture):
    # register defaults to True, so the bare call is fully determined.
    assert cmd(addons.register_custom_property_editor()) == \
        "RegisterCustomPropertyEditorAction /Register:1"
    command = cmd(addons.register_custom_property_editor(
        action="MyEditor", property_id=20011, property_index=1, editable=True))
    assert "/Register:1" in command
    assert "/PropertyId:20011" in command
    assert "/PropertyIndex:1" in command
    assert "/PropertyIdentName" not in command
    assert "/Action:MyEditor" in command
    assert "/Editable:1" in command


def test_register_false_is_emitted_not_dropped(capture):
    # Unregistering is the teardown path; a truthiness bug would silently
    # re-register instead.
    assert cmd(addons.register_custom_property_editor(register=False)) == \
        "RegisterCustomPropertyEditorAction /Register:0"


def test_load_api_module_net_register_is_lowercase(capture):
    """EplApiModuleActionNet's key is lowercase `register` while
    RegisterCustomPropertyEditorAction's is `Register`. Both are correct; a
    well-meaning normalisation of either would break the other."""
    command = cmd(addons.load_api_module_net(register="MyAddin.dll"))
    assert "/register:MyAddin.dll" in command
    assert "/Register:" not in command
    assert "/REGISTER:" not in command


def test_load_api_module_net_camel_case_keys(capture):
    command = cmd(addons.load_api_module_net(
        register_module="Mod", unregister="MyAddin", unregister_internal="Other"))
    assert "/registerModule:Mod" in command
    assert "/unregister:MyAddin" in command
    assert "/unregisterInternal:Other" in command


@pytest.mark.parametrize("fn", [
    e3d.export_production_data_ras_center,
    e3d.export_production_data_smart_mounting,
], ids=["ras_center", "smart_mounting"])
def test_automationml_exports_keep_pascal_casing(capture, fn):
    command = cmd(fn(file_name="C:/out.aml", project_path="C:/p.elk",
                     database_id="7", whole_project=True, config_scheme="Default"))
    assert "/ConfigScheme:Default" in command   # not /CONFIGSCHEME
    assert "/FileName:C:/out.aml" in command
    assert "/ProjectPath:C:/p.elk" in command
    assert "/DatabaseId:7" in command
    assert "/WholeProject:1" in command
    assert "/CONFIGSCHEME" not in command


def test_update_detail_engineering_keeps_update_flag_casing(capture):
    command = cmd(planning.update_detail_engineering(
        project_name="C:/p.elk", update_macros=True, update_identifier=True,
        update_placeholder=False, update_pipedata=False, update_parts=True))
    assert "/UpdateMacros:1" in command       # not /UPDATEMACROS
    assert "/UpdateIdentifier:1" in command
    assert "/UpdatePlaceholder:0" in command
    assert "/UpdatePipedata:0" in command
    assert "/UpdateParts:1" in command
    assert "/PROJECTNAME:C:/p.elk" in command  # ...but PROJECTNAME IS screaming
    assert "/UPDATEMACROS" not in command


def test_select_device_project_name_is_mixed_case(capture):
    """XPamsDeviceSelectionAction uses /ProjectName, not the /PROJECTNAME that
    most other actions use - the inconsistency is EPLAN's, and copying the
    common form here would silently drop the project."""
    command = cmd(interaction.select_device(
        project_name="C:/p.elk", mode="updateDevice",
        keep_swapped_conn_point_information=True))
    assert "/ProjectName:C:/p.elk" in command
    assert "/PROJECTNAME" not in command
    assert "/Mode:updateDevice" in command
    assert "/KeepSwappedConnPointInformation:1" in command


def test_insert_symbol_reference_placementmode_casing(capture):
    """The docs spell it /Placementmode - lower-case 'm' in the middle."""
    command = cmd(interaction.insert_symbol_reference(
        symbol_lib_name="SPECIAL", symbol_id=12, variant_id=2,
        fct_def_tag="1302.1.1", placement_mode="Standard", symbol_type=16,
        custom_symbols="XSbGui.CustomSymbols.CustomSymbol", cursor="ENDTERMINAL"))
    assert "/Placementmode:Standard" in command
    assert "/PlacementMode" not in command
    assert "/SymbolLibName:SPECIAL" in command
    assert "/SymbolId:12" in command
    assert "/VariantId:2" in command
    assert "/FctDefTag:1302.1.1" in command
    assert "/SymbolType:16" in command
    assert "/CustomSymbols:XSbGui.CustomSymbols.CustomSymbol" in command
    assert "/Cursor:ENDTERMINAL" in command


def test_start_ged_interaction_lowercase_observed_keys(capture):
    command = cmd(interaction.start_ged_interaction(
        name="XMIaInsertMacro", filename="C:/m.ema", variant=0))
    assert command.startswith("XGedStartInteractionAction ")
    assert "/Name:XMIaInsertMacro" in command
    assert "/filename:C:/m.ema" in command   # lowercase, as observed in MFTools.xml
    assert "/variant:0" in command
    assert "/FileName" not in command and "/Variant:" not in command


def test_convert_base_projects_pascal_keys(capture):
    command = cmd(project.convert_base_projects(
        project_template="C:/t.ept", folder="C:/scratch", file_types="*.*"))
    assert "/ProjectTemplate:C:/t.ept" in command
    assert "/Folder:C:/scratch" in command
    assert "/FileTypes:*.*" in command


def test_create_graving_text_complete_key(capture):
    assert cmd(cabinet.create_graving_text(complete=True)) == \
        "XCCreateGravingtextAction /Complete:1"


def test_export_to_graphics_screaming_keys(capture):
    command = cmd(export_.export_to_graphics(
        destination_path="C:/out", type="GRAPHICPAGE", project_name="C:/p.elk",
        page_name="=A1/1", export_scheme="Default", format="PNG",
        color_depth=24, image_width=1024, image_compression="LZW",
        black_white=False, use_page_filter=True))
    assert "/EXPORTSCHEME:Default" in command
    assert "/DESTINATIONPATH:C:/out" in command
    assert "/TYPE:GRAPHICPAGE" in command
    assert "/PAGENAME:=A1/1" in command
    assert "/COLORDEPTH:24" in command
    assert "/IMAGEWIDTH:1024" in command
    assert "/IMAGECOMPRESSION:LZW" in command
    assert "/BLACKWHITE:0" in command
    assert "/USEPAGEFILTER:1" in command


def test_insert_model_view_screaming_keys(capture):
    command = cmd(e3d.insert_model_view(
        layout_space="LS1", page_name="=A1/1", dx=100.0, dy=50.0,
        project_name="C:/p.elk", structure="S", view_name="V",
        angle=1, selection_scheme="Sel", style=2, item_labeling="Lbl",
        viewpoint=7, root_elements="1#2", scale_setting=2, scale="1:10",
        view_type=1))
    for expected in ["/LAYOUTSPACE:LS1", "/PAGENAME:=A1/1", "/DX:100.0",
                     "/DY:50.0", "/PROJECTNAME:C:/p.elk", "/STRUCTURE:S",
                     "/VIEWNAME:V", "/ANGLE:1", "/SELECTIONSCHEME:Sel",
                     "/STYLE:2", "/ITEMLABELING:Lbl", "/VIEWPOINT:7",
                     "/ROOTELEMENTS:1#2", "/SCALESETTING:2", "/SCALE:1:10",
                     "/VIEWTYPE:1"]:
        assert expected in command, expected


# ---------------------------------------------------------------------------
# 3. None-valued optional parameters are omitted entirely
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", ALL_OPTIONAL, ids=ALL_OPTIONAL_IDS)
def test_bare_call_emits_no_none_params(capture, fn, kwargs):
    command = cmd(fn(**kwargs))
    emitted = set(keys(command))
    # register_custom_property_editor legitimately defaults register=True;
    # every other all-optional wrapper must emit the bare action name.
    expected = {"Register"} if fn is addons.register_custom_property_editor else set()
    assert emitted == expected, command
    assert "None" not in command


def test_mandatory_only_calls_omit_the_optionals(capture):
    assert cmd(export_.export_to_graphics(destination_path="C:/out")) == \
        "exportToGraphics /TYPE:GRAPHICPROJECT /DESTINATIONPATH:C:/out"
    assert cmd(interaction.start_ged_interaction(name="XMIaInsertMacro")) == \
        "XGedStartInteractionAction /Name:XMIaInsertMacro"
    assert cmd(project.run_project_action(project_name="C:/p.elk", action="export")) == \
        "ProjectAction /PROJECTNAME:C:/p.elk /Action:export"


def test_partial_optionals_drop_only_the_none_ones(capture):
    command = cmd(e3d.export_production_data_ras_center(
        file_name="C:/out.aml", whole_project=True))
    assert keys(command) == ["FileName", "WholeProject"]
    assert "/ProjectPath" not in command
    assert "/DatabaseId" not in command
    assert "/ConfigScheme" not in command


def test_zero_is_not_treated_as_missing(capture):
    """style=0 means "wire frame" and viewpoint=0 means "default" - a
    truthiness check instead of an `is None` check would silently drop both."""
    command = cmd(e3d.insert_model_view(
        layout_space="LS1", page_name="=A1/1", dx=1, dy=1,
        style=0, viewpoint=0, scale_setting=0, view_type=0))
    assert "/STYLE:0" in command
    assert "/VIEWPOINT:0" in command
    assert "/SCALESETTING:0" in command
    assert "/VIEWTYPE:0" in command


def test_empty_string_is_dropped(capture):
    command = cmd(e3d.export_production_data_ras_center(
        file_name="", config_scheme="Default"))
    assert keys(command) == ["ConfigScheme"]


# ---------------------------------------------------------------------------
# 4. Bools render as 1/0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,rendered", [(True, "1"), (False, "0")])
def test_bools_render_as_one_or_zero(capture, value, rendered):
    assert "/WholeProject:" + rendered in cmd(
        e3d.export_production_data_ras_center(whole_project=value))
    assert "/BLACKWHITE:" + rendered in cmd(
        export_.export_to_graphics(destination_path="C:/out", black_white=value))
    assert "/UpdateMacros:" + rendered in cmd(
        planning.update_detail_engineering(update_macros=value))
    assert "/NOCLOSE:" + rendered in cmd(project.run_project_action(
        project_name="C:/p.elk", action="export", no_close=value))
    assert "/Complete:" + rendered in cmd(cabinet.create_graving_text(complete=value))
    assert "/Editable:" + rendered in cmd(
        addons.register_custom_property_editor(editable=value))
    assert "/KeepSwappedConnPointInformation:" + rendered in cmd(
        interaction.select_device(keep_swapped_conn_point_information=value))
    assert "/USEPAGEFILTER:" + rendered in cmd(
        export_.export_to_graphics(destination_path="C:/out", use_page_filter=value))


def test_true_never_renders_as_python_repr(capture):
    command = cmd(planning.update_detail_engineering(update_macros=True,
                                                     update_parts=False))
    assert "True" not in command and "False" not in command


# ---------------------------------------------------------------------------
# 5. Values containing spaces get quoted (and space-free values do not)
# ---------------------------------------------------------------------------

def test_values_with_spaces_are_quoted(capture):
    command = cmd(export_.export_to_graphics(
        destination_path="C:/out dir", export_scheme="My Scheme"))
    assert '/DESTINATIONPATH:"C:/out dir"' in command
    assert '/EXPORTSCHEME:"My Scheme"' in command


def test_values_without_spaces_are_not_quoted(capture):
    command = cmd(export_.export_to_graphics(destination_path="C:/out"))
    assert "/DESTINATIONPATH:C:/out" in command
    assert '"' not in command


def test_already_quoted_value_is_not_double_quoted(capture):
    command = cmd(export_.export_to_graphics(destination_path='"C:/out dir"'))
    assert '/DESTINATIONPATH:"C:/out dir"' in command
    assert '""' not in command


def test_spaces_quoted_across_modules(capture):
    assert '/ProjectPath:"C:/My Projects/p.elk"' in cmd(
        e3d.export_production_data_ras_center(project_path="C:/My Projects/p.elk"))
    assert '/Folder:"C:/scratch dir"' in cmd(
        project.convert_base_projects(folder="C:/scratch dir"))
    assert '/register:"C:/My Addins/A.dll"' in cmd(
        addons.load_api_module_net(register="C:/My Addins/A.dll"))
    assert '/LAYOUTSPACE:"Layout Space 1"' in cmd(e3d.insert_model_view(
        layout_space="Layout Space 1", page_name="=A1/1", dx=1, dy=1))


# ---------------------------------------------------------------------------
# 6. Raw parameter tails are appended verbatim, never re-quoted
# ---------------------------------------------------------------------------

def test_run_project_action_appends_raw_tail(capture):
    command = cmd(project.run_project_action(
        project_name="C:/p.elk", action="export",
        action_args='  /TYPE:PDFPROJECT /EXPORTFILE:"C:/out/demo.pdf"  '))
    assert command == (
        'ProjectAction /PROJECTNAME:C:/p.elk /Action:export '
        '/TYPE:PDFPROJECT /EXPORTFILE:"C:/out/demo.pdf"'
    )


def test_run_project_action_without_tail_has_no_trailing_space(capture):
    command = cmd(project.run_project_action(project_name="C:/p.elk", action="export"))
    assert command == command.strip()


def test_lock_unlock_all_objects_bare_and_with_raw_args(capture):
    assert cmd(settings.lock_unlock_all_objects()) == "LockUnlockAllObjects"
    assert cmd(settings.lock_unlock_all_objects(
        raw_args='  /KEY:value /OTHER:"a b"  ')) == \
        'LockUnlockAllObjects /KEY:value /OTHER:"a b"'


# ---------------------------------------------------------------------------
# 7. Every emitted key exists, with that exact casing, in the official docs
#    (the two actions whose doc page 404s are exempt - the wrappers say so).
# ---------------------------------------------------------------------------

with open(_OFFICIAL_PATH, "r", encoding="utf-8") as _f:
    OFFICIAL = json.load(_f)


def _all_kwargs(fn):
    """Every parameter of the wrapper set to a simple, space-free value."""
    return {name: "x" for name in inspect.signature(fn).parameters}


@pytest.mark.parametrize("fn,_kwargs", WRAPPERS, ids=WRAPPER_IDS)
def test_emitted_keys_match_official_docs(capture, fn, _kwargs):
    action = docstring_action(fn)
    entry = OFFICIAL.get(action)
    assert entry is not None, action + " is not in official_actions_2027.json"
    if entry.get("doc_error"):
        pytest.skip(action + ": official doc page 404s, no parameter table")

    documented = {p["name"] for p in entry.get("params") or []}
    allowed = documented | OBSERVED_ONLY_KEYS.get(action, set())

    command = cmd(fn(**_all_kwargs(fn)))
    for key in keys(command):
        assert key in allowed, (
            "%s emits /%s which is not a documented parameter of %s. "
            "Documented (exact casing): %s" % (
                fn.__name__, key, action, sorted(documented))
        )


@pytest.mark.parametrize("fn,_kwargs", WRAPPERS, ids=WRAPPER_IDS)
def test_wrapper_does_not_silently_drop_a_kwarg(capture, fn, _kwargs):
    """Setting every argument must produce a key for every argument, except the
    raw-tail arguments which are appended rather than keyed."""
    raw_tails = {"action_args", "raw_args"}
    params = [p for p in inspect.signature(fn).parameters if p not in raw_tails]
    command = cmd(fn(**_all_kwargs(fn)))
    assert len(keys(command)) == len(params), command


# ---------------------------------------------------------------------------
# 7b. export_3d / import_3d - Audit #42 items 1 and 4.
#
# Before this fix, export_3d sent FORMAT/INSTALLATIONSPACE (neither a real
# export3d parameter) and never sent the mandatory TYPE; import_3d sent
# IMPORTSCHEME (the action documents SCHEME) and also never sent TYPE.
# Reproduced live 2026-09-04 (EPLAN 2025.0.3, Pro Panel licensed): both
# actions answered "Este proceso no es compatible." and wrote nothing. The
# fix was then verified live the same way - a real installation space
# exported to a .stp file that import_3d could read back in.
#
# Not folded into the WRAPPERS table above: `type` is validated, and
# `_all_kwargs`'s blanket "x" is not a legal value for it, so the two
# generic tests that call every wrapper with all-"x" kwargs would break on
# these before ever reaching _build_action.
# ---------------------------------------------------------------------------

def test_export_3d_emits_documented_keys(capture):
    command = cmd(export_.export_3d(
        destination_path="C:/out", type="STEP", project_name="C:/p.elk",
        installation_space="BR1", export_scheme="Scheme1",
        separate_files=True, filename="out.jt"))
    assert command.split()[0] == "export3d"
    documented = {p["name"] for p in OFFICIAL["export3d"].get("params") or []}
    assert keys(command), command
    for key in keys(command):
        assert key in documented, (
            "export3d emits /%s, not a documented parameter. Documented: %s"
            % (key, sorted(documented)))
    assert len(keys(command)) == len(inspect.signature(export_.export_3d).parameters)
    assert "/TYPE:STEP" in command
    assert "/INSTALLATIONSPACENAME:BR1" in command
    assert "/FORMAT" not in command
    assert "/INSTALLATIONSPACE:" not in command  # the old, wrong key


def test_export_3d_rejects_invalid_type(capture):
    result = export_.export_3d(destination_path="C:/out", type="BMP")
    assert result["success"] is False
    assert "STEP" in result["error"] and "JT" in result["error"]


def test_import_3d_emits_documented_keys(capture):
    command = cmd(import_.import_3d(
        import_file="C:/in.stp", type="STEP", project_name="C:/p.elk",
        import_scheme="Scheme1"))
    assert command.split()[0] == "import3d"
    documented = {p["name"] for p in OFFICIAL["import3d"].get("params") or []}
    assert keys(command), command
    for key in keys(command):
        assert key in documented, (
            "import3d emits /%s, not a documented parameter. Documented: %s"
            % (key, sorted(documented)))
    assert len(keys(command)) == len(inspect.signature(import_.import_3d).parameters)
    assert "/TYPE:STEP" in command
    assert "/SCHEME:Scheme1" in command
    assert "/IMPORTSCHEME" not in command


def test_import_3d_rejects_invalid_type(capture):
    result = import_.import_3d(import_file="C:/in.stp", type="BMP")
    assert result["success"] is False
    assert "STEP" in result["error"]


# ---------------------------------------------------------------------------
# 7c. update_reports - Audit #42 item 3.
#
# TYPE only became "PAGES" when page_name/page_names/page_identifiers were
# given. Passing only use_page_filter or page_filter_name left TYPE="PROJECT",
# where the action documents PAGEFILTERNAME as effective only under "PAGES" -
# so the filter was silently ignored and the WHOLE project's reports were
# updated instead of the filtered subset.
#
# Not folded into the generic WRAPPERS table above: `_all_kwargs`'s blanket
# "x" turns page_names/page_identifiers (List[str] params) into the STRING
# "x", which this wrapper's `for i, page in enumerate(page_names, 1)` then
# iterates character-by-character - a real bug in the generic harness's
# assumptions for any List[str] param, not in this wrapper. And TYPE is
# always emitted regardless of which arguments were given, which breaks the
# generic table's "one key per argument" kwarg-count check. Both apply to
# every List[str]-taking wrapper equally, not just this one, and are out of
# scope for the fix this issue asked for.
# ---------------------------------------------------------------------------

def test_update_reports_page_filter_alone_selects_pages_type(capture):
    command = cmd(reports.update_reports(use_page_filter=True))
    assert command.split()[0] == "reports"
    assert "/TYPE:PAGES" in command
    assert "/TYPE:PROJECT" not in command


def test_update_reports_page_filter_name_alone_selects_pages_type(capture):
    command = cmd(reports.update_reports(page_filter_name="MyFilter"))
    assert "/TYPE:PAGES" in command
    assert '/PAGEFILTERNAME:"MyFilter"' in command


def test_update_reports_no_page_selector_still_means_whole_project(capture):
    """The other half of the fix: a bare call must still mean TYPE=PROJECT -
    over-selecting PAGES with no filter at all would be its own bug."""
    command = cmd(reports.update_reports())
    assert "/TYPE:PROJECT" in command


def test_update_reports_emits_only_documented_keys(capture):
    command = cmd(reports.update_reports(
        project_name="C:/p.elk", page_name="=A1", page_names=["=A2", "=A3"],
        page_identifiers=["1/2/3"], use_page_filter=True, page_filter_name="F1"))
    documented = {p["name"] for p in OFFICIAL["reports"].get("params") or []}
    documented |= {"PAGENAME1", "PAGENAME2", "SEL1"}  # PAGENAMEn/SELn instances
    for key in keys(command):
        assert key in documented, (
            "update_reports emits /%s, not documented: %s" % (key, sorted(documented)))


# ---------------------------------------------------------------------------
# 8. No connection -> the not-connected error dict, never an exception
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", WRAPPERS, ids=WRAPPER_IDS)
def test_not_connected_returns_error_dict(disconnected, fn, kwargs):
    result = fn(**kwargs)
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Not connected" in result["message"]
    assert "command" not in result


# ---------------------------------------------------------------------------
# 9. The generic catalog tier (catalog.py) - offline by design
# ---------------------------------------------------------------------------

def test_action_catalog_needs_no_connection(disconnected):
    result = catalog.action_catalog(limit=5)
    assert result["success"] is True
    assert result["count"] > 500
    assert result["returned"] == 5
    assert result["truncated"] == result["count"] - 5


def test_action_catalog_search_narrows(disconnected):
    everything = catalog.action_catalog(limit=0)["count"]
    narrowed = catalog.action_catalog(search="pdf", limit=0)["count"]
    assert 0 < narrowed < everything


def test_action_catalog_rejects_non_integer_limit(disconnected):
    result = catalog.action_catalog(limit="lots")
    assert result["success"] is False
    assert "limit" in result["error"].lower()


def test_action_run_dry_run_preserves_key_casing(disconnected):
    result = catalog.action_run(
        "ProjectAction",
        {"PROJECTNAME": "C:/p.elk", "NOCLOSE": True, "OpenMode": "ReadOnly"},
        dry_run=True)
    assert result["success"] is True and result["dry_run"] is True
    command = result["command"]
    assert command.startswith("ProjectAction ")
    assert "/PROJECTNAME:C:/p.elk" in command
    assert "/NOCLOSE:1" in command
    assert "/OpenMode:ReadOnly" in command


def test_action_run_resolves_name_casing_but_not_param_casing(disconnected):
    resolved = catalog.action_run("projectaction", {"PROJECTNAME": "x"}, dry_run=True)
    assert resolved["command"].split()[0] == "ProjectAction"

    wrong = catalog.action_run("ProjectAction", {"noclose": True}, dry_run=True)
    assert wrong["success"] is False
    assert "casing matters" in wrong["suggestions"]["noclose"]


def test_action_run_unknown_action_is_refused(disconnected):
    result = catalog.action_run("NoSuchActionAtAll", dry_run=True)
    assert result["success"] is False
    assert "near_matches" in result


def test_action_run_allow_unknown_params_passes_them_through(disconnected):
    result = catalog.action_run("ProjectAction", {"MadeUpKey": "v"},
                                dry_run=True, allow_unknown_params=True)
    assert result["success"] is True
    assert "/MadeUpKey:v" in result["command"]
    assert result["validation"]["unknown_params_sent"] == ["MadeUpKey"]


def test_action_run_without_connection_still_reports_the_command(disconnected):
    result = catalog.action_run("ProjectAction", {"PROJECTNAME": "x"})
    assert result["success"] is False
    assert "Not connected" in result["message"]
    assert result["command"] == "ProjectAction /PROJECTNAME:x"


def test_action_describe_degrades_to_registry_only(disconnected):
    result = catalog.action_describe("projectaction")
    assert result["success"] is True
    assert result["name"] == "ProjectAction"
    assert result["in_registry"] is True
    assert result["live"]["probed"] is False
    assert "Not connected" in result["live"]["reason"]


def test_action_describe_unknown_name_offers_near_matches(disconnected):
    result = catalog.action_describe("ProjectActio")
    assert result["in_registry"] is False
    assert "ProjectAction" in result["near_matches"]


def test_action_describe_requires_a_name(disconnected):
    assert catalog.action_describe("   ")["success"] is False


def test_ribbon_catalog_success_path(monkeypatch):
    monkeypatch.setattr(catalog, "_execute_script", lambda script, timeout=30.0: {
        "success": True,
        "results": {"success": True, "tabs": [], "tab_count": 0, "command_count": 0},
    })
    result = catalog.ribbon_catalog()
    assert result["success"] is True
    assert result["tab_count"] == 0
    assert "custom" in result["note"].lower()


def test_ribbon_catalog_reports_script_failure(monkeypatch):
    monkeypatch.setattr(catalog, "_execute_script", lambda script, timeout=30.0: {
        "success": False, "message": "boom"})
    result = catalog.ribbon_catalog()
    assert result == {"success": False, "error": "boom"}


# ---------------------------------------------------------------------------
# 10. All of the above wrappers are actually exported as MCP tools
# ---------------------------------------------------------------------------

def test_every_wrapper_is_exported(capture):
    from api import actions
    for fn, _ in WRAPPERS:
        assert fn.__name__ in actions.__all__, fn.__name__ + " missing from __all__"
    for name in ("action_catalog", "action_describe", "action_run", "ribbon_catalog"):
        assert name in actions.__all__, name + " missing from __all__"
