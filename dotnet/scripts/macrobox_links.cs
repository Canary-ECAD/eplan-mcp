// @tool     macrobox_links
// @desc     How EPLAN ties placements to the macro boxes on the given pages: references, referenced boxes, group chain, and boxes that reference or share objects with each box.
// @schema   1
// @arg      pages  list    required   Exact page names
// @arg      out    string  optional   JSON file for the rows (default macrobox_links.json in the run folder)
// @writes   false
// @needs    session
//
// Tells nesting apart without relying on the group tree, which the user can edit.
using System;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var pages = ctx.Args.List("pages");
        if (pages.Count == 0) return new { error = "'pages' is required: a list of page names." };
        var rows = MacroBoxes.Links(ctx, project, pages);
        var path = PlainJson.OutPath(ctx, ctx.Args.String("out"), "macrobox_links.json");
        return new { project = project.ProjectFullName, boxes = rows.Count, @out = path, bytes = PlainJson.Write(path, rows) };
    }
}
