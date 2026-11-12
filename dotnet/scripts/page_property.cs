// @tool     page_property
// @desc     Page properties by id and/or identifying name; with neither, every property the page holds.
// @schema   1
// @arg      page   string  required   Page Name or IdentifyingName (exact)
// @arg      ids    list    optional   Property ids to read
// @arg      names  list    optional   Identifying names (user-defined properties included)
// @arg      index  int     optional   Index used when a plain read of an id fails (indexed property; default 1)
// @writes   false
// @needs    session
using System.Collections.Generic;
using System.Linq;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var page = Pages.Require(project, ctx.Args.Require("page"));
        var ids = ctx.Args.List("ids").Select(s => int.TryParse(s, out var n) ? (int?)n : null).Where(n => n.HasValue).Select(n => n!.Value).ToList();
        var names = ctx.Args.List("names").Distinct(System.StringComparer.OrdinalIgnoreCase).ToList();
        int index = (int)ctx.Args.Int("index", 1);

        var results = new List<object>();
        foreach (var id in ids) results.Add(PropertyReader.ReadById(page, id, index));
        foreach (var name in names) results.Add(PropertyReader.ReadByName(page, project, name));
        if (ids.Count == 0 && names.Count == 0) results.AddRange(PropertyReader.Existing(page));
        return new
        {
            project = project.ProjectFullName,
            page = page.Name,
            requested = ids.Count > 0 || names.Count > 0,
            properties = results,
        };
    }
}
