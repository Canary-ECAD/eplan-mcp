# Live results: EPLAN 2026.0.3 (host 0.3.0, flavor netfx)

EPLAN 2026.0.3.25794 on .NET Framework 4.8.9363.0, host built on the same machine
(`dotnet build EplanMcp.sln -c Release -p:EplanVersion=2026.0.3`, which selects `net481`). Measured
2026-11-12. Read-only runs only: the open project was read, never written, and no scratch clone was
made. Nothing about that project is recorded here.

## Bootstrap runtime (nothing registered)

| Check | Result |
|---|---|
| `eplan_script_hello(runtime="bootstrap")` | `success`, core 0.3.0, flavor `netfx`, framework .NET Framework 4.8.9363.0, `unloads: false`, Roslyn 4.12.0.0 (shipped with the host) |
| Snippet reading the open project's pages | `ok`, phase `done`; 5.1 s cold (first Roslyn use in the process), 0.55 s for the same snippet again |
| Same snippet a second time | reused its loaded assembly (no second load); log says the script stays loaded until EPLAN closes |
| Compile error (`ctx.Projectt`) | phase `compile`, `CS1061` with the author's line |
| Write in a read-only run | phase `compile`, `EMCP002` from the safety analyzer |
| `identity.cs` | `data_model_copies` 1, `context_from_host` true, the API from EPLAN's `Bin` (`Eplan.EplApi.DataModelu.dll`) |

`identity.cs` also reported 3 copies of the host assemblies: the two earlier attempts of this
session, which loaded the host from bytes and failed, stay in the process until EPLAN closes. A fresh
EPLAN holds one.

## What failed first, and why the netfx host loads from files

The first build loaded the host from bytes, as the .NET 8 bootstrap does. EPLAN 2026 answered every
call with `ArgumentException: the path is not of a legal form`, thrown when `EplanMcp.Scripting`
needed `EplanMcp.Scripting.Core`. EPLAN 2026's AppDomain has three `AssemblyResolve` handlers of its
own, which run before any other:

- `Eplan.EplApi.Internal.MyAssEventHandler.MyResolveEventHandler`
- `Eplan.IdentityClient.BindingRedirectAssemblyResolver.CurrentDomainAssemblyResolve`
- `Eplan.EplApi.Scripting.Internal.MyScriptEventHandler.MyResolveEventHandler`

One of them fails on a requesting assembly with no file location, which is what an assembly loaded
from bytes has. So on .NET Framework the bootstrap copies each verified file to
`%TEMP%\EplanMcp\host-<manifest hash>\` and loads it from there, and compiled scripts are written to
`%TEMP%\EplanMcp\scripts\<image hash>.dll` before they load.

## Offline host

| Check | Result |
|---|---|
| `eplan_script_hello(runtime="offline")` | `success`, flavor `netfx`, .NET Framework 4.8.9363.0, Roslyn 4.12.0.0, EPLAN 2026.0.3.25794 |
| `eplan_script_offline_stop` | stopped |

Not run: an offline script on a closed project (none at hand that is not a real one).

## Not run here

- The add-in runtime (`EplanMcp_RunScript`): registering it needs an EPLAN restart, and the EPLAN on
  this machine had work open.
- Writes to a scratch clone (`allow_real_project` stays off; the write gate is the same code as on
  .NET 8 and is covered by `GuardTests`).
- `hang.cs`, `lock_check.cs`.
