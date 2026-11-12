// @tool     function_inspect
// @desc     Placed functions on a page or matching a device tag: names, connection points, supplementary fields 1-2 (raw), active arrangement, symbol.
// @schema   1
// @arg      page        string  optional   Page Name or IdentifyingName (exact)
// @arg      device_tag  string  optional   Substring of the device tag (FUNC_DEVICETAG_FULLNAME), case-insensitive
// @arg      max         int     optional   Functions listed (default 500); all matches are counted
// @arg      with_id     bool    optional   Include each function's string id (valid only while the project stays open)
// @writes   false
// @needs    session
using System;
using System.Collections.Generic;
using System.Linq;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        string? pageFilter = ctx.Args.String("page");
        string? tagFilter = ctx.Args.String("device_tag");
        int max = (int)Math.Max(0, ctx.Args.Int("max", 500));
        bool withId = ctx.Args.Bool("with_id");

        var results = new List<object>();
        int total = 0;
        foreach (var page in Pages.All(project).Where(p => string.IsNullOrEmpty(pageFilter) || Pages.Matches(p, pageFilter)))
        {
            ctx.Budget.Check();
            var functions = Safe.Get(() => Functions.OnPage(page), null);
            if (functions == null) continue;
            string? pageName = Safe.Text(() => page.Name);
            foreach (var function in functions)
            {
                string? tag = Functions.DeviceTag(function);
                if (!string.IsNullOrEmpty(tagFilter) && (tag == null || tag.IndexOf(tagFilter, StringComparison.OrdinalIgnoreCase) < 0)) continue;
                total++;
                if (results.Count < max) results.Add(Describe.FunctionFull(function, pageName, tag, withId));
            }
        }
        return new
        {
            project = project.ProjectFullName,
            page_filter = pageFilter,
            device_tag_filter = tagFilter,
            max,
            function_total = total,
            functions = results,
        };
    }
}
