# Full EPLAN action coverage

Goal: let Claude drive EPLAN the way a human can — every API action *and* every
GUI button — without publishing one MCP tool per action.

Measured on a reference installation of **EPLAN Electric P8 2027.0.1**.
Counts below are transcribed from the committed data files rather than from a
past session's prose; `tests/test_coverage_counts_offline.py` fails if the two
drift apart again.

## The inventory

| Source | Count | What it is |
|---|---:|---|
| Official API docs (`api/2027/API Actions.html`) | 100 | "the list of all official Eplan API actions available for the user" |
| `Cfg/MFTools.xml` → `UsedActions` | 704 | GUI command id → full action command line (with real parameters) |
| `Cfg/MFTools.xml` → `ActionCategory` | 703 | rights-management grouping of GUI actions |
| `Cfg/MFTools.xml` → `Dialogs` | 157 | dialog-opening actions |
| **Union (registry total)** | **1150** | `mcp_server/api/actions/data/action_registry.json` |

Regenerate with `python tools/build_action_registry.py`. It is stdlib-only,
byte-stable (no timestamp), and degrades gracefully with a warning when
`MFTools.xml` is absent, so the repo stays portable to machines without EPLAN.

### What this install actually has

`ActionManager.FindAction(name, silent=true)` probed over all 1150 candidate
names (`tools/data/live_actions_2027.json`):

- **938 resolve** on that installation — registered and module loaded. This
  included all 100 documented actions there; on any other machine the set
  depends on which modules are installed and licensed, so treat the figure as
  a property of the reference installation and not of the API.
- 212 do not, and they are explained rather than mysterious:
  - 141 come only from the `Dialogs` section — those are **dialog ids**, not actions.
  - 46 are **GED interaction names** (values for `XGedStartInteractionAction /Name:`,
    not standalone actions) — extracted to `tools/data/ged_interaction_names.json`.
  - **7 are genuine gaps** on the reference installation: four
    `ExportActionPxc*` actions, which belong to a third-party add-on that was
    not present there, plus `XGedViewExternalDocumentAction`,
    `XSettingsProjCreateAllDescAction` and `XSettingsProjCreateDescAction`.
    An installation carrying that add-on will resolve the first four.

## How the actions are exposed

**Tier 1 — typed tools (101 actions, 183 `eplan_*` wrapper tools).** Fifteen documented
actions that had no wrapper were added following the existing convention
(`_build_action`, an `Action: <Name>` docstring line so `tools/validate_actions.py`
keeps working, exported from `api/actions/__init__.py`).

Ten of them were executed against a live EPLAN before being included (see
Testing):

`exportToGraphics`, `XCCreateGravingtextAction`, `XPrjConvertBaseProjectsAction`,
`ProjectAction`, `EplApiModuleActionNet`, `RegisterCustomPropertyEditorAction`,
`XGedStartInteractionAction`, `XDLInsertDeviceAction`, `XEGActionInsertSymRef`,
`XPamsDeviceSelectionAction`.

The remaining five ship as well, but **could not be exercised on the reference
installation**, so each one's docstring opens with a delimited `NOT VERIFIED`
block naming exactly what was and was not tested:

`InsertModelViewAction`, `XAMlExportProductionData2RASCenterAction`,
`XAMlExportProductionData2SmartMountingAction`, `XPlaUpdateDetailAction`,
`LockUnlockAllObjects` — see "Shipped but not live-verified" below.

**Tier 2 — catalog + validated dispatch (`catalog.py`), 4 tools** for the other
~1049. One tool per GUI action would have tripled the server's tool count and
degraded tool selection for everything else.

- `eplan_action_catalog(search, category, documented_only, wrapped, available_only, limit)`
  — offline registry search; always reports the true match count so a truncated
  list is never mistaken for the total. `available_only=True` restricts results
  to the actions the recorded probe found registered on the reference
  installation - advisory, not a licence check for the machine you are talking
  to - and every record carries `live_resolved` + `module_name`.
- `eplan_action_describe(name)` — registry entry + live `FindAction` probe
  (resolved? `ModuleName`?). Degrades to registry-only when disconnected.
- `eplan_action_run(name, params, dry_run, allow_unknown_params)` — validated
  dispatch for *any* action. Rejects unknown action names (with near matches) and
  unknown parameter keys, with an escape hatch because many registry params are
  observed rather than documented. Supersedes `execute_raw_action`.
- `eplan_ribbon_catalog(tab, search)` — the live GUI tree, tab → group → button.
  The full tree serialises to ~147,000 characters (past the tool-result cap), so
  it drills down: no arguments returns the tab index (~2.4 KB), `tab="Insert"`
  returns that tab's buttons (~20 KB), `search="macro"` finds a button by label
  across all tabs.

### The ribbon → action bridge

EPLAN documents `RibbonCommand.ActionCommandLine` as *"available only from a
custom command"*, and live testing confirmed built-in buttons return `""`. But
they do expose their **command id**, and `MFTools.xml/UsedActions` is keyed by
that same id. `build_action_registry.py` emits a `_command_index`
(1019 entries) and `ribbon_catalog()` joins against it.

Result, verified live: **352 of 361 ribbon buttons resolved** (9 unresolved).

```
Home  Clipboard  Paste          -> GfDlgMgrActionIGfWind /function:Paste
Home  Page       New            -> XPageNewDialogShow
Home  3D layout  New            -> XCabCreateInstallationSpace
```

So a button a human clicks can be found by name and then run with
`action_run()` — which is what "use EPLAN like a human" actually requires.

## Testing

**Offline: the whole suite runs with EPLAN closed.** Two tests skip: the
documentation
cross-check for `XAMlExportProductionData2SmartMountingAction` and
`LockUnlockAllObjects` — the only two wrapped actions whose EPLAN doc page 404s,
so there is no official parameter table to check their `/KEY`s against.

The highest-value assertions cross-check every emitted `/KEY` against
`tools/data/official_actions_2027.json` verbatim, and pin parameter **casing**
(`/NOCLOSE`, `/OpenMode`, `/PartNr`, `/Register`, `/ConfigScheme`,
`/Placementmode`, and the all-lowercase `register`/`registerModule` on
`EplApiModuleActionNet`). The wrapper test suite was mutation-checked: seeded
faults produced exactly the expected failures.

**Live (scratch only): every shipped wrapper except the five under
"Shipped but not live-verified", plus the catalog tier.**
Ran against a disposable clone of an EPLAN sample project in
`%TEMP%\eplan_mcp_scratch`, upgraded to the 2027 scheme. No project or master
data outside that scratch directory was written to.

| Action | Result | Note |
|---|---|---|
| `exportToGraphics` | PASS | 52 PNGs (project) + 2 (per-page). **`TYPE` is `GRAPHICPROJECT`/`GRAPHICPAGE`** — `PROJECT` raises *"This operation is not supported."* |
| `ProjectAction` | PASS | **Only works on a CLOSED project** — it opens the project itself. Against an open one: *"Project is already open."* |
| `XCCreateGravingtextAction` | PASS | |
| `XGedStartInteractionAction` | PASS | Needs an open page; returns immediately, does **not** block |
| `XEGActionInsertSymRef` | PASS | |
| `XPamsDeviceSelectionAction` | PASS | |
| `XDLInsertDeviceAction` | PASS | Opens the configured parts database **read-only** to resolve the part number |
| `action_catalog` / `describe` / `run` / `ribbon_catalog` | PASS | `describe` resolved `exportToGraphics` → module `Eplan.EplApi.CommandLineActionsNet` |
| `RegisterCustomPropertyEditorAction` | PASS | Registered and unregistered again (`/Register:1` then `/Register:0`); no state left behind |
| `EplApiModuleActionNet` | PASS | Reachable, lowercase `/register:` honoured, fails cleanly on a missing assembly. A successful load of a real .NET add-in was not exercised |
| `XPrjConvertBaseProjectsAction` | PASS | Ran against an isolated folder. No legacy `.ept`/`.epb` exists on this machine, so a real conversion was not exercised |

All four interaction-start actions were run with a UI dismiss watcher armed:
**0 modal dialogs appeared, and every call returned immediately** — safe to call
headless under QuietMode. `interaction.py` documents this measured behaviour
rather than the theoretical "may block" warning. The residual caveat is that a
call returning means the interaction was *started*, not finished: EPLAN is left
in that editor mode.

## Shipped but not live-verified

Five documented actions **are** wrapped and exported here, but their live
behaviour could not be exercised on the reference installation (EPLAN Electric
P8 2027.0.1, measured 2026-09-02/03). They ship marked rather than omitted: each
wrapper's docstring opens with a delimited `NOT VERIFIED` block stating what is
untested, the exact EPLAN error where one was seen, and what would be needed to
verify it. Their command-string construction *is* covered by
`tests/test_new_actions_offline.py` — what is unverified is EPLAN's response,
not the string the wrapper emits.

All five **do** resolve via `ActionManager.FindAction` on this installation:

| Action | Module |
|---|---|
| `InsertModelViewAction` | `Eplan.EplApi.CommandLineActionsNet` |
| `XAMlExportProductionData2RASCenterAction` | `AMLLog` |
| `XAMlExportProductionData2SmartMountingAction` | `AMLLog` |
| `XPlaUpdateDetailAction` | `PlanningLog` |
| `LockUnlockAllObjects` | `Eplan.EplApi.CommandLineActionsNet` |

So the actions exist here. Resolving is **not** proof of a licence — see the
caveat below.

| Action | Why it could not be verified |
|---|---|
| `InsertModelViewAction` | Needs a 3D layout space. Only the "Electric P8" variant is installed (`Electric P8/<ver>/Cfg/install.xml`), and `XCabCreateInstallationSpace` fails with *"New layout space function could not be run"*, so no fixture can be created. |
| `XAMlExportProductionData2RASCenterAction` | Same 3D prerequisite: *"Export manufacturing data (Rittal - RiPanel Processing Center) function could not be run"*. |
| `XAMlExportProductionData2SmartMountingAction` | Same 3D prerequisite (never executed; no error of its own was observed). Additionally it has **no documentation page at all**: 404 on eplan.help and absent from the 2027 API wiki (confirmed by sweeping all 98 action pages in the wiki index), so its parameters are **inferred** from the RAS Center sibling. If a call is silently ignored, wrong parameter names are the first suspect. |
| `XPlaUpdateDetailAction` | The Preplanning module **is** present and the action resolves, but every call fails (*"...action ... of the PlanningLog module has failed"*) because no available project contains preplanning objects. This is a **missing fixture, not a proven licence limit** — retest against a project that has preplanning data. |
| `LockUnlockAllObjects` | **Tested, and it does not work.** Marked deprecated on EPLAN's own action index, no doc page, and fails with *"Unable to gain access to the database"* whether or not a project is open. The cause is deprecation, not a licence. Prefer `set_setting` / `set_project_setting`. |

A contributor whose installation includes Pro Panel, or who has a project
containing preplanning data, can verify the first four and report back; the
docstrings say precisely what to run.

### Contributor report: EPLAN 2025.0.3 Electric P8 with Pro Panel (2026-09-03)

A second, independent installation (not the 2027.0.1 reference above — 2027.0.1
is not installed there) does have Pro Panel licensed, and was used to follow up
on exactly the invitation above. Numbers below are from that install; they do
not change or re-measure anything stated for the 2027.0.1 reference — read them
as a second data point, not a correction.

- **The 3D gate itself is not a general "Electric P8 lacks Pro Panel" limit —
  it's per-installation.** `XCabCreateInstallationSpace` (headless,
  `InstallationSpace.Create`) succeeded outright against a disposable scratch
  clone. So the prerequisite the four 3D/planning actions share is satisfiable
  on some Electric P8 installs, just not the one this document was measured
  against.
- **`XAMlExportProductionData2RASCenterAction`: executed, and it works.**
  Ran against the same scratch project with a real `FileName`; it produced a
  15.3 MB AutomationML file at the given path. This is the first live
  execution of this action recorded anywhere in this document — worth
  promoting out of "shipped but not live-verified" once the docstring's `NOT
  VERIFIED` block is updated to cite it.
- **`XAMlExportProductionData2SmartMountingAction`: executed, still fails.**
  `success:false`, no message surfaced (neither in the return value nor in
  `eplan_get_system_messages`) — consistent with the RAS Center sibling now
  working, this failure is *not* the 3D prerequisite. Given the action has no
  documentation page anywhere (confirmed above by the wiki sweep), the
  strongest remaining hypothesis is still what this doc already says: the
  inferred parameter name(s) are wrong, or the action name itself is not a
  real, callable action on this EPLAN version.
- **`XPlaUpdateDetailAction`: executed, returned `success:true` — but
  inconclusively.** The scratch project (a parts/3D-macro bulk-import
  project, not a preplanning one) had zero preplanning objects, same
  precondition gap as the reference install, but the *outcome differs*: a
  silent successful no-op here vs. a failure inside `PlanningLog` on the
  reference install. That discrepancy is itself worth a note in the
  docstring — a caller cannot currently tell "processed 0 objects
  successfully" apart from "processed some objects successfully" from the
  return value alone on at least one of the two installations.
- **`InsertModelViewAction`: still not exercised.** Not blocked by the 3D
  prerequisite this time (the gate works here) — blocked on finding an
  existing page name to pass as the mandatory `PAGENAME`, headless, without a
  reliable non-interactive page-listing or page-creation path in the current
  tool surface. `execute_custom_script` was tried for this and hit an
  unrelated, separately-reported issue (compile-error timeouts — see the
  `eplan-scripting` skill's `pitfalls.md` #9), so this one is a tooling gap
  in the test harness, not a finding about the action itself.

**An important caveat on availability data.** `ActionManager.FindAction`
resolving an action means its module is *loaded*, **not** that it is licensed to
run: module licensing is enforced at execution time. All five actions above
resolve. Three of them were actually executed and all three failed:
`XAMlExportProductionData2RASCenterAction` (consistent with run-time module
enforcement), `XPlaUpdateDetailAction` (missing preplanning fixture, not a
demonstrated licence limit) and `LockUnlockAllObjects` (deprecation, not a
licence). The remaining two, `InsertModelViewAction` and
`XAMlExportProductionData2SmartMountingAction`, were never reached at all. So `live_resolved` in the registry, and
`action_catalog(available_only=True)`, are a necessary-not-sufficient filter -
confirm by actually running the action.

## Is the official list of 100 complete?

`python tools/validate_actions.py --completeness` answers it against the 2027
wiki, two independent ways (result in `tools/action_validation_report.md`):

- **Direct.** `GET /file` for `API Reference/Actions/<Name>.md` for each of the
  100 names in `tools/data/official_actions_2027.json`: **98 have a page, 2 do
  not** - `LockUnlockAllObjects` and
  `XAMlExportProductionData2SmartMountingAction`, the same two that 404 on
  eplan.help. This direction is exact - `/file` is a yes/no lookup.
- **Reverse.** Enumerate the wiki's own `API Reference/Actions/*.md` pages with
  12,268 prefix/seed queries (`/search` caps `topK` at 20 and has no path
  filter or pagination, so enumeration means many queries; the sweep recurses
  only into prefixes that came back saturated). Result: **98 action pages, and
  0 of them missing from our list.** The sweep is **capped** at prefix length
  3 (`--max-depth`); 1,115 length-3 prefixes were still saturated and were not
  expanded. The cap is justified empirically - length 3 cost 10,872 queries
  and added zero pages over length 2 - but it is a cap, not proven exhaustion.

So the wiki documents nothing we do not already know about, and our list is a
strict superset of it by exactly those 2 deprecated/undocumented names.

Caveat, stated because it is the only hole: two prefixes (`ep`, `eed`) fail
deterministically with `D1_ERROR: D1 DB exceeded its CPU time limit` - they
match too much of the index - so the automated sweep cannot see through them.
They were drilled by hand (all 36 `ep?` prefixes, then 144 four-character
prefixes under the sub-prefixes that also fail: `epe`, `epl`, `eps`, `eed`) and
turned up no action page that is not already in the list.

## Known gaps

- The registry can go stale: `tools/build_action_registry.py` must be re-run
  after adding wrappers, and the determinism test only compares build-vs-build,
  never committed-vs-source.
- `ribbon_catalog`'s `resolved_from_command_index` / `unresolved_commands`
  counters describe the whole ribbon walk, not the filtered view.
- EPLAN appears to lowercase parameter keys internally (an error echoed
  `/projectname:` for a `/PROJECTNAME:` call), so the casing discipline above may
  be stricter than required - documented casing is still what the wrappers send.
- **19 emitted `/KEY`s across 15 pre-existing wrappers are in neither the 2027
  wiki page nor the MFTools registry.** All of them pre-date the action-catalog
  work, none has been retested live, so **none was changed** - they are listed
  here so the next person does not rediscover them. Full table in
  `tools/action_validation_report.md`. A key that is in neither source is not
  automatically wrong (EPLAN's docs omit things, and MFTools only records the
  keys the GUI happens to use), but where the docs name a *different* key for
  the same job, the wrapper is the more likely suspect:

  | Wrapper emits | Action | The wiki documents instead |
  |---|---|---|
  | `/FORMAT`, `/INSTALLATIONSPACE` | `export3d` | `INSTALLATIONSPACENAME`; the format is chosen with `TYPE` (`STEP`/`JT`) - which `export_.export_3d` never sends at all |
  | `/DESTINATIONPATH`, `/SCHEME` | `generatemacros` | `WINDOWMACRODIR`, `PAGEMACRODIR`, `FILTERSCHEME` |
  | `/EXPORTFILE`, `/PROJECTNAME` | `XEsUserPropertiesExportAction` | `XMLFile`, `Project` (same for the Import twin with `IMPORTFILE`) |
  | `/EXPORTFILE`, `/PROJECTNAME` | `ExportNCData` | `TargetFile` / `TargetDirectory`, `ProjectName` |
  | `/EXPORTFILE` | `ExportSegmentsTemplate` | `FILENAME` |
  | `/DATASOURCE` | `XPartsSetDataSourceAction` | `DataSourceType`, `DataBaseFileName`, `Sql*`, `Container*` |
  | `/PROJECTNAME` | `XMDeleteReprTypeAction` | no project parameter at all (`RepresentationType`, `Source`, `Destination`) |
  | `/IMPORTSCHEME` | `import3d` | `SCHEME` |
  | `/DESTINATIONPATH`, `/SOURCEPATH`, `/USEPAGEFILTER`, `/IMPORTFILE`+`/PROJECTNAME` | `masterdata`, `export`, `XMImportDCArticleDataAction`, `ImportPrePlanningData`, `ImportSegmentsTemplate`, `ExportProductionWiring` | not listed on the page - undocumented rather than contradicted |

  Note `TYPE` is in the validator's `IGNORED_PARAMS`, so a wrapper that omits a
  **mandatory** `TYPE` (as `export_3d` does) is invisible to the report.
- **`/PROJECTNAME` vs the documented `/ProjectName`** in three wrappers -
  `cabinet.calculate_cabinet_weight`, `production.export_nc_data`,
  `production.export_production_wiring`. If the internal-lowercasing
  observation above holds this is harmless; if it does not, `project_name` is
  silently ignored and the current project is used. Left unchanged for the
  same reason: unverified live.

## Refreshing after a version or licence change

```
python tools/build_action_registry.py      # re-mine MFTools.xml + docs
python -m pytest tests/ -q                 # all green, 2 documented skips
python tools/validate_actions.py --out tools/action_validation_report.md
```

`validate_actions.py` checks against the 2027 wiki (`https://rag2027.covaga.xyz`,
override with `--rag-url`): an action is documented iff the wiki serves
`API Reference/Actions/<Name>.md`, and every `/KEY` must appear on that page with
the same casing. Add `--completeness` (or `--completeness-only`) to also sweep
the wiki for action pages that are missing from
`tools/data/official_actions_2027.json` - it takes thousands of queries and tens
of minutes, so it is opt-in.

Regenerate the availability data with `python tools/probe_live_actions.py`
against a running EPLAN.

`tools/data/live_actions_2027.json` (the FindAction probe) is a point-in-time
snapshot of what this installation had registered; re-probe after upgrading.
