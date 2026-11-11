# EPLAN Action Validation Report

Checked **101** unique EPLAN actions declared by the wrappers against the official EPLAN 2027 wiki (`https://rag2027.covaga.xyz`).

An action counts as documented if and only if the wiki serves a page at `API Reference/Actions/<Name>.md`. Parameter names are matched **case-sensitively** against that page's full text, because `_build_action` forwards kwarg names verbatim as `/KEY`.

- OK: 80
- Parameter names not found on the doc page: 16
- Parameter names present but with different casing: 2
- In our official list but no wiki page (wiki index gap): 2
- Undocumented (GUI-only / internal action, never in the API docs): 1
- Request errors: 0

## Wiki completeness

Does the 2027 wiki document any action we do not know about?

Direct probe - `GET /file` for each of the 100 names in `tools/data/official_actions_2027.json`:

- with a wiki page: **98**
- without a wiki page: **2** (`LockUnlockAllObjects`, `XAMlExportProductionData2SmartMountingAction`)

Reverse sweep - enumerate `API Reference/Actions/*.md` with 12268 prefix/seed queries (FTS5 prefix search, recursing only into saturated prefixes; deepest prefix used: 3 characters):

- action pages found in the wiki: **98**
- in the wiki but NOT in our list: **0** - our list is complete
- in our list but NOT in the wiki: **2** (`LockUnlockAllObjects`, `XAMlExportProductionData2SmartMountingAction`)
- queries that still failed after retries: **2** (`ep`, `eed`) - the sweep is that much less than exhaustive

## Per-action results

| Status | Action | Wrapper(s) | Detail |
|--------|--------|------------|--------|
| WARN | `ExportNCData` | `production.export_nc_data` | params not on the doc page: ['EXPORTFILE']; case mismatch: ['PROJECTNAME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ExportNCData.html) |
| WARN | `ExportProductionWiring` | `production.export_production_wiring` | params not on the doc page: ['EXPORTFILE']; case mismatch: ['PROJECTNAME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ExportProductionWiring.html) |
| WARN | `ExportSegmentsTemplate` | `cabinet.export_segments_template` | params not on the doc page: ['EXPORTFILE'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ExportSegmentsTemplate.html) |
| WARN | `ImportPrePlanningData` | `cabinet.import_preplanning_data` | params not on the doc page: ['IMPORTFILE'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ImportPrePlanningData.html) |
| WARN | `ImportSegmentsTemplate` | `cabinet.import_segments_template` | params not on the doc page: ['IMPORTFILE'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ImportSegmentsTemplate.html) |
| WARN | `XEGActionInsertSymRef` | `interaction.insert_symbol_reference` | params not on the doc page: ['Cursor'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEGActionInsertSymRef.html) |
| WARN | `XEsUserPropertiesExportAction` | `properties.export_user_properties` | params not on the doc page: ['EXPORTFILE', 'PROJECTNAME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsUserPropertiesExportAction.html) |
| WARN | `XEsUserPropertiesImportAction` | `properties.import_user_properties` | params not on the doc page: ['IMPORTFILE', 'PROJECTNAME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsUserPropertiesImportAction.html) |
| WARN | `XGedStartInteractionAction` | `interaction.start_ged_interaction` | params not on the doc page: ['variant'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XGedStartInteractionAction.html) |
| WARN | `XMDeleteReprTypeAction` | `data_exchange.delete_representation_type` | params not on the doc page: ['PROJECTNAME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMDeleteReprTypeAction.html) |
| WARN | `XMImportDCArticleDataAction` | `data_exchange.import_dc_article_data` | params not on the doc page: ['IMPORTFILE', 'PROJECTNAME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMImportDCArticleDataAction.html) |
| WARN | `XPartsSetDataSourceAction` | `parts.set_parts_data_source` | params not on the doc page: ['DATASOURCE'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XPartsSetDataSourceAction.html) |
| WARN | `export` | `export_.export_pdf_project, export_.export_pdf_pages, export_.export_dxf_project, export_.export_dxf_pages, export_.export_dwg_project, export_.export_dwg_pages, export_.export_dxfdwg_project_scheme, export_.export_dxfdwg_pages_scheme, export_.export_graphics_project, export_.export_graphics_pages, export_.export_pxf_project` | params not on the doc page: ['USEPAGEFILTER'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/export.html) |
| WARN | `generatemacros` | `macros.generate_macros` | params not on the doc page: ['DESTINATIONPATH']; case mismatch: ['SCHEME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/generatemacros.html) |
| WARN | `import3d` | `import_.import_3d` | params not on the doc page: ['IMPORTSCHEME'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/import3d.html) |
| WARN | `masterdata` | `data_exchange.masterdata_operation` | params not on the doc page: ['DESTINATIONPATH', 'SOURCEPATH'] [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/masterdata.html) |
| CASE | `XCabCalculateEnclosureTotalWeightAction` | `cabinet.calculate_cabinet_weight` | params present only with different casing: ['PROJECTNAME'] - _build_action forwards kwarg names verbatim as /KEY, so check this against EPLAN [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XCabCalculateEnclosureTotalWeightAction.html) |
| CASE | `export3d` | `export_.export_3d` | params present only with different casing: ['FORMAT', 'INSTALLATIONSPACE'] - _build_action forwards kwarg names verbatim as /KEY, so check this against EPLAN [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/export3d.html) |
| NO WIKI PAGE | `LockUnlockAllObjects` | `settings.lock_unlock_all_objects` | in official_actions_2027.json but the wiki has no 'API Reference/Actions/LockUnlockAllObjects.md' page (wiki index gap); parameters checked against the JSON instead [doc](https://www.eplan.help/en-us/Infoportal/Content/api/2027/LockUnlockAllObjects.html) |
| NO WIKI PAGE | `XAMlExportProductionData2SmartMountingAction` | `e3d.export_production_data_smart_mounting` | in official_actions_2027.json but the wiki has no 'API Reference/Actions/XAMlExportProductionData2SmartMountingAction.md' page (wiki index gap); parameters checked against the JSON instead - params not in the JSON: ['ConfigScheme', 'DatabaseId', 'FileName', 'ProjectPath', 'WholeProject'] [doc](https://www.eplan.help/en-us/Infoportal/Content/api/2027/XAMlExportProductionData2SmartMountingAction.html) |
| UNDOCUMENTED | `XPrjActionProjectClose` | `project.close_project` | no 'API Reference/Actions/XPrjActionProjectClose.md' page and not in official_actions_2027.json - GUI-only or internal action, parameters observed rather than documented |
| OK | `CleanWorkspaceAction` | `workspace.clean_workspace` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/CleanWorkspaceAction.html) |
| OK | `EplApiModuleAction` | `addons.load_api_module` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/EplApiModuleAction.html) |
| OK | `EplApiModuleActionNet` | `addons.load_api_module_net` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/EplApiModuleActionNet.html) |
| OK | `EsCorrectConnections` | `data_exchange.correct_connections` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/EsCorrectConnections.html) |
| OK | `ExecuteScript` | `scripts.execute_script` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ExecuteScript.html) |
| OK | `InsertModelViewAction` | `e3d.insert_model_view` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/InsertModelViewAction.html) |
| OK | `MfExportRibbonBarAction` | `ribbon.export_ribbon_bar` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/MfExportRibbonBarAction.html) |
| OK | `MfImportRibbonBarAction` | `ribbon.import_ribbon_bar` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/MfImportRibbonBarAction.html) |
| OK | `OpenWorkspaceAction` | `workspace.open_workspace` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/OpenWorkspaceAction.html) |
| OK | `ProjectAction` | `project.run_project_action` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ProjectAction.html) |
| OK | `ProjectOpen` | `project.open_project` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/ProjectOpen.html) |
| OK | `RegisterCustomPropertyEditorAction` | `addons.register_custom_property_editor` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/RegisterCustomPropertyEditorAction.html) |
| OK | `RegisterScript` | `scripts.register_script` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/RegisterScript.html) |
| OK | `SaveWorkspaceAction` | `workspace.save_workspace` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/SaveWorkspaceAction.html) |
| OK | `SetProjectLanguage` | `project.set_project_language` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/SetProjectLanguage.html) |
| OK | `SwitchProjectType` | `project.switch_project_type` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/SwitchProjectType.html) |
| OK | `Topology` | `cabinet.topology_operation` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/Topology.html) |
| OK | `UnregisterScript` | `scripts.unregister_script` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/UnregisterScript.html) |
| OK | `UpdateSegmentsFilling` | `cabinet.update_segments_filling` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/UpdateSegmentsFilling.html) |
| OK | `XAMlExportProductionData2RASCenterAction` | `e3d.export_production_data_ras_center` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XAMlExportProductionData2RASCenterAction.html) |
| OK | `XAfActionSetting` | `settings.set_setting` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XAfActionSetting.html) |
| OK | `XAfActionSettingProject` | `settings.set_project_setting` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XAfActionSettingProject.html) |
| OK | `XCCreateGravingtextAction` | `cabinet.create_graving_text` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XCCreateGravingtextAction.html) |
| OK | `XCMRemoveUnnecessaryNDPsAction` | `data_exchange.remove_unnecessary_ndps` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XCMRemoveUnnecessaryNDPsAction.html) |
| OK | `XCMUniteNetDefinitionPointsAction` | `data_exchange.unite_net_definition_points` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XCMUniteNetDefinitionPointsAction.html) |
| OK | `XDLInsertDeviceAction` | `interaction.insert_device` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XDLInsertDeviceAction.html) |
| OK | `XEsGetPagePropertyAction` | `properties.get_page_property` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsGetPagePropertyAction.html) |
| OK | `XEsGetProjectPropertyAction` | `properties.get_project_property` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsGetProjectPropertyAction.html) |
| OK | `XEsGetPropertyAction` | `properties.get_property` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsGetPropertyAction.html) |
| OK | `XEsSetPagePropertyAction` | `properties.set_page_property` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsSetPagePropertyAction.html) |
| OK | `XEsSetProjectPropertyAction` | `properties.set_project_property` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsSetProjectPropertyAction.html) |
| OK | `XEsSetPropertyAction` | `properties.set_property` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XEsSetPropertyAction.html) |
| OK | `XGedClosePage` | `navigation.close_pages` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XGedClosePage.html) |
| OK | `XGedUpdateMacroAction` | `macros.update_macros` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XGedUpdateMacroAction.html) |
| OK | `XMActionDCCommonExport` | `data_exchange.dc_export` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMActionDCCommonExport.html) |
| OK | `XMActionDCImport` | `data_exchange.dc_import` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMActionDCImport.html) |
| OK | `XMExportConnectionsAction` | `data_exchange.export_connections` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportConnectionsAction.html) |
| OK | `XMExportDCArticleDataAction` | `data_exchange.export_dc_article_data` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportDCArticleDataAction.html) |
| OK | `XMExportFunctionAction` | `data_exchange.export_functions` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportFunctionAction.html) |
| OK | `XMExportLocationBoxesAction` | `data_exchange.export_location_boxes` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportLocationBoxesAction.html) |
| OK | `XMExportPagesAction` | `data_exchange.export_pages` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportPagesAction.html) |
| OK | `XMExportPipeLineDefsAction` | `data_exchange.export_pipeline_definitions` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportPipeLineDefsAction.html) |
| OK | `XMExportPotentialDefsAction` | `data_exchange.export_potential_definitions` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XMExportPotentialDefsAction.html) |
| OK | `XPamSelectPart` | `parts.select_part` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XPamSelectPart.html) |
| OK | `XPamsDeviceSelectionAction` | `interaction.select_device` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XPamsDeviceSelectionAction.html) |
| OK | `XPlaUpdateDetailAction` | `planning.update_detail_engineering` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XPlaUpdateDetailAction.html) |
| OK | `XPrjActionUpgradeProjects` | `project.upgrade_projects` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XPrjActionUpgradeProjects.html) |
| OK | `XPrjConvertBaseProjectsAction` | `project.convert_base_projects` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XPrjConvertBaseProjectsAction.html) |
| OK | `XSDPreviewAction` | `navigation.preview_page` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XSDPreviewAction.html) |
| OK | `XSettingsExport` | `settings.export_settings` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XSettingsExport.html) |
| OK | `XSettingsImport` | `settings.import_settings` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XSettingsImport.html) |
| OK | `XSettingsRegisterAction` | `addons.register_addon` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XSettingsRegisterAction.html) |
| OK | `XSettingsUnregisterAction` | `addons.unregister_addon` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/XSettingsUnregisterAction.html) |
| OK | `backup` | `backup.backup_project, backup.backup_masterdata` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/backup.html) |
| OK | `changelayer` | `layers.change_layer` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/changelayer.html) |
| OK | `check` | `verify.check_project, verify.check_pages, verify.check_parts` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/check.html) |
| OK | `compress` | `project.compress_project` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/compress.html) |
| OK | `devicelist` | `devicelist.export_device_list, devicelist.import_device_list, devicelist.delete_device_list` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/devicelist.html) |
| OK | `edit` | `navigation.edit_open_page, navigation.edit_goto_device, navigation.edit_open_layout_space` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/edit.html) |
| OK | `exportToGraphics` | `export_.export_to_graphics` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/exportToGraphics.html) |
| OK | `gedRedraw` | `navigation.redraw_ged` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/gedRedraw.html) |
| OK | `generate` | `generate.generate_connections, generate.generate_cables` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/generate.html) |
| OK | `graphicallayertable` | `layers.export_graphical_layer_table, layers.import_graphical_layer_table` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/graphicallayertable.html) |
| OK | `import` | `import_.import_pxf_project, import_.import_dwg_page, import_.import_dxf_page, import_.import_dxfdwg_files, import_.import_pdf_comments` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/import.html) |
| OK | `label` | `labels.create_labels` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/label.html) |
| OK | `navigateToEEC` | `navigation.navigate_to_eec` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/navigateToEEC.html) |
| OK | `partslist` | `parts.export_parts_list, parts.import_parts_list` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/partslist.html) |
| OK | `partsmanagementapi` | `partsmanagement.partsmanagement_export, partsmanagement.partsmanagement_import, partsmanagement.partsmanagement_export_by_properties, partsmanagement.partsmanagement_export_all` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/partsmanagementapi.html) |
| OK | `plcservice` | `plc.plc_export, plc.plc_import` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/plcservice.html) |
| OK | `preparemacros` | `macros.prepare_macros` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/preparemacros.html) |
| OK | `print` | `print_.print_project, print_.print_pages` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/print.html) |
| OK | `projectmanagement` | `project.project_management` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/projectmanagement.html) |
| OK | `renumber` | `renumber.renumber_devices, renumber.renumber_pages, renumber.renumber_cables, renumber.renumber_terminals, renumber.renumber_connections` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/renumber.html) |
| OK | `reports` | `reports.update_reports, reports.update_model_view_pages, reports.create_model_views, reports.create_copper_unfolds, reports.create_drilling_views` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/reports.html) |
| OK | `restore` | `backup.restore_project, backup.restore_masterdata` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/restore.html) |
| OK | `search` | `search.search_devices, search.search_text, search.search_all_properties, search.search_page_data, search.search_project_data` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/search.html) |
| OK | `selectionset` | `navigation.get_selected_pages, project.get_current_project` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/selectionset.html) |
| OK | `subprojects` | `data_exchange.export_subproject, data_exchange.import_subproject` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/subprojects.html) |
| OK | `synchronize` | `project.synchronize_project` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/synchronize.html) |
| OK | `translate` | `translate.translate_project, translate.export_missing_translations, translate.remove_language` | [doc](https://www.eplan.help/en-US/infoportal/content/api/2027/translate.html) |
