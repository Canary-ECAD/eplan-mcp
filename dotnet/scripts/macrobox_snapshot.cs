// @tool     macrobox_snapshot
// @desc     Saves every macro box in the project (page, macro, variant, flags, area, layer, pen, texts) to a snapshot file that macrobox_restore can re-create missing boxes from.
// @schema   1
// @arg      out  string  optional   Snapshot file to write (default macrobox_snapshot.json in the run folder)
// @writes   false
// @needs    session
//
// A macro box is its own placement type, so a check that counts functions, texts and property
// placements does not see one go missing. Take a snapshot before an operation that can delete
// placed objects, and compare or restore afterwards. The file records the project name, so
// macrobox_restore refuses it for another project unless told otherwise.
using System;
using System.Linq;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var (rows, problems, pages) = MacroBoxes.Survey(ctx, project);
        var path = PlainJson.OutPath(ctx, ctx.Args.String("out"), "macrobox_snapshot.json");
        long bytes = PlainJson.Write(path, Guards.SnapshotEnvelope("macrobox", 1, project.ProjectName, project.ProjectFullName, rows));
        return new
        {
            project = project.ProjectName,
            pages,
            macro_boxes = rows.Count + problems.Count,
            saved = rows.Count,
            failed = problems.Count,
            problems,
            distinct_macros = rows.Select(r => PlainJson.Str(r, "macro")).Distinct(StringComparer.OrdinalIgnoreCase).Count(),
            ok = problems.Count == 0,
            @out = path,
            bytes,
        };
    }
}
