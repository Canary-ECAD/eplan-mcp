# LLM Operating Guide — EPLAN AI Automation Toolkit

This file tells you (the LLM) what this toolkit lets you **do** and **configure**.
It assumes you are connected through one or more of the MCP servers described here.

The local `eplan` action server is maintained in this repository. The three
Cloudflare documentation RAG servers are maintained separately in
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags):
[P8 2026](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-p8),
[P8 2027](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027),
and [EEC Pro 2026](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eecpro).
The [eplan-scripting skill](https://github.com/Canary-ECAD/eplan-scripting-skill)
also has its own repository.

Human-readable guides: [English](README.md) · [Español](README.es.md) ·
[한국어](README.ko.md) · [Deutsch](README.de.md) ·
[中文](README.zh-CN.md) · [Русский](README.ru.md).

---

## 1. What you are connected to

There are up to **four MCP servers**, each a different capability:

| MCP server | Kind | What it lets you do |
|------------|------|---------------------|
| `eplan` (local) | Action server | **Control a running EPLAN Electric P8 instance** — open/close projects, export, import, reports, checks, renumber, parts DB, settings, run C# scripts, etc. |
| `eplan-rag` (remote) | Knowledge | **Look up the EPLAN P8 API** (2026 docs, actions/classes/properties/parameters) via **semantic search** (Vectorize + bge-base). |
| `eplan-wiki-2027` (remote) | Knowledge | **Look up the EPLAN P8 API** (2027 docs) via **keyword/full-text search** (SQLite FTS5 + bm25). Prefer this over `eplan-rag` when you already know or can guess the exact class/method/property name — measured head-to-head, FTS5 wins that case and semantic search wins only when the query shares no vocabulary with the docs at all. |
| `eecpro-rag` (remote) | Knowledge | **Look up the EPLAN EEC Pro 2026** documentation via semantic search. |

If `eplan-rag`/`eplan-wiki-2027` aren't connected, you can still query them over REST:
`POST https://rag2026.covaga.xyz/search` (semantic, 2026) or
`POST https://rag2027.covaga.xyz/search` (keyword, 2027), body `{"query": "...", "topK": 5}`.
Use one of these whenever you are unsure of an exact action name or parameter —
**do not guess EPLAN action parameters**.

---

## 2. The local `eplan` action server

It exposes **282 tools** (full tool-by-tool reference: [covaga.dev/docs/tools](https://covaga.dev/docs/tools/project-and-workspace-management/)):

- **7 script-host tools** (`eplan_script_hello`, `eplan_script_run`,
  `eplan_script_status`, `eplan_script_cancel`, `eplan_script_list`,
  `eplan_script_offline_stop`, `eplan_script_host_install`): typed C#
  run inside EPLAN with no rebuild and no restart. See "Escape hatches" below;
  prefer them to `eplan_execute_custom_script` for anything that reads or writes
  the data model. The script library also ships ready-made object tools (texts,
  line styles, functions, macro boxes, parts snapshots): run them with
  `eplan_script_run(script="<name>")`, or set `EPLAN_MCP_SCRIPT_TOOLS=publish` to
  get each as its own `eplan_<name>` tool. Those that write default to
  `dry_run=True`, write only to scratch clones, take handles from their read
  tool, and need a `limit` for bulk changes (see dotnet/SCRIPTING.md).
  `eplan_script_run` itself defaults to `dry_run=False`: pass `dry_run=True` to preview.
  Library scripts (name: args; `*` = required):
  - Texts: `text_placements` (page*, symbol_prefix, include_free_texts),
    `text_set_height` (page*, handle*, height | factor, target=height|font_size, allow_shared;
    the height and font size of a property text shown from its symbol variant are always refused, use
    `text_set_box` or make the placements local in EPLAN),
    `text_set_box` (page*, handle*, has_box, box_fixed_width, box_fixed_height,
    fitting_permitted, never_hyphenate, remove_breaks, box_width, box_height, allow_shared),
    `text_create` (page*, text* not blank, x*, y*, height, debug).
  - Lines: `line_styles` (page*, x0, y0, x1, y1: all four or none, limit),
    `line_styles_set` (page*, x0*, y0*, x1*, y1*, limit*, style, factor, width).
  - Functions: `function_move` (page*, moves*: [{handle | name, x, y}]),
    `function_remove` (page*, names*, symbol_prefix*).
  - Snapshots: `macrobox_snapshot` (out), `macrobox_restore` (snapshot*, limit*,
    update_existing, allow_other_project, out), `parts_snapshot` (page_prefix, out),
    `parts_restore` (snapshot*, limit*, page_prefix, promote_main, allow_other_project, out;
    matches by object id when the snapshot is from the same project, else by page, full device
    tag, function definition, symbol and connection points; ties are refused and listed with their
    candidates in the out file).
  - Expected refusals (missing argument, unknown page, wrong snapshot) come back as
    `success: false` with a plain `error`, never a stack trace.
  - Read inspectors: `project_info` (also offline), `page_inspect` (page, max, include),
    `page_property` (page*, ids, names, index), `function_inspect` (page, device_tag, max,
    with_id), `function_dump` (dt*, page, max, fields), `unplaced_functions` (symbol_prefix*,
    max), `cable_shields` (dt, max), `layer_table`, `symbol_library_inspect` (library*,
    mode=symbols|variant|arrangements, symbol, variant), `macrobox_links` (pages*, out),
    `macro_prepare_inspect` (pages*, out), `read_selection` (GUI).
  - Selection: `set_selection` (pages, page, select_all_on_page, clear; writes the selection only).
- **8 connection/utility tools**: `eplan_versions`, `eplan_servers`,
  `eplan_connect`, `eplan_status`, `eplan_ping`, `eplan_test`,
  `eplan_disconnect`, `eplan_list_extensions`.
- **259 EPLAN action tools** → `eplan_<action>` (e.g. `eplan_open_project`).
  Includes 2 Data Portal tools that use EPLAN's own Data Portal sign-in:
  `eplan_dataportal_search_count` (read-only) and
  `eplan_dataportal_add_to_download_list`, which only *queues* parts - the
  download is a dialog in EPLAN, so its result carries a `userAction` the model
  must relay to the user before waiting on the import. On EPLAN 2025 queuing
  opens EPLAN's Data Portal window and the action only finishes once the user
  closes it, so the tool runs the action from a timer after its script returns
  and comes back within a few seconds with `status: "dataportal_window_open"`
  and `executed: null`: the user checks the download list in that window,
  downloads it and closes it. Do not queue the same parts again; a request made
  while that window is open is refused (`errorType: "DataPortalWindowOpen"`)
  without reaching EPLAN, and the next call reports the earlier verdict in
  `earlierResults`. While the window is open EPLAN takes no other commands
  (`eplan_ping` still answers): those calls return `EplanBlockedByDialog`, whose
  `next_step` says to have the user finish in that window, not to click it.
  Both are flagged
  `network` (`openWorldHint: true`): they reach the Data Portal.
  Includes 3 tools that work **only on EPLAN 2027 and later**, built on API
  members new in 2027: `eplan_live_read_terminal_jumpers` (terminal
  jumpers/bridges via `Terminal.GetJumpers`), `eplan_parts_db_export_edz`
  (export named parts, with their referenced data, to an EDZ file) and
  `eplan_remove_unused_user_properties` (preview, then remove unused
  user-defined property definitions from the project or the parts database;
  removing needs `confirm=True`, plus `allow_real_project=True` outside the
  scratch root for a project). Connected to an older EPLAN they return
  `errorType: EplanVersionUnsupported` at once, without running anything.
  Includes `eplan_live_set_target_project` (pin every later call to one open
  project by its .elk path - reflection scripts then pick it from
  `ProjectManager.OpenProjects` and action wrappers fill an omitted
  `PROJECTNAME` with it, so the user clicking another project in EPLAN cannot
  redirect a write; set it right after opening the project) and 10 batched
  page-operation tools built on ONE C# interpreter that runs a list of ops in
  one script: `eplan_live_batch` (ops: place, rect, macro, update, move,
  remove, dimension, line, text - a free page text, bilingual with
  "es_ES@..;en_US@..;" -, find, read; objects addressed by handle, by device
  tag, or by `$label` of an earlier op), `eplan_live_find_placements` (by tag -
  handles do not survive an EPLAN restart, tags do), `eplan_live_place_device`
  (place + tag + part + properties + function definition in one go; terminals
  and PLC points fall back to the 2-arg Create automatically),
  `eplan_live_insert_macro` (a window macro by insertion point or top-left
  corner, devices tagged), `eplan_live_place_panel_item` (the part's 2D macro,
  or EPLAN's rectangle fallback), `eplan_live_place_plc_point` (DI/DO/PS/CPS
  with the right FunctionDefinition), `eplan_live_place_terminal`,
  `eplan_live_update_placement` (tag/part/properties on an existing object; a
  duplicate tag is refused unless allowed), `eplan_live_render_page` (export
  the page to PNG to look at it) and `eplan_live_check_page` (page check +
  itemized messages + overlapping outlines/texts + duplicate wire labels, in
  one call). Every write is scratch-only unless `allow_real_project=True`.
  Includes 5 discovery tools (`eplan_settings_list_children`,
  `eplan_list_schemes`, `eplan_list_report_templates`, `eplan_list_layers`,
  `eplan_list_enums`) that enumerate real EPLAN catalogs instead of guessing,
  3 dialog tools (`eplan_list_dialogs`, `eplan_click_dialog_button`,
  `eplan_dialog_history`) that read, dismiss and remember EPLAN's prompts
  straight from Windows, so they still work while a modal blocks every other
  call,
  8 live-DataModel tools (`eplan_live_query_functions`,
  `eplan_live_query_pages`, `eplan_live_plc_io_list` (the PLC I/O
  assignment list as JSON: identifier split into =/+/- parts, address,
  symbolic address, data type, function text per language, module, page,
  plus the PLC boxes with CPU/rack/slot/device name),
  `eplan_live_set_function_text`,
  `eplan_live_set_connection_designations`,
  `eplan_live_read_check_messages`, `eplan_live_scale_text`,
  `eplan_live_set_layer`) that read/edit the open project's
  object model via runtime reflection (see §4 below) - the last of these reaches
  a different namespace still (`Eplan.EplApi.EServices.PrjMessagesCollection`,
  the itemized "Message management" results a check run produces, which
  `eplan_get_system_messages` cannot see), 2 API-introspection tools
  (`eplan_api_types`, `eplan_api_describe`) that ask the loaded object model
  what it declares - namespaces, types, member signatures, property
  read/write access and enum numeric values - using the same reflection but
  no project and no LockingStep, since they read metadata rather than data.
  They exist because the CS0234 block is compile-time only: all 26
  `Eplan.EplApi.*` namespaces / 606 public types are reachable at runtime, so
  writing against this API means looking members up constantly, and the
  alternative was a hand-written throwaway script per question. Deliberately
  2 tools and not a wrapper per class - same call as the action catalog
  below, for the same reason. 12 schematic-authoring
  tools on that same reflection scaffold (`eplan_live_symbol_catalog`,
  `eplan_live_create_page`, `eplan_live_place_symbol`,
  `eplan_live_connect_pins`, `eplan_live_read_page`,
  `eplan_live_remove_placement`) that CREATE a schematic rather than only
  reading one - every write returns the page read-back as proof and an undo
  handle, and writes refuse a project outside the scratch root unless
  `allow_real_project=True`, plus `eplan_live_verify_page` (check a page against
  a description written in live_read_page's own schema, so the read format
  doubles as the specification format) and `eplan_live_set_device_tag` (a placed
  function is anonymous until tagged; a duplicate tag is refused by default
  because it would MERGE devices) and `eplan_live_read_connections` (the LOGICAL
  connections - what is actually wired to what, as opposed to where a line was
  drawn; read-only, and it reports when connections look ungenerated rather than
  letting an empty list read as "nothing is wired"; `device=` scopes it to one
  device or terminal strip, and it reports `CONNECTION_TYPE`, where 5 is
  "Jumper (automatic)" - `kindOfWire` cannot tell you that, its five members are
  IndividualConnection/Cable/Conduit/PhaseBusbar/Line) and
  `eplan_live_read_terminals` (a terminal strip's terminals with every
  jumper-bearing property EPLAN keeps on them - the saddle jumper option
  #20808, the manual jumper crests, the switching jumpers, and the sort
  code/level that order a strip; these live on the TERMINAL, not on the
  connection, so no amount of connection reading reaches them) and
  `eplan_live_connect_pins_routed` (a drawn line through a right-angled corner,
  for the diagonal case where devices share neither axis - NOT the way to wire a
  straight run, which needs no object at all) and the connection-symbol tools
  (`eplan_live_routing_catalog`, `eplan_live_place_connection_symbol`,
  `eplan_live_place_corner`, `eplan_live_place_tnode`,
  `eplan_live_place_connected` - place a device already lined up to autoconnect
  with a pin on the page, so the caller never computes a millimetre) - EPLAN wires two facing
  pins on a shared axis with an autoconnecting line and no object, so what
  actually has to be PLACED is the corners and branches, and which symbol that
  is has to be discovered rather than assumed: one measured project carries 24
  connection symbols, including two different `TNodeUp` symbols and five
  same-direction `TLRU` variants whose pins sit in different places, so these
  tools refuse to guess between rivals and report the geometry instead),
  and 5 convention-profile tools
  (`eplan_profile_learn`, `eplan_profile_list`, `eplan_profile_get`,
  `eplan_profile_suggest`, `eplan_profile_forget`) that learn how a GO-BY
  project builds schematics - which symbol it uses for each device kind, its
  tag and page-naming shapes, its grid and spacing - so generated work matches
  the house standard. Learning accumulates rather than overwriting, so a
  profile sharpens with each project it sees; profiles are stored OUTSIDE the
  repo (EPLAN_MCP_PROFILES) because a client's conventions are customer data, application lifecycle
  control (`eplan_app_launch`, `eplan_app_shutdown`, `eplan_app_restart` —
  full exit/relaunch/reconnect/reopen cycles for unattended add-in
  deploy-test loops), scratch project fixtures
  (`eplan_scratch_project_create` / `_discard` / `_list` — disposable clones
  of a template project; deletion is confined to the scratch root), an
  add-in development loop driven by a manifest an extension registers by name
  (`eplan_addin_build`, `eplan_addin_deploy`, `eplan_addin_update` - build,
  shut EPLAN down, deploy, relaunch, verify the actions registered; deploy and
  restart are opt-in, `do_deploy=True` / `restart=True`, only when the user
  asked - and `eplan_list_addin_actions`, a static scan of the add-in's C# for
  its action names), scratch symbol-library
  isolation (`eplan_scratch_symbols_create` / `_restore` / `_purge` /
  `_status` and `eplan_assert_isolation` - redirect $(MD_SYMBOLS) at copies so
  a symbol-writing test cannot reach the real libraries; the gate needs a
  library reader an extension registers), out-of-process UI Automation
  (`eplan_ui_drive`, `eplan_ui_dismiss_watch_start`,
  `eplan_ui_dismiss_watch_stop`: drive WinForms dialogs and arm a modal dismisser BEFORE a blocking action;
  window lookups match EPLAN's own windows unless `process` names another;
  dialog presets come from extensions), and
  `eplan_get_system_messages` (read EPLAN's system message tree — the same
  errors/warnings the user sees in the GUI's system messages dialog).
- **4 action-catalog tools** reaching the ~1,050 further EPLAN actions that
  exist only as GUI buttons (mined from the install's `MFTools.xml`, not
  documented, not individually wrapped — publishing one tool per action would
  have tripled the tool count): `eplan_action_catalog(search, category,
  documented_only, wrapped, available_only, limit)` to search the ~1,150-action
  registry offline, `eplan_action_describe(name)` for a registry entry + live
  `FindAction` probe, `eplan_action_run(name, params, dry_run,
  allow_unknown_params)` for validated dispatch of *any* action (rejects
  unknown names/params, with an escape hatch since many registry params are
  observed rather than documented — supersedes `execute_raw_action` for
  actions already in the registry), and `eplan_ribbon_catalog(tab, search)` to
  browse the live GUI ribbon tree and resolve a button to the action it runs.
  `available_only=True` on `action_catalog` restricts to actions the live
  probe found registered on this installation — that is necessary, not
  sufficient: `FindAction` resolving an action means its module is *loaded*,
  not that it is *licensed* to run (module licensing is enforced at
  execution time). Confirm by actually running the action.
- **4 Asset Administration Shell tools** → `aas_<action>`
  (`aas_export_part`, `aas_export_project`, `aas_inspect_package`,
  `aas_import_parts`) for AAS/AASX digital-twin export and import.

The EPLAN version is auto-detected (newest installed). If the user wants a
specific version, call `eplan_versions` to list what is installed, then
`eplan_connect(version="2026")`. Decide the version BEFORE the first connect —
once one version's DLLs are loaded, switching requires restarting the server.

Every action runs inside a C# script in EPLAN's process under `QuietMode`
(no dialogs). It is silent, safe for unattended/batch use, and returns values
EPLAN wrote back to the calling context (e.g. `PROJECT`, `PAGES`).

Each tool already carries its own description and parameter schema (generated
from the Python docstring + type hints). **Read the tool's own description before
calling it** — this guide is the map, the tool schemas are the territory.

### Result shape

Tools return JSON. Actions typically return:

```json
{ "success": true, "parameters": { "PROJECT": "C:\\...\\Proj.elk" } }
```

`success: false` with a `message`/`error` means the EPLAN action itself failed —
read the message; it usually points at a bad parameter or a missing precondition
(e.g. no project open).

**A call that did not complete** carries one of three `errorType`s and a
`next_step` to follow:

- `EplanBlockedByDialog` — EPLAN stopped at a prompt (it is in `dialogs`).
- `EplanActionTimeout` — no answer within `EPLAN_MCP_ACTION_TIMEOUT` (600 s).
- `EplanBusy` — an earlier abandoned call is still running, so this one was not sent.

In all three the result is **unknown**: EPLAN may still finish the call. Do not
retry blindly. `eplan_list_dialogs` reads EPLAN's windows from Windows (it works
while EPLAN is blocked), and `eplan_click_dialog_button` answers one — by
default only OK, Cancel, Close, No or Skip, in any language. Show the user the
dialog's text when the answer is theirs to give, then check the state (e.g.
`eplan_get_current_project`) before carrying on.

`success: true` from a directly-executed utility (`ExecuteScript`) only means
EPLAN accepted the call. Generated scripts are one-shot `[Start]`-only classes
run via `ExecuteScript` alone — they are deliberately **not** passed through
`RegisterScript`/`UnregisterScript` (that pair is for installing a script's
persistent `[DeclareAction]`/`[DeclareEventHandler]`/`[DeclareMenu]` hooks,
which these scripts don't have; registering them anyway just produced a
spurious "script does not contain attributes for loading" warning in
EPLAN's own UI and two wasted remote-API round-trips per call).

---

## 3. Standard workflow

1. **Check / connect first.** Call `eplan_status` (or `eplan_servers` →
   `eplan_connect`). Almost every action needs an open connection. Port and
   EPLAN version are auto-detected; pass `version` only if the user asks for a
   specific one. If `eplan_servers` returns `[]` the connection usually still
   works — that empty list is a known limitation (especially right after EPLAN
   starts), not a failure: `eplan_connect` falls back to the TCP ports
   EPLAN.exe actually listens on (read from Windows' TCP table, so it works in
   any Windows language), then the default 49152. To
   reach EPLAN on another machine pass `host` (port required then).
2. **Pick the project context.** Most actions take an optional `project_name`. If
   omitted, EPLAN uses the **currently selected/open** project. Use
   `eplan_get_current_project` to confirm what that is.
3. **Call `eplan_<action>`** with the parameters from the tool schema.
4. **Verify unknowns via the RAG** before constructing raw actions or custom
   scripts.
5. **Report results** from the returned JSON honestly (including `success: false`).

---

## 4. What you can DO (capability map)

All of these exist as `eplan_*` tools:

- **Projects:** open, close, get current, compress, synchronize, upgrade, set
  language, switch type, project management tasks.
- **Backup / restore:** projects and master data.
- **Export:** PDF (project/pages), DXF/DWG (project/pages, by scheme), graphics
  (PNG/TIF/…), PXF/EPJ, 3D.
- **Import:** PXF projects, DXF/DWG into pages or as macros, PDF comments, 3D.
- **Print:** project or pages.
- **Check / verify:** project, pages, parts (with verification schemes).
- **Generate:** connections, cables.
- **Reports / evaluations:** `eplan_live_report_types` (the DocumentType
  names + the report pages the project already has) and
  `eplan_live_create_report` (add a cover sheet / parts list / terminal
  diagram / panel legend ... with a given form and generate its pages; the
  form must already be in the project master data, else S029153 with a
  hint), update reports, model views, copper unfolds,
  drilling views.
- **Search:** devices, texts, all properties, page data, project data.
- **Navigation / editing:** open page, go to device, open layout space, close
  pages, get selected pages, page/macro preview, navigate to EEC.
- **Renumber:** devices, pages, cables, terminals, connections.
- **Translate:** translate project, export missing translations, remove language.
- **Device lists, labels, graphical layers, macros.**
- **Settings & properties:** import/export settings, set settings, get/set
  project / page / object properties, user properties.
- **Parts:** export/import parts lists, part selection, data source, full parts
  management API export/import.
- **PLC:** bus data export/import via converters.
- **Workspace:** open/save/clean (needs the EPLAN GUI/mainframe).
- **Data exchange:** connections/functions/pages export for external editing,
  data-configuration import/export, potential/pipeline definitions, subprojects,
  master data operations.
- **Cabinet / 3D:** cabinet weight, segment filling, topology, pre-planning data,
  segment templates.
- **Production:** NC data, production wiring.
- **Ribbon & add-ons:** export/import ribbon bar, load API module, register/
  unregister add-on, `execute_raw_action` for any action not wrapped, and
  `verify_actions` (which action names EPLAN actually registered - the
  post-deploy check, since EPLAN swallows add-in load failures).
- **Export verification (host-side, no EPLAN needed):** `pdf_inspect` (page
  count, GoTo links, outline, page labels) and `dwg_inspect` (layouts, texts,
  entity counts; DXF natively, DWG via AutoCAD's accoreconsole).
- **Navigator focus:** `navigator_select` focuses an open project (and
  selects pages) so selection-driven tools act on it, not on whatever the
  user last clicked.
- **Scripted advanced APIs (run as C#):** direct **parts database** queries
  (`parts_db_*`; `eplan_parts_db_get_part` also returns every filled record
  property - ARTICLE_NOTE with the manufacturer's technical text, voltages,
  pressure, PLC station type - and the function templates), **typed settings** get/set
  (`settings_get/set_string|bool|int|double`), **PathMap** variable substitution,
  and `execute_custom_script` to run arbitrary C# inside EPLAN.
- **Live DataModel (read/edit the open project via reflection):**
  `eplan_live_query_functions`, `eplan_live_query_pages` (read, with substring
  filter + result limit), `eplan_live_plc_io_list` (read: every PLC
  connection point with address, symbolic address, data type, channel,
  function text per language, page and module, grouped by =installation so
  repeated stations map to an array index; use it before `eplan_plc_export`
  when the PLC programmer only needs the list, not a TIA import file),
  `eplan_live_panel_captions` / `eplan_live_set_panel_captions` (the
  property texts next to a panel item - tag, part, type, legend index -
  with their boxes in page mm; hide/show/move them and set the legend
  position, always on a LOCAL property arrangement so other items are not
  dragged along),
  `eplan_live_copy_pages_to_structure` (repeated stations: copy drawn
  pages to =ST2, =ST3 ... and retag every device on the copies, keeping the
  shared ones such as the CPU; wire numbers and PLC addresses are copied
  as-is and must be renumbered afterwards),
  `eplan_live_terminal_strips` (every strip with its terminal count and
  whether it has a terminal strip definition) and
  `eplan_live_set_terminal_strip_definition` (create the missing
  definition - unplaced, or placed as SPECIAL/TDEF on a page - with text
  and part; PLC connection points are not strip terminals),
  `eplan_live_cables` (cables with their conductors: wire number, colour,
  cross-section, source, target), `eplan_live_place_cable_definition`
  (draw the cable definition line across wires, name it with the page's
  structure, then assign the crossed connections and regenerate; keep the
  line clear of the wire-number symbols) and
  `eplan_live_assign_cable_connections` (re-run the geometric assignment
  for a line placed by hand or moved: EPLAN does not assign conductors to
  an API-placed line on its own),
  `eplan_live_project_templates` (the .zw9 basic projects / .ept templates
  under $(MD_TEMPLATES)) and `eplan_live_create_project` (new project from
  one of them via ProjectManager.CreateProject, left open and set as the
  target; the path must be under the scratch root unless
  allow_real_project),
  `eplan_live_set_function_text` (write `FUNC_TEXT`,
  defaults to one function at a time, returns the previous value),
  `eplan_live_set_connection_designations` (write the indexed
  `FUNC_CONNECTIONDESIGNATION` property, re-reads after writing to confirm),
  `eplan_live_read_check_messages` (page through the itemized "Message
  management" results of the last check run — `Eplan.EplApi.EServices.
  PrjMessagesCollection` — by 1-based index, matching the order EPLAN's own
  dialog lists them in; `eplan_get_system_messages` only ever sees the two
  summary lines a check run appends, never the individual entries),
  `eplan_live_scale_text` (multiply every text height in the GED selection or on
  a named page by a factor — dry-run by default, skips the `-16002` "from layer"
  sentinel and texts shared with a symbol variant, reverses with `1/factor`),
  `eplan_live_set_layer` (move the selection or a page onto one layer - default
  `EPLAN100` - and hand colour/line width back to that layer via the same
  `-16002` sentinel; dry-run by default, reports the layers the objects came
  from), and the generic pair `eplan_live_objects_read` / `eplan_live_objects_edit`
  (find functions, connections, pages or macro boxes project-wide, in the focused
  project or any open one via `project` - for the selection use
  `eplan_get_property`/`eplan_set_property` - filter on any
  property - id, `id:index`, user-defined name, or name/page/type/handle/partNr/area -
  then read any properties, or write them and/or re-apply master part data with
  `update_from_part`; edit is dry-run by default). Reach for these before
  writing a new single-purpose live tool.
  These reach `Eplan.EplApi.DataModel`/`HEServices`/`EServices` types via
  `AppDomain.CurrentDomain.GetAssemblies()` + `Assembly.Load` fallback instead
  of a static `using`, because that `using` doesn't compile in EPLAN's script
  engine (CS0234) and, separately, the managed assembly names changed
  (`Eplan.EplApi.DataModelu` → `...DataModelNetu`) starting with EPLAN 2025/2027
  — a hardcoded old name throws `BadImageFormatException` on newer installs.

### Escape hatches

- **`eplan_script_run(code=... | script=..., args=..., project=...)` — the
  preferred way to do anything the tools above do not cover.** Write ordinary,
  typed C# against the EPLAN API: `using Eplan.EplApi.DataModel;` works here
  (the host compiles with the full reference set; CS0234 is a limit of EPLAN's
  own script engine only). A bare statement body is enough:
  `var p = ctx.RequireProject(); return new DMObjectsFinder(p).GetPages(null).Length;`.
  - `ctx` gives `Project`, `Args` (`String`/`Int`/`Bool`/`List`),
    `Budget.Check()` (call it in every long loop: it is the only way a run can
    stop), `Progress()`, `Log()`, `Lock(obj)`, `DryRun`, `WriteAllowed`.
    Return plain data. The run already holds a `LockingStep`.
  - Works on EPLAN 2026 (host flavor `netfx`, .NET Framework) and 2027+
    (`net8`); the server picks the target EPLAN's. On 2026 a script cannot be
    unloaded: it stays loaded until EPLAN closes (`unloaded` is null), and the
    same script run again reuses it, so prefer saved library scripts with
    arguments over many one-off variants. `#if NETFRAMEWORK` works in scripts.
    EPLAN 2025 and older are refused.
  - Call `eplan_script_hello` once first: it reports the host version, which
    runtime answers (`addin`, else `bootstrap`), the framework and flavor, the
    EPLAN version and the license. Every runtime (add-in, bootstrap, offline) needs the EPLAN API
    developer license. `runtime="offline"` works on a closed `.elk` path with no
    EPLAN window, for scripts with `@needs offline` or `@needs either`.
  - **Writes:** declare `// @writes true`. Ad-hoc scripts may write only when
    the TARGET project is a scratch clone from `eplan_scratch_project_create`,
    and a writing script may touch only `ctx.Project` (no `ProjectManager`, no
    selection); other projects may stay open.
    A real project needs all of: `EPLAN_MCP_ALLOW_REAL_PROJECT_WRITES=1` in the
    server's environment (a person sets it in the MCP config; you cannot), a
    saved script in a script library folder, `allow_real_project=True`, and the
    `confirm_code` from a `compile_only=True` run of that script. **Show the
    `confirm_code` and what the script changes to the user and get their
    approval before passing it.** The scratch marker is a guard against
    mistakes, not a security boundary: a script is C# running in EPLAN.
    Read-only runs reject EPLAN writes at compile time.
  - Compile errors come back with your own line numbers and "did you mean"
    hints; fix and re-run (a warm compile takes milliseconds). Use
    `compile_only=True` to check without running.
  - Long runs return a `run_id`: follow with `eplan_script_status`, stop with
    `eplan_script_cancel`. `eplan_script_list` shows the script library;
    `dotnet/scripts/_template.cs` is the starting point for a new one.
  - `eplan_script_offline_stop` stops the offline host (`runtime="offline"`;
    it otherwise exits after 30 idle minutes).
  - No local `dotnet/` build (or one of the other flavor)? The host installs
    itself on first use from the GitHub release matching the server's version
    and the target EPLAN's flavor, checked against its SHA-256 sums; `eplan_script_host_install` does it explicitly and returns
    the `install_file` to register the add-in with `eplan_register_addon`.
    `eplan_script_hello` warns when the host's version differs.
- `eplan_execute_raw_action("ActionName /PARAM:value ...")` — run any EPLAN
  action string directly (still wrapped in QuietMode). Use after confirming the
  syntax with the RAG.
- `eplan_execute_custom_script(<C# code>, timeout_seconds=30.0)` — run a full
  C# script with access to `Eplan.EplApi.*`. Write results to
  `{{RESULT_PATH}}` as JSON. Raise `timeout_seconds` for scripts that walk
  large collections (e.g. reflection over every function/page in a big
  project); the default is tuned for small scripts, not bulk enumeration.
  **If the call times out, don't assume the script is slow or the collection
  is large** — a C# compile error (e.g. the `using Eplan.EplApi.DataModel;`
  trap above) means the script never ran and never wrote a result, which is
  indistinguishable from a hang on this end. Call
  `eplan_get_system_messages(min_level="Message")` first and look for a
  `CS####`-prefixed entry naming the generated `.cs` file before raising the
  timeout or suspecting RAM/project size (confirmed live: identical timeout
  on a 400-item and a 4-item project, same root cause both times).

---

## 5. What you can CONFIGURE

- **Target EPLAN version:** auto-detected (newest installed). Override per
  session with `eplan_connect(version="2026")`; list options with
  `eplan_versions`. Non-standard install path: set the `EPLAN_PLATFORM_ROOT`
  environment variable. Switching versions after DLLs are loaded requires a
  server restart.
- **Add a new action / tool:** implement a function in
  `api/actions/<module>.py`, export it in that package's
  `__init__.py` `__all__`, restart. It auto-registers as `eplan_<name>`. The
  docstring + type hints become the tool description and schema you will see.
  Then state what it does with one line in `TOOL_FLAGS`
  (`mcp_server/tool_annotations.py`, see §7) and regenerate `tools.json` with
  `python tools/dump_tools.py`; the test suite fails until both are done.
- **EPLAN settings at runtime:** via `eplan_set_setting` /
  `eplan_set_project_setting` (action params `set`/`value`/`index`) or the
  typed `eplan_settings_set_*` scripted tools.
- **The MCP registration itself:** `python python/install.py` (own `.venv`, registers `eplan`).

---

## 6. Caveats & gotchas

- **Never pass an action a file path under the long-form `AppData` folder.**
  `ExecuteScript /ScriptFile:"C:\Users\<user>\AppData\Local\..."` (or `...\Roaming\...`)
  is silently ignored on 2027.0.3: success is reported and nothing runs. Use a path
  under the user profile (`~\.eplan-mcp`), ProgramData, Documents or the 8.3-form
  TEMP. Measured 2026-11-10; see `dotnet/tests/live/results-2027.0.3.md`.

- **Connect before acting.** Unconnected calls return a "Not connected" error.
- **`project_name` is optional** — omitting it uses the selected project. Pass the
  full `.elk` path to be explicit. Windows paths must be escaped (`\\`) or use `/`.
- **GUI-only actions** behave poorly headless/under QuietMode: `redraw_ged`
  (returns FALSE in QuietMode) and the `workspace` actions (need a mainframe).
- **Property actions on project/page** (`get/set_project_property`,
  `get/set_page_property`) act on the **current project / selected page(s)** and
  use `PropertyId`/`PropertyIndex`/`PropertyValue` — they do not take a project
  or page name.
- **`selectionset`** valid `TYPE` values are `PROJECT`, `PROJECTS`, `PAGES`,
  `LAYOUTSPACES` only.
- **Don't invent parameters.** When unsure, query the RAG (`rag2026.covaga.xyz`)
  for the authoritative action page.
- **Custom C# scripts can't `using Eplan.EplApi.DataModel;`** — that statement
  doesn't compile in EPLAN's script engine (CS0234). Reach DataModel/HEServices
  types via reflection instead (see the `live_*` tools in §4), and don't
  hardcode the managed assembly name — it's `...Netu`-suffixed on EPLAN
  2025/2027, not the pre-2025 name.

---

## 7. Safety — confirm before destructive actions

Treat these as outward/irreversible and **confirm with the user first** unless
explicitly authorized: deleting pages or device/parts lists, closing a project
with unsaved changes, renumbering (devices/pages/cables/terminals/connections),
restore/backup overwrites, settings changes, `set_*_property`, raw actions, and
custom C# scripts. Read-only actions (status, search, get current project,
exports to new files, parts DB queries) are safe to run as needed.

### Tool annotations

You don't have to guess which is which: every tool states it. Each carries the
four standard MCP annotations, always set explicitly (`readOnlyHint`,
`destructiveHint`, `idempotentHint`, `openWorldHint`; the last is always false,
since nothing talks to anything but the local EPLAN), and EPLAN facts in its
`_meta` under the key `canary-ecad/eplan`:

| Fact | Meaning |
|---|---|
| `changesProject` | Writes the open project; back it up before the first such call |
| `runsCode` | Runs scripts, actions or add-ins it is given; what it does depends on its input |
| `changesEplan` | Changes EPLAN itself: settings, parts database, master data, ribbon, workspace, add-ins |
| `projectArgument` | Present when the tool has an argument naming the project (`project_name`, `project_path` or `project`) |

A tool with `readOnlyHint: true` changes nothing. Treat `destructiveHint`,
`runsCode` or `changesEplan` as "confirm every time". The facts are written by
hand in `mcp_server/tool_annotations.py` (`TOOL_FLAGS`, one line per tool);
`python/tools.json` is the published copy, attached to each
release (`vX.Y.Z` tags) together with the tools added, removed or re-annotated
since the previous one. Extension modules may give their tools facts with a
`TOOL_FLAGS = {"function_name": "flags"}` dict; without it they carry no
annotations, which means "may change anything".

These are facts, not policy: a client such as Bochica decides from them when to
ask, and may ask more often than they suggest.
