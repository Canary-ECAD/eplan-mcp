# Live results: EPLAN 2027.0.3, .NET 8 host

Measured 2026-11-10 on one Windows PC with an EPLAN API developer license (Electric P8 Premium),
script host core 0.1.0, runtime **bootstrap** (`ExecuteScript`, host loaded from bytes). The
target was a scratch clone of a mid-size schematic project, opened alone.

| Check | Result |
|---|---|
| Handshake (`script_hello`, bootstrap) | Pass. EPLAN 2027.0.3, Roslyn 4.12.0.0 found in EPLAN's own `Bin`, license reported. |
| `identity.cs` | Pass. One copy of `Eplan.EplApi.DataModelNetu` (Default context); `ctx` comes from the one host copy (`EplanMcp.Core/<version>/<manifest hash>` context); the script runs in its own collectible context. |
| `references.cs` | Pass. EPLAN's native host DOES provide `TRUSTED_PLATFORM_ASSEMBLIES` (356 entries); 25 of ~237 loaded assemblies have no file location. |
| `project_info.cs` | Pass. Page and function counts of the clone in about 0.6 s per run (compile included). |
| `hang.cs`, budget 3 s | Pass. Stopped at 3.4 s with `ScriptStoppedException`; the error points at `hang.cs:line 6`. EPLAN stayed responsive. |
| `lock_check.cs` | Pass. `ctx.Lock` (SmartLock) succeeded on the bootstrap path: script-context runs CAN lock. |
| Compile error | Pass. `CS1061` on the author's line 2, hint "Did you mean: ProjectName, ProjectType". |
| Read-only write | Pass. `SmartLock` in a script without `@writes true` rejected at compile time (`EMCP002`). |
| Unload | Mostly pass. 20 consecutive runs (half of them using the DataModel) unloaded, with flat private memory (about 1.66 GB) and a flat count of loaded script assemblies. The FIRST run on each new server connection, and the class-file scripts run in one earlier batch, stayed loaded: one small assembly each, no visible memory growth. Cause not found yet; EPLAN's own `AssemblyLoadContext.AssemblyLoad` subscribers (API module, license handler, script log, WPF) are the suspects. |
| Add-in runtime | Pass, same day. `EplApiModuleActionNet /register:` on a copy outside the build folder made `EplanMcp_RunScript` and `EplanMcp_Hello` resolvable at once, with NO EPLAN restart (first registration). Every check above passed through the add-in too (identity: one data-model copy, host in the Default context; lock taken; budget stop; hints; read-only rejection), with the same unload pattern. `/unregister:` removed both actions again. |

## Gotcha found: action file paths under `AppData`

An `ExecuteScript /ScriptFile:"..."` whose path is written in the long form
`C:\Users\<user>\AppData\Local\...` or `...\AppData\Roaming\...` is silently ignored: the remote
call reports success, nothing runs, and EPLAN logs "The name of the script file is missing
(ScriptFile)". The same files under the user profile (`~\.eplan-mcp`), ProgramData, Documents or the
8.3-form TEMP (`C:\Users\<SHORT~1>\AppData\Local\Temp`) run fine. The script host therefore keeps
its run folders in `~\.eplan-mcp\runs`. Not tested yet: whether add-in action parameters
(`/request:` `/result:`) are affected the same way.

## Script host 0.2.0 (final live test)

Measured 2026-11-11 on the same PC and EPLAN 2027.0.3.27481 (Electric P8 Premium), host core 0.2.0
built in Release from this branch. The add-in was registered with `EplApiModuleActionNet /register:`
from `dotnet/artifacts/host`, then EPLAN was restarted. The target was a scratch clone of a mid-size
schematic project (75 pages, 8,687 functions), carrying the scratch marker, opened alone. All three
runtimes ran in the same session; the legacy probe add-in stayed registered for the parity check.

Two builds were used. These checks ran on 26ecc2914: the add-in handshake, the public-script reads
and `text_create`, the read-only refusal, the bootstrap checks, the write gate, and the first
`identity.cs` run. These ran on e73e291a4, which carries the reference fix below: probe parity,
the probe write, `lock_check.cs` on the add-in, the MasterData check on both runtimes, the offline
host, and an `identity.cs` re-run on both runtimes with the same result.

| Check | Result |
|---|---|
| Handshake, add-in | Pass. `script_hello(runtime="addin")` reports core 0.2.0, protocol 1, no version warning. `EplanMcp_RunScript` and `EplanMcp_Hello` resolve after the restart. |
| Reads, add-in | Pass. `project_info` (75 pages, 8,687 functions, about 1.8 s), `page_inspect` (all pages, then one page with 442 functions), `function_inspect` and `function_dump` all return data for the clone named in `project`. |
| Write, add-in | Pass. `text_create` writes a two-line text and reads it back. `lock_check.cs` locks a function. A write probe from a helper library (about 50 files) creates a text. No `LockingException`: the add-in no longer opens its own nested `LockingStep`. |
| Read-only run that writes | Pass. `Text.Create` in a script without `@writes true` is rejected at compile time (`EMCP002`). `ctx.Lock` in such a script throws "This run may not write" at run time. |
| Probe parity | Pass. The helper-library probes `project_info`, `page_inspect`, `function_inspect` and `function_dump`, run through the script host, give output identical to the legacy probe add-in on the same clone: zero differences, field by field. Both sides were given the project explicitly, and both report its name, 75 pages and 442 functions on the sampled page. The legacy add-in matches `project` against the full name without `.elk`; the script host takes the `.elk` path. |
| Public scripts vs legacy probes | Expected differences only. `function_dump` is identical. `page_inspect` adds an `err: null` per item and omits `include`. `function_inspect` reports an empty supplementary field as `null` where the legacy probe puts an `EmptyPropertyException` in `err`. The public `project_info` is a different, smaller summary by design. |
| Handshake, bootstrap | Pass. Core 0.2.0, same EPLAN, license and Roslyn as the add-in. |
| Read and write, bootstrap | Pass. `project_info` takes about 0.5 s. `text_create` writes and reads back. `lock_check.cs` locks a function through `ctx.Lock`. |
| `identity.cs` | Pass on both runtimes. One copy of `Eplan.EplApi.DataModelNetu` (Default context), and `ctx` comes from the runtime's own host copy. With both runtimes used in one session, the process holds two host copies, one per runtime: the add-in's in the Default context and the bootstrap's in `EplanMcp.Core/0.2.0/<hash>`. That is by design. |
| Offline host | Pass. Started on the closed clone in 167 s (first start). `project_info` read 75 pages and 8,687 functions, about 16-20 s per run because each run opens and closes the project. Session-only scripts (`page_inspect`, `text_create`) were refused at the guard ("needs the interactive EPLAN"). `script_offline_stop` stopped it, and no host process remained after 1 s. |
| Write gate | Pass. With the scratch marker removed from the same clone, ad-hoc writes were refused at the guard on both the add-in and the bootstrap: "the target project ... is not a scratch clone (no marker file)". `allow_real_project=True` without the server switch was refused before anything ran. The marker was restored afterwards. |
| Unload | Not measured in steady state. About half the runs (13 of 25) reported `unloaded: false`. Every run here came from a fresh server connection, which is the case 0.1.0 already saw stay loaded. The warm-connection series that 0.1.0 measured was not repeated. |

### Fixed during this test

- **MasterData scripts did not compile in a fresh session.** The compile references come from the
  loaded assemblies, and EPLAN loads `Eplan.EplApi.MasterDataNetu` lazily. So any script or helper
  using `Eplan.EplApi.MasterData` failed with `CS0234` on the add-in and bootstrap runtimes until
  something else loaded it. The probe helper library hit this. Both in-EPLAN runtimes now reference
  every `Eplan.EplApi.*Netu.dll` in EPLAN's `Bin`, as the offline host already did. After a restart,
  the library compiled at once.
- The write-gate refusal said "is not a scratch clone" twice. Reworded.

### Seen, not changed

- `write_allowed` is `true` in a result that failed the compile-time safety check of a read-only
  script, because it reports the gate and not the script. It is `false` in a result that reached
  the run phase.
- During one batch, EPLAN showed its "Open symbol library" and "Symbol selection" dialogs.
  They were already open before the first refused call. Three add-in runs then reported
  `EplanBlockedByDialog` and "the host wrote no result". The test closed no dialog. Shortly after,
  the dialogs were gone, and a retry passed. The cause was not identified. EPLAN's system messages
  show only read-only symbol-library opens, each closed again.

## 0.2.0 library tools

Measured 2026-11-11 on the same PC and EPLAN 2027.0.3, host core 0.2.0 built in Release (first
`4f78a11`, then rebuilt with the fixes below). The target was a scratch clone of a mid-size
schematic project (75 pages), carrying the scratch marker, opened alone. Every tool was called the
way the MCP server builds it (`script_tools.make_tool`), so a writer's default call is a dry run.
Each dry run and each guard was proved by a before/after read (`text_placements`, `line_styles`,
or a function-location read), not only by the tool's own report.

| Tool | Result | Dry run | Real write, read-back | Guards refused (`success: false`, nothing written) |
|---|---|---|---|---|
| `text_placements` | Pass | - | - | - |
| `text_set_height` | Pass | No change | height 3.0, factor 1.5, `target=font_size` 3.5 and 2.54: `sticks`, `not_stuck` empty | neither or both of height/factor; factor 0; bad target; unknown handle; malformed `#` handle; symbol handle without `#`; wrong property id; position out of range; handle from another page; stale handle of a deleted text; variant text without `allow_shared` |
| `text_set_box` | Pass | No change | 8 settings on a free text, 2 on a local property text, all `sticks` | nothing to set; `box_width` 0; stale handle; variant text without `allow_shared` |
| `text_create` | Pass | No new text | two-line text: text, x, y, height read back; the line break kept (`debug` codes) | height 0; unknown page (thrown, so `phase: run`) |
| `line_styles` | Pass | - | - | - |
| `line_styles_set` | Pass | No change | 2 lines and 1 arc: style, factor, width all `sticks` | over limit; nothing matches; missing limit; missing or inverted area; nothing to set; factor 0; width below 0 |
| `function_move` | **Fixed**, then pass | No change | 2 functions, by name and by handle: `sticks`; moved back | ambiguous name; unknown handle; no x/y; same function twice; one bad move with one good; empty `moves` (thrown) |
| `function_remove` | Pass | No change | 2 marker functions: `removed`, count 120 to 118 | one bad name (all-or-nothing); wrong prefix; ambiguous name; empty prefix; empty names; missing prefix (thrown); main function; every function on a 120-function page (dry and real) |
| `macrobox_snapshot` | Pass | - | 621 boxes on 75 pages, about 1.6 s | - |
| `macrobox_restore` | **Fixed**, then pass | `would_create` 2 | after deleting 2 boxes: `created` 2, `ok` true; a new snapshot equals the original field by field; a re-run creates nothing | missing limit; over limit (limit 1 for 2); bare-array file; other project; missing file. With `allow_other_project` the other-project file is accepted. |
| `parts_snapshot` | Pass | - | 8,687 functions, 1,022 with parts, about 4.2 s | - |
| `parts_restore` | Pass (write path; coverage limited, see below) | `would_change` 2 | after clearing the parts of 2 main functions: `changed` 2, read back; a new snapshot equals the original except the 2 functions `function_remove` deleted | same as `macrobox_restore` |

Both restores ran project-wide well inside the 120 s budget: `macrobox_restore` 0.4-2.5 s,
`parts_restore` 4.6-6.6 s. The limit check runs a full dry pass first, so a refused call costs
about the same time as a real one.

### Bootstrap runtime

`text_placements`, `line_styles` and `text_set_height` (dry run, real write with `sticks`, and the
stale-handle guard) passed on the bootstrap runtime after the rebuild. `script_hello` reports core
0.2.0, protocol 1, on both runtimes.

### Python tools (reworded only)

`scratch_symbols_status` reads the current symbol path and reports no redirect.
`list_addin_actions` without a manifest refuses clearly ("prefix is required", then "source_dirs is
required"). A `ui_dismiss_watch_start` / `ui_dismiss_watch_stop` pair started, stopped and reported
0 dismissals. Nothing was built, deployed or isolated.

### Answers to the open questions

- **Handles.** `ToStringIdentifier()` gives `28/30/<n>/0` for a free text and `28/17/<n>/0` for a
  function (symbol reference). A free-text handle has no `#`. A property-text handle is
  `<owner>#<position>:<property id>`, for example `28/17/<n>/0#1:20201`. Handles were identical
  across two separate runs, and still resolved after an EPLAN restart and a reopen of the project.
- **Variant (non-local) property texts.** Without `allow_shared`, both writers refuse. With it,
  `text_set_box` wrote `has_box` to the variant, and a later run showed it on every instance of
  that variant (20 per page on the three pages checked) and on none of another variant of the same
  symbol. `text_set_height` with `allow_shared` threw "The database is write-protected" at the
  `TextBase.Height` setter: nothing was written, and the result is `success: false`, `phase: run`,
  with a stack trace instead of a clean refusal. Not changed; see below.
- **Font size (#19017) read-back** is an invariant-culture number string: `"2.54"`, `"3"`, `"3.5"`,
  `"4.5"`. It is `null` on property texts whose height comes from the layer. The `font_size` sticks
  check parses it correctly. Writing the font size also changes `Height` to the same value.
- **`Pen.Width` sticks** (0.5 mm on 2 lines and an arc, read back in a later run and after a
  restart), as do the style id and the style factor. The pattern length then reads -2.
- **Restore budget:** see above; both are far below 120 s on this project.

### Fixed during this test

- **`function_move` wrote the good moves when another move failed** and reported `success: true`
  with `errors > 0`. For "same function twice", the first entry was written. Every move is now
  checked before any is written, and one failed check refuses the call. Commit `093bbb0`.
  Re-tested live: each guard leaves every position unchanged.
- **`macrobox_restore` failed to set the layer on every created box** ("S511249 Invalid layer
  cannot be transferred"): `new GraphicalLayer(name, ...)` is refused. Every restore was reported
  `partly_applied` with `ok: false`, although the boxes were created. The helper now takes the
  layer object from the project's `LayerTable` by name and reads it back. Commit `2a600db`
  (`EplanMcp.Eplan`, so EPLAN was restarted on the rebuilt host). Re-tested live: `created` 2,
  `ok` true. A probe also moved a box to another layer and back through the same lookup.

### Seen, not changed

- `text_set_height` with `allow_shared` on a variant text throws (see above). `text_set_box`
  reaches the variant; `text_set_height` does not. A clean refusal, or a switch to local
  placements, is a design decision.
- The bounds of a property text are 0,0,0,0 when it shows an empty value. Texts with a value have
  page-coordinate bounds. `x` and `y` of a property text are relative to the symbol.
- `text_create` accepts an empty `text` and places an empty text.
- `line_styles` with only some of x0..y1 given ignores the area and lists the whole page.
- Arguments that `ctx.Args.Require` or `PlainJson` reject (missing `symbol_prefix`, empty `moves`,
  bare-array or other-project snapshot, unknown page) come back as an exception (`phase: run`,
  with a stack trace) instead of a result `error`. They are still `success: false`, and nothing is
  written.
- **`parts_restore` finds only about a third of the snapshot on its own source project.** Of
  1,022 rows with parts, 327 matched a function (325 unchanged, 2 restored). 502 were ambiguous:
  several functions share page, device tag, symbol, category and connection points, and none or
  several of them are main. 298 of those are unplaced functions, where the page is empty, so every
  unplaced function with the same device tag collides. 195 matched an auxiliary function whose
  device has no single main function (mostly terminal symbols; 30 unplaced), and are skipped
  without `promote_main`. The matcher does search unplaced functions too. The tool refuses rather
  than guesses, so nothing wrong was written, but a restore after a large loss would put back only
  the uniquely identifiable functions. The test deleted parts from two such functions, so it proves
  the write path, not the coverage.
- When a restore has nothing to do, a real call reports `dry_run: true`, because it returns its
  planning pass.
- A read-only snapshot refuses an `out` path outside its run folder. Use the default and copy the
  file.
- `unloaded` was `false` on the first run in each new server connection, and on the first run of
  some scripts after it. Later runs reported `true`, as in 0.2.0.

No dialog that the test did not open appeared, and the "Project master data" watcher dismissed
nothing. The clone was discarded and its marker removed. EPLAN was left running with no project
open.

### 0.2.0 fixes

Measured 2026-11-11 on the same PC and EPLAN 2027.0.3. The host was rebuilt in Release three
times: at `71b4473`, at `80cfc6c`, and as core **0.2.1** at `a358c5c`. EPLAN was restarted on each
build, and both runtimes report core 0.2.1. The version moved because the refusal result and the
helper signatures that `parts_snapshot` and `parts_restore` use (now `@requires core>=0.2.1`) are
part of the contract. The target was a fresh scratch clone of the same mid-size schematic project (75 pages,
8,687 functions, 1,022 of them with parts). The clone carried the scratch marker and was opened
alone. Each call was made the way the MCP server builds it.

**Clean refusals.** A new `ScriptRefusedException` in the core is turned by the run pipeline into
the result `{"error": ...}`. The run ends `ok`, `phase: done`, and the server reports
`success: false` with the plain message and no stack trace. These throw it:

- `ctx.Args.Require` and `ctx.RequireProject`;
- `Pages.Require`;
- `PlainJson`'s record and snapshot readers;
- the `out` path check.

Two scripts that threw an `ArgumentException` now return the error. All 11 guards that threw
before were re-tested live, and each came back clean:

- a missing required argument, and a missing `symbol_prefix`;
- empty `moves`;
- a bare-array snapshot, an other-project snapshot, a snapshot of the wrong kind, and a missing
  snapshot file;
- an unknown page, in `text_create` and in `line_styles`;
- `macrobox_links` without pages;
- a read-only `out` outside the run folder. The message now says to pass a bare file name and
  copy the file from the `out` path.

On the bootstrap runtime, an unknown page and a missing argument were clean too. Both restores
now resolve `out` before the first write, so a refusal always means nothing was written.

**`text_set_height` on a variant property text.** The EPLAN API documents no way to set the
height of a variant's property placement. `SwitchLocalPropertyPlacements` makes one instance
local, which is a different change. With `allow_shared`, the font size target also failed live,
with "The database is write-protected", and nothing was written. Both targets are now refused up
front, in a dry run as well, with a pointer to `text_set_box` or to local placements.
`allow_shared` stays for compatibility. Live after the rebuild, all four calls were clean
refusals (height and font size, each dry and real), and 0 of 1,180 texts on the page changed. On
0.2.1 the same refusal also comes without `allow_shared`, dry and real. Before, that call asked
for `allow_shared`, which can no longer help.

**`parts_restore` coverage.** `parts_snapshot` writes schema 2. Each row adds:

- `id` (`ToStringIdentifier()`);
- `full_dt` (with structures);
- `definition` (function definition identifier);
- `variant`.

`parts_restore` matches by id first when the snapshot comes from the same project and the
function at that id has the same category and device tag. The rest match by
(page, full device tag, definition, category, symbol, variant, connection points). Schema 1 files
still match by the older key and the loose key.

A tie is refused and listed in the out file, with up to 20 candidates (id, page, full device tag,
definition, main flag, current parts). Parts go back on the matched function itself. The old
redirect of an auxiliary match to the device's main function was wrong for this data:

- all 192 terminal rows with parts belong to a strip whose main function carries different parts;
- 51 article-placement rows had parts that differ from their single main function.

Only a row recorded as main that now matches a non-main function is still redirected.

Coverage of a project-wide dry run on the untouched clone (1,022 rows with parts):

| Snapshot | Matched | Already equal | Ambiguous | Skipped (unmatched) |
|---|---|---|---|---|
| Before the fix (schema 1, earlier test) | 327 | 325 | 502 | 195 |
| Schema 1 file, new code (older key) | 522 | 522 | 500 | 0 |
| Schema 2, key only (`allow_other_project`, no ids) | 654 | 654 | 368 | 0 |
| Schema 2, same project (ids) | **1,022** | 1,022 | 0 | 0 |

The remaining key-only ties are real duplicates, for example 17 cable functions on one page with
the same placeholder device tag and the same part. Only the id tells them apart.

**Restore after a loss.** The test cleared the parts of 8 functions with a script, after a dry
run:

- 2 placed main functions (cables);
- 2 unplaced main functions;
- 1 terminal;
- 1 article placement whose device has a single main function with other parts;
- 2 cables that were ambiguous under the old key.

The restore then ran:

- The dry run reported `would_change` 8.
- `limit` 7 was refused, and nothing was written.
- `limit` 8 wrote 8, all `set` by id and read back.
- A re-run changed nothing and reported `dry_run: false`. On 0.2.1 it also carries the real
  call's counts (`changed` 0), not the dry pass's `would_change`.

A fresh snapshot equals the original row for row, 8,687 ids, 0 differences. That includes the
strip's main function and the article placement's main function, which were not touched. The
function ids did not change through the parts removal and restore. After an EPLAN restart and a
reopen, a dry restore again matched all 1,022 rows by id.

**Small items:**

- `text_create` refuses an empty or whitespace-only text.
- `line_styles` refuses a partial area, naming the corners it got. All four corners, or none,
  work as before (3 and 33 lines).
- A restore with nothing to do reports the real `dry_run`.
- A text whose bounds read 0,0,0,0 reports `bounds: null` with `bounds_reason`. The reason names
  both causes seen live: a property text with an empty value (found within the first 5 pages),
  and 5 texts of one symbol type that do have values.
- The stale-handle message says the object no longer exists, or the symbol's texts changed, and
  to re-read.

**Bootstrap runtime:** `parts_snapshot` (8,687 functions, 1,022 with parts) and `text_placements`
passed.

No dialog that the test did not open appeared, and the "Project master data" watcher dismissed
nothing. The clone was discarded and its marker removed. EPLAN was left running with no project
open, and the shared add-ins load as before.
