# Live checks for the script host

These scripts prove what unit tests cannot: behaviour inside a running EPLAN. Run them only against
a **scratch clone** (`eplan_scratch_project_create`), through both runtimes
(`runtime="addin"` and `runtime="bootstrap"`), and record the result per EPLAN build in
`results-<eplan version>.md`.

| Script | Proves | Pass when |
|---|---|---|
| `identity.cs` | Scripts bind to the live EPLAN API and the live host, not second copies (type identity) | `data_model_copies` is 1 and `context_from_host` is true |
| `references.cs` | The compiler finds what it needs under EPLAN's native host | it compiles and returns the reference count and whether the trusted-platform list exists |
| `lock_check.cs` | A run on the direct path can lock objects (the S511176 trap) | `locked` is true for the sampled function |
| `hang.cs` | A runaway loop is stopped by the budget, and EPLAN stays responsive | result phase `run`, error mentions the budget, `unloaded` true |
| `../../scripts/project_info.cs` | A plain read works and unloads | `ok` and `unloaded` true |

Every run's `unloaded` must be true. A `false` means something kept the script alive and memory grows
until EPLAN restarts.
