// @tool     parts_restore
// @desc     Puts the parts saved by parts_snapshot back on the matching functions: by object id when the snapshot is from this project, else by page, device tag, function definition, symbol and connection points. Checks the file belongs to the project, refuses more than limit changes, reads every change back and writes one outcome per function (ties with their candidates) to a file. Dry run by default.
// @schema   1
// @requires core>=0.2.1
// @arg      snapshot             string  required   A file written by parts_snapshot
// @arg      limit                int     required   Max functions that may be changed; more means nothing is written
// @arg      page_prefix          string  optional   Only rows (and functions) on pages whose name starts with this
// @arg      promote_main         bool    optional   Make a function main again when the snapshot recorded it as main and its device has no main function now
// @arg      allow_other_project  bool    optional   Accept a snapshot taken from a project with another name (a copy)
// @arg      out                  string  optional   File for the per-function outcomes (default parts_restore.json in the run folder)
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). Only snapshot rows WITH parts are
// restored; a row without parts never removes anything. A matched function's parts are set to
// exactly the recorded ones, on that same function: terminals and auxiliary functions keep their
// own parts in EPLAN. Only a row recorded as a main function that now matches a non-main one goes to
// the device's single main function. Rows matching several functions equally are refused and listed
// with their candidates ("ambiguous" in the out file). A fixed device is never changed. Schema 1
// snapshots (no ids) are still read, by key.
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        // Every refusal comes before the first write: the out path too.
        var path = PlainJson.OutPath(ctx, ctx.Args.String("out"), "parts_restore.json");
        var snapshot = PlainJson.ReadSnapshot(ctx.Args, "snapshot", "parts", Parts.SnapshotSchema, project.ProjectName,
            ctx.Args.Bool("allow_other_project"), out int schema, out string from);
        // Object ids mean something only in the project they were read from.
        bool useIds = schema >= 2 && string.Equals(from, project.ProjectName, System.StringComparison.OrdinalIgnoreCase);
        string? prefix = ctx.Args.String("page_prefix");
        bool promote = ctx.Args.Bool("promote_main");
        var result = Parts.Restore(ctx, project, snapshot, prefix, promote, dryRun: true, useIds);
        int planned = (int)result["would_change"]! + (int)result["would_promote_to_main"]!;
        if (!ctx.DryRun && planned > 0)
        {
            var refusal = Guards.OverLimit(planned, ctx.Args.Int("limit"), "functions to change");
            if (refusal != null) result["error"] = refusal;
            else result = Parts.Restore(ctx, project, snapshot, prefix, promote, dryRun: false, useIds);
        }
        else if (!ctx.DryRun)
        {
            // Nothing to do: report the real call, with the real call's counts.
            result["dry_run"] = false;
            result["changed"] = 0; result.Remove("would_change");
            result["promoted_to_main"] = 0; result.Remove("would_promote_to_main");
        }
        result["snapshot_schema"] = schema;
        result["bytes"] = PlainJson.Write(path, result["rows"]);
        result["out"] = path;
        result.Remove("rows");
        result["project"] = project.ProjectName;
        return result;
    }
}
