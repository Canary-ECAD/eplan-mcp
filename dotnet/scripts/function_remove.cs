// @tool     function_remove
// @desc     Removes placed functions from one page by exact name, each guarded by its symbol name prefix. Never removes a main function or every function on the page; if any name fails its checks, nothing is removed. Dry run by default.
// @schema   1
// @arg      page           string  required   Page Name or IdentifyingName (exact)
// @arg      names          list    required   Exact placement names of the functions to remove
// @arg      symbol_prefix  string  required   Guard: each function's symbol name must start with this
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). This is the batch-by-name remover
// for symbols without part data (markers, connection symbols, ...): the symbol prefix keeps a name
// typo from deleting a device, and a main function is refused because its part data would go with
// it. To remove ONE placement of any type by handle (the undo of the eplan_live_place_* tools), use
// eplan_live_remove_placement. Each object is locked before Remove() (without the lock Remove()
// fails silently), and "removed" is read back from IsValid.
using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.DataModel;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        string prefix = ctx.Args.Require("symbol_prefix").Trim();
        if (prefix.Length == 0) return new { error = "symbol_prefix must not be empty." };
        var page = Pages.Require(project, ctx.Args.Require("page"));
        var names = ctx.Args.List("names").Where(n => !string.IsNullOrWhiteSpace(n)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        if (names.Count == 0) return new { error = "names is empty: pass the exact names of the functions to remove." };
        var functions = Functions.OnPage(page);

        // Check every name first: one failed check means nothing is removed.
        var rows = new List<Dictionary<string, object?>>();
        var targets = new List<(Function f, Dictionary<string, object?> row)>();
        foreach (var name in names)
        {
            ctx.Budget.Check();
            var row = new Dictionary<string, object?> { ["name"] = name };
            rows.Add(row);
            var hits = Functions.Named(functions, name).Where(f => Functions.SymbolName(f).StartsWith(prefix, StringComparison.OrdinalIgnoreCase)).ToList();
            if (hits.Count != 1) { row["error"] = $"{hits.Count} functions named '{name}' with a symbol starting '{prefix}' on the page (need exactly 1)"; continue; }
            var f = hits[0];
            row["symbol"] = Functions.SymbolName(f);
            row["handle"] = Safe.Text(() => f.ToStringIdentifier());
            if (Safe.Get(() => f.IsMainFunction, false)) { row["error"] = "main function: refused (its part data would be removed with it)"; continue; }
            targets.Add((f, row));
        }
        int errors = rows.Count(r => r.ContainsKey("error"));
        string? refusal = errors > 0 ? $"{errors} name(s) failed their checks; nothing was removed."
            : targets.Count >= functions.Count ? "these names cover every function on the page; refused. Remove the page with eplan_live_remove_placement(remove_page=True) if that is meant."
            : null;
        if (refusal != null || ctx.DryRun)
            return new { project = project.ProjectName, page = page.Name, dry_run = ctx.DryRun, error = refusal, would_remove = refusal == null ? targets.Count : 0, functions = rows };

        int removed = 0;
        foreach (var (f, row) in targets)
        {
            ctx.Budget.Check();
            try
            {
                ctx.Lock(f);
                f.LockObject();
                f.Remove();
                bool gone = !Safe.Get(() => f.IsValid, true);
                row["removed"] = gone;
                if (gone) removed++;
            }
            catch (Exception ex) { row["error"] = Safe.Error(ex); }
        }
        return new { project = project.ProjectName, page = page.Name, dry_run = false, removed, not_removed = targets.Count - removed, functions = rows };
    }
}
