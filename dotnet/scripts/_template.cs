// @tool     my_tool_name
// @desc     One sentence: what this script does and what it returns.
// @schema   1
// @requires core>=0.1
// @arg      page   string  optional  Page name to limit the work to
// @writes   false
// @needs    session
//
// A script is either a full class like this one, or just a statement body (a "snippet") that is
// wrapped into Run(ScriptContext ctx) for you. Return plain data (numbers, strings, lists,
// dictionaries, anonymous objects); EPLAN objects are reported by type and text only.
//
// The run already holds a LockingStep. To write: declare '// @writes true', run on a scratch clone,
// and lock each object with ctx.Lock(obj) before changing it. Call ctx.Budget.Check() in long loops.
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.DataModel;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var pages = new DMObjectsFinder(project).GetPages(null);
        var wanted = ctx.Args.String("page");
        var rows = new List<object>();
        foreach (var page in pages)
        {
            ctx.Budget.Check();
            if (wanted != null && page.Name != wanted) continue;
            rows.Add(new { page = page.Name, placements = page.AllPlacements.Length });
        }
        return new { project = project.ProjectName, pages = rows };
    }
}
