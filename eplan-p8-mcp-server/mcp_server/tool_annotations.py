"""
What each tool does, stated as facts every MCP client can read.

Every published tool carries:

- the four standard MCP annotations (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`), always set explicitly, and
- a few EPLAN facts in the tool's `_meta`, under the key `canary-ecad/eplan`:

    changesProject   writes the open project (a client may back it up first)
    runsCode         runs scripts, actions or add-ins it is given
    changesEplan     changes EPLAN itself: settings, parts database, master
                     data, ribbon, workspace, loaded add-ins
    projectArgument  the argument that names the project the call acts on,
                     when the tool has one (for a client's typed confirmation)

These are facts, not policy: whether a client asks before a call is the
client's decision. The facts are written down by hand in TOOL_FLAGS, one line
per tool, so a diff shows exactly what changed. A tool missing from the table
fails test_tool_annotations_offline.py; tools.json (see tools/dump_tools.py)
is the published copy, attached to every release.

Flags, separated by spaces:

    read         only reads EPLAN, the parts database or the docs, or moves
                 the GUI around (opens a page, selects a device)
    project      changesProject
    code         runsCode
    eplan        changesEplan
    destructive  may delete or overwrite work, or is hard to undo
    idempotent   calling it twice with the same arguments does nothing more

An empty string means: changes something outside the open project (writes an
export, a backup or a print) or opens, closes or checks it, without deleting
anything. No tool talks to anything but the local EPLAN, so openWorldHint is
always false.

Extension modules (EPLAN_MCP_EXTENSIONS) may declare their own table as
TOOL_FLAGS = {"function_name": "flags"}; their tools have no annotations
otherwise, which a careful client treats as "may change anything".
"""

import inspect

from mcp.types import ToolAnnotations

__all__ = ["META_KEY", "TOOL_FLAGS", "FLAGS", "annotate", "parse_flags"]

META_KEY = "canary-ecad/eplan"

FLAGS = frozenset({"read", "project", "code", "eplan", "destructive", "idempotent"})

# Arguments that name the project a call acts on, in the order they are looked
# for. The first one a tool has is its projectArgument.
_PROJECT_ARGUMENTS = ("project_name", "project_path", "project")


def parse_flags(flags):
    """'project destructive' -> {'project', 'destructive'}; unknown flags raise."""
    words = set(flags.split())
    unknown = words - FLAGS
    if unknown:
        raise ValueError(f"unknown tool flags: {', '.join(sorted(unknown))}")
    if "read" in words and words & {"project", "code", "eplan", "destructive"}:
        raise ValueError(f"a read tool cannot also change something: {flags!r}")
    return words


def _project_argument(func):
    if func is None:
        return None
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return None
    return next((name for name in _PROJECT_ARGUMENTS if name in params), None)


def annotate(tool_name, func=None, table=None):
    """
    (ToolAnnotations, meta) for a tool, or (None, None) when the table doesn't
    know it. `meta` is the tool's whole `_meta`: {META_KEY: facts}.
    """
    table = TOOL_FLAGS if table is None else table
    flags = table.get(tool_name)
    if flags is None:
        return None, None
    words = parse_flags(flags)
    read = "read" in words
    annotations = ToolAnnotations(
        readOnlyHint=read,
        destructiveHint="destructive" in words,
        idempotentHint=read or "idempotent" in words,
        openWorldHint=False,
    )
    facts = {
        "changesProject": "project" in words,
        "runsCode": "code" in words,
        "changesEplan": "eplan" in words,
    }
    argument = _project_argument(func)
    if argument:
        facts["projectArgument"] = argument
    return annotations, {META_KEY: facts}


# fmt: off
TOOL_FLAGS = {
    "aas_export_part":                             "idempotent",
    "aas_export_project":                          "idempotent",
    "aas_import_parts":                            "eplan",
    "aas_inspect_package":                         "read",
    "eplan_action_catalog":                        "read",
    "eplan_action_describe":                       "read",
    "eplan_action_run":                            "project code destructive",
    "eplan_api_describe":                          "read",
    "eplan_api_types":                             "read",
    "eplan_app_launch":                            "",
    "eplan_app_restart":                           "destructive",
    "eplan_app_shutdown":                          "destructive",
    "eplan_backup_masterdata":                     "",
    "eplan_backup_project":                        "",
    "eplan_calculate_cabinet_weight":              "project",
    "eplan_change_layer":                          "project",
    "eplan_check_pages":                           "",
    "eplan_check_parts":                           "",
    "eplan_check_project":                         "",
    "eplan_clean_workspace":                       "eplan destructive",
    "eplan_close_pages":                           "read",
    "eplan_close_project":                         "idempotent",
    "eplan_compress_project":                      "project destructive",
    "eplan_connect":                               "read",
    "eplan_convert_base_projects":                 "project destructive",
    "eplan_correct_connections":                   "project",
    "eplan_create_copper_unfolds":                 "project",
    "eplan_create_drilling_views":                 "project",
    "eplan_create_graving_text":                   "project",
    "eplan_create_installation_space":             "project",
    "eplan_create_labels":                         "project",
    "eplan_create_model_views":                    "project",
    "eplan_dc_export":                             "idempotent",
    "eplan_dc_import":                             "project",
    "eplan_delete_device_list":                    "project destructive",
    "eplan_delete_representation_type":            "project destructive",
    "eplan_disconnect":                            "read",
    "eplan_edit_goto_device":                      "read",
    "eplan_edit_open_layout_space":                "read",
    "eplan_edit_open_page":                        "read",
    "eplan_execute_custom_script":                 "project code destructive",
    "eplan_execute_raw_action":                    "project code destructive",
    "eplan_execute_script":                        "project code destructive",
    "eplan_export_3d":                             "idempotent",
    "eplan_export_connections":                    "idempotent",
    "eplan_export_dc_article_data":                "idempotent",
    "eplan_export_device_list":                    "idempotent",
    "eplan_export_dwg_pages":                      "idempotent",
    "eplan_export_dwg_project":                    "idempotent",
    "eplan_export_dxf_pages":                      "idempotent",
    "eplan_export_dxf_project":                    "idempotent",
    "eplan_export_dxfdwg_pages_scheme":            "idempotent",
    "eplan_export_dxfdwg_project_scheme":          "idempotent",
    "eplan_export_functions":                      "idempotent",
    "eplan_export_graphical_layer_table":          "idempotent",
    "eplan_export_graphics_pages":                 "idempotent",
    "eplan_export_graphics_project":               "idempotent",
    "eplan_export_location_boxes":                 "idempotent",
    "eplan_export_missing_translations":           "idempotent",
    "eplan_export_nc_data":                        "idempotent",
    "eplan_export_pages":                          "idempotent",
    "eplan_export_parts_list":                     "idempotent",
    "eplan_export_pdf_pages":                      "idempotent",
    "eplan_export_pdf_project":                    "idempotent",
    "eplan_export_pipeline_definitions":           "idempotent",
    "eplan_export_potential_definitions":          "idempotent",
    "eplan_export_production_data_ras_center":     "idempotent",
    "eplan_export_production_data_smart_mounting": "idempotent",
    "eplan_export_production_wiring":              "idempotent",
    "eplan_export_pxf_project":                    "idempotent",
    "eplan_export_ribbon_bar":                     "idempotent",
    "eplan_export_segments_template":              "idempotent",
    "eplan_export_settings":                       "idempotent",
    "eplan_export_subproject":                     "idempotent",
    "eplan_export_to_graphics":                    "idempotent",
    "eplan_export_user_properties":                "idempotent",
    "eplan_generate_cables":                       "project",
    "eplan_generate_connections":                  "project",
    "eplan_generate_macros":                       "project",
    "eplan_get_current_project":                   "read",
    "eplan_get_page_property":                     "read",
    "eplan_get_project_property":                  "read",
    "eplan_get_property":                          "read",
    "eplan_get_selected_pages":                    "read",
    "eplan_get_system_messages":                   "read",
    "eplan_import_3d":                             "project",
    "eplan_import_dc_article_data":                "project",
    "eplan_import_device_list":                    "project",
    "eplan_import_dwg_page":                       "project",
    "eplan_import_dxf_page":                       "project",
    "eplan_import_dxfdwg_files":                   "project",
    "eplan_import_graphical_layer_table":          "project",
    "eplan_import_parts_list":                     "project",
    "eplan_import_pdf_comments":                   "project",
    "eplan_import_preplanning_data":               "project",
    "eplan_import_pxf_project":                    "project",
    "eplan_import_ribbon_bar":                     "eplan",
    "eplan_import_segments_template":              "project",
    "eplan_import_settings":                       "eplan",
    "eplan_import_subproject":                     "project",
    "eplan_import_user_properties":                "project",
    "eplan_insert_3d_macro":                       "project",
    "eplan_insert_device":                         "project",
    "eplan_insert_model_view":                     "project",
    "eplan_insert_symbol_reference":               "project",
    "eplan_list_enums":                            "read",
    "eplan_list_extensions":                       "read",
    "eplan_list_layers":                           "read",
    "eplan_list_report_templates":                 "read",
    "eplan_list_schemes":                          "read",
    "eplan_live_connect_pins":                     "project",
    "eplan_live_connect_pins_routed":              "project",
    "eplan_live_create_page":                      "project",
    "eplan_live_place_connected":                  "project",
    "eplan_live_place_connection_symbol":          "project",
    "eplan_live_place_corner":                     "project",
    "eplan_live_place_symbol":                     "project",
    "eplan_live_place_tnode":                      "project",
    "eplan_live_query_functions":                  "read",
    "eplan_live_query_pages":                      "read",
    "eplan_live_read_check_messages":              "read",
    "eplan_live_read_connections":                 "read",
    "eplan_live_read_page":                        "read",
    "eplan_live_remove_placement":                 "project destructive",
    "eplan_live_routing_catalog":                  "read",
    "eplan_live_set_connection_designations":      "project idempotent",
    "eplan_live_set_device_tag":                   "project idempotent",
    "eplan_live_set_function_text":                "project idempotent",
    "eplan_live_symbol_catalog":                   "read",
    "eplan_live_verify_page":                      "read",
    "eplan_load_api_module":                       "code eplan",
    "eplan_load_api_module_net":                   "code eplan",
    "eplan_lock_unlock_all_objects":               "project",
    "eplan_masterdata_operation":                  "eplan destructive",
    "eplan_navigate_to_eec":                       "read",
    "eplan_open_project":                          "idempotent",
    "eplan_open_workspace":                        "",
    "eplan_parts_db_count":                        "read",
    "eplan_parts_db_create":                       "eplan",
    "eplan_parts_db_get_part":                     "read",
    "eplan_parts_db_list_product_groups":          "read",
    "eplan_parts_db_query":                        "read",
    "eplan_parts_db_update":                       "eplan",
    "eplan_partsmanagement_export":                "idempotent",
    "eplan_partsmanagement_export_all":            "idempotent",
    "eplan_partsmanagement_export_by_properties":  "idempotent",
    "eplan_partsmanagement_import":                "eplan",
    "eplan_pathmap_get_common_paths":              "read",
    "eplan_pathmap_substitute":                    "read",
    "eplan_ping":                                  "read",
    "eplan_plc_export":                            "idempotent",
    "eplan_plc_import":                            "project",
    "eplan_prepare_macros":                        "project",
    "eplan_preview_page":                          "read",
    "eplan_print_pages":                           "idempotent",
    "eplan_print_project":                         "idempotent",
    "eplan_project_management":                    "project destructive",
    "eplan_redraw_ged":                            "read",
    "eplan_register_addon":                        "code eplan",
    "eplan_register_custom_property_editor":       "code eplan",
    "eplan_register_script":                       "code eplan",
    "eplan_remove_language":                       "project destructive",
    "eplan_remove_unnecessary_ndps":               "project",
    "eplan_renumber_cables":                       "project",
    "eplan_renumber_connections":                  "project",
    "eplan_renumber_devices":                      "project",
    "eplan_renumber_pages":                        "project",
    "eplan_renumber_terminals":                    "project",
    "eplan_restore_masterdata":                    "eplan destructive",
    "eplan_restore_project":                       "destructive",
    "eplan_ribbon_catalog":                        "read",
    "eplan_run_project_action":                    "project code destructive",
    "eplan_save_workspace":                        "",
    "eplan_scratch_project_create":                "",
    "eplan_scratch_project_discard":               "destructive",
    "eplan_scratch_project_list":                  "read",
    "eplan_search_all_properties":                 "read",
    "eplan_search_devices":                        "read",
    "eplan_search_page_data":                      "read",
    "eplan_search_project_data":                   "read",
    "eplan_search_text":                           "read",
    "eplan_select_device":                         "read",
    "eplan_select_part":                           "",
    "eplan_servers":                               "read",
    "eplan_set_page_property":                     "project idempotent",
    "eplan_set_parts_data_source":                 "eplan idempotent",
    "eplan_set_project_language":                  "project idempotent",
    "eplan_set_project_property":                  "project idempotent",
    "eplan_set_project_setting":                   "project idempotent",
    "eplan_set_property":                          "project idempotent",
    "eplan_set_setting":                           "eplan idempotent",
    "eplan_settings_get_bool":                     "read",
    "eplan_settings_get_double":                   "read",
    "eplan_settings_get_int":                      "read",
    "eplan_settings_get_string":                   "read",
    "eplan_settings_list_children":                "read",
    "eplan_settings_set_bool":                     "eplan idempotent",
    "eplan_settings_set_double":                   "eplan idempotent",
    "eplan_settings_set_int":                      "eplan idempotent",
    "eplan_settings_set_string":                   "eplan idempotent",
    "eplan_start_ged_interaction":                 "",
    "eplan_status":                                "read",
    "eplan_switch_project_type":                   "project destructive",
    "eplan_synchronize_project":                   "project",
    "eplan_test":                                  "read",
    "eplan_topology_operation":                    "project",
    "eplan_translate_project":                     "project",
    "eplan_unite_net_definition_points":           "project",
    "eplan_unregister_addon":                      "code eplan",
    "eplan_unregister_script":                     "code eplan",
    "eplan_update_detail_engineering":             "project",
    "eplan_update_macros":                         "project",
    "eplan_update_model_view_pages":               "project",
    "eplan_update_reports":                        "project",
    "eplan_update_segments_filling":               "project",
    "eplan_upgrade_projects":                      "project destructive",
    "eplan_versions":                              "read",
    # Discovery mode only (EPLAN_MCP_MODE=discovery): eplan_tools_call runs
    # any other tool by name, so it carries the facts of the worst one.
    "eplan_tools_search":                          "read",
    "eplan_tools_describe":                        "read",
    "eplan_tools_call":                            "project code eplan destructive",
}
# fmt: on
