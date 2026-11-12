// @tool     unplaced_functions
// @desc     Functions in the project database that a page-by-page walk never reaches (not placed on any page), filtered by symbol name.
// @schema   1
// @arg      symbol_prefix  string  required   Symbol names to count; "*" means every function
// @arg      max            int     optional   Examples listed (default 50)
// @writes   false
// @needs    session
//
// A walk over pages and their placements and a query of the project's functions can disagree:
// functions that exist but sit on no page the walk visits. This names them.
using System;
using System.Collections.Generic;
using Eplan.EplApi.DataModel;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        string prefix = ctx.Args.Require("symbol_prefix");
        if (prefix == "*") prefix = "";
        int max = (int)ctx.Args.Int("max", 50);

        // Pages by identity: two pages can share a name.
        var visited = new HashSet<long>();
        foreach (var page in Pages.All(project))
        {
            long id = Safe.Get(() => (long)page.ObjectIdentifier, 0L);
            if (id != 0) visited.Add(id);
        }

        int matched = 0, onVisited = 0;
        var examples = new List<object>();
        foreach (var function in Functions.All(project))
        {
            ctx.Budget.Check();
            var symbol = Functions.SymbolName(function);
            if (prefix.Length > 0 && !symbol.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
            matched++;
            Page? page = Safe.Object(() => function.Page);
            long pageId = page == null ? 0 : Safe.Get(() => (long)page.ObjectIdentifier, 0L);
            if (pageId != 0 && visited.Contains(pageId)) { onVisited++; continue; }
            if (examples.Count >= max) continue;
            examples.Add(new Dictionary<string, object?>
            {
                // FUNC_DEVICETAG_FULLNAME leaves out the structure prefixes; FUNC_FULLDEVICETAG has them.
                ["dt_no_structures"] = Functions.DeviceTag(function),
                ["dt_full"] = Functions.FullDeviceTag(function),
                ["name"] = Safe.Text(() => function.Name),
                ["visible_name"] = Safe.Text(() => function.VisibleName),
                ["symbol"] = symbol,
                ["library"] = Safe.Text(() => function.SymbolVariant?.Parent?.Parent?.Name),
                ["page"] = page == null ? null : Safe.Text(() => page.Name),
                ["page_type"] = page == null ? null : Safe.Text(() => page.PageType.ToString()),
                ["object_id"] = Safe.Get(() => (long)function.ObjectIdentifier, 0L),
                ["is_main"] = Safe.Text(() => function.IsMainFunction.ToString()),
                ["is_placed"] = Safe.Text(() => function.IsPlaced.ToString()),
                ["category"] = Safe.Text(() => function.Category.ToString()),
            });
        }
        return new
        {
            project = project.ProjectFullName,
            symbol_prefix = prefix,
            pages_a_page_walk_visits = visited.Count,
            functions_matching_prefix = matched,
            on_a_visited_page = onVisited,
            not_reachable_by_a_page_walk = matched - onVisited,
            examples,
        };
    }
}
