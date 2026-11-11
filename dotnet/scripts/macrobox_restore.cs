// @tool     macrobox_restore
// @desc     Re-creates the macro boxes a project is missing from a macrobox_snapshot file; boxes that exist are never duplicated. Checks the file belongs to the project, refuses more than limit changes, and writes one outcome per box to a file. Dry run by default.
// @schema   1
// @arg      snapshot             string  required   A file written by macrobox_snapshot
// @arg      limit                int     required   Max boxes that may be created or restyled; more means nothing is written
// @arg      update_existing      bool    optional   Also re-apply flags, drawing order and appearance to boxes that exist (default false)
// @arg      allow_other_project  bool    optional   Accept a snapshot taken from a project with another name (a copy)
// @arg      out                  string  optional   File for the per-box outcomes (default macrobox_restore.json in the run folder)
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). A box is identified by page,
// macro, variant and its rectangle (rounded to 0.01 mm), so several boxes of one macro on one page
// stay distinct. Each created box is read back. Safe to re-run.
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        // Every refusal comes before the first write: the out path too.
        var path = PlainJson.OutPath(ctx, ctx.Args.String("out"), "macrobox_restore.json");
        var rows = PlainJson.ReadSnapshot(ctx.Args, "snapshot", "macrobox", 1, project.ProjectName, ctx.Args.Bool("allow_other_project"));
        bool update = ctx.Args.Bool("update_existing");
        var result = MacroBoxes.Restore(ctx, project, rows, update, dryRun: true);
        int planned = (int)result["would_create"]! + (int)result["would_restyle"]!;
        if (!ctx.DryRun && planned > 0)
        {
            var refusal = Guards.OverLimit(planned, ctx.Args.Int("limit"), "macro boxes to create or restyle");
            if (refusal != null) { result["error"] = refusal; result["dry_run"] = true; }
            else result = MacroBoxes.Restore(ctx, project, rows, update, dryRun: false);
        }
        else if (!ctx.DryRun)
        {
            // Nothing to do: report the real call, with the real call's counts.
            result["dry_run"] = false;
            result.Remove("would_create"); result.Remove("would_restyle");
        }
        result["bytes"] = PlainJson.Write(path, result["rows"]);
        result["out"] = path;
        result.Remove("rows");
        result["project"] = project.ProjectName;
        return result;
    }
}
