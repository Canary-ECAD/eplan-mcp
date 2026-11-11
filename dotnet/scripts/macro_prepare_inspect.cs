// @tool     macro_prepare_inspect
// @desc     What "Prepare macros for automatic generation" left on each macro box of the given pages: usage, stored vs. automatic name, version and part, flags, grouping.
// @schema   1
// @arg      pages  list    required   Exact page names
// @arg      out    string  optional   JSON file for the rows (default macro_prepare_inspect.json in the run folder)
// @writes   false
// @needs    session
using System;
using System.Linq;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var pages = ctx.Args.List("pages");
        if (pages.Count == 0) return new { error = "'pages' is required: a list of page names." };
        var rows = MacroBoxes.PrepareInspect(ctx, project, pages);
        var path = PlainJson.OutPath(ctx, ctx.Args.String("out"), "macro_prepare_inspect.json");
        return new
        {
            project = project.ProjectFullName,
            boxes = rows.Count,
            samples = rows.Take(4).ToList(),
            @out = path,
            bytes = PlainJson.Write(path, rows),
        };
    }
}
