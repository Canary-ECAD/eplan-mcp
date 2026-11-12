// @tool     page_inspect
// @desc     Pages with their placements, texts and functions. Without a page filter only counts come back unless max is given.
// @schema   1
// @arg      page     string  optional   Page Name or IdentifyingName (exact, case-insensitive)
// @arg      max      int     optional   Items listed per kind and page (default 500 with a page, 0 without)
// @arg      include  list    optional   Any of placements, texts, functions (default all)
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
        string? filter = ctx.Args.String("page");
        // A whole-project listing is megabytes; without a page, list nothing unless asked.
        int max = (int)System.Math.Max(0, ctx.Args.Int("max", string.IsNullOrEmpty(filter) ? 0 : 500));
        var include = new HashSet<string>(ctx.Args.List("include"), System.StringComparer.OrdinalIgnoreCase);
        bool all = include.Count == 0;

        var pages = Pages.All(project).Where(p => string.IsNullOrEmpty(filter) || Pages.Matches(p, filter)).ToList();
        var results = new List<object>();
        foreach (var page in pages)
        {
            ctx.Budget.Check();
            results.Add(Describe.Page(page, all || include.Contains("placements"), all || include.Contains("texts"),
                all || include.Contains("functions"), max));
        }
        return new
        {
            project = project.ProjectFullName,
            page_filter = filter,
            max,
            page_count = results.Count,
            pages = results,
        };
    }
}
