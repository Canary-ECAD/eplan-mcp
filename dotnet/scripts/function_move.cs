// @tool     function_move
// @desc     Moves placed functions on one page to absolute page coordinates. Each move names one function by handle or by its exact name on that page; a name that matches more or fewer than one function is refused, and if any move fails its checks nothing is moved. Reads each position back. Dry run by default.
// @schema   1
// @arg      page   string  required   Page Name or IdentifyingName (exact)
// @arg      moves  list    required   JSON array of {handle or name, x, y}; a missing x or y keeps the current value
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). handle is the one the live tools
// report (eplan_live_read_page); name is the function's placement name. A function named twice in
// one call is refused. Every move is checked before any is written: one failed check means nothing
// moves. not_stuck lists the moves whose read-back position differs.
using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var page = Pages.Require(project, ctx.Args.Require("page"));
        var functions = Functions.OnPage(page);
        var moved = new List<Dictionary<string, object?>>();
        var targets = new List<(Function f, PointD to, Dictionary<string, object?> row)>();
        var seen = new HashSet<Function>();
        // Check every move first. RequireRows: a 'moves' that parses to nothing is an error,
        // never "moved nothing, ok".
        foreach (var spec in PlainJson.RequireRows(ctx.Args, "moves"))
        {
            ctx.Budget.Check();
            string handle = PlainJson.Str(spec, "handle"), name = PlainJson.Str(spec, "name");
            var row = new Dictionary<string, object?> { ["handle"] = handle.Length > 0 ? handle : null, ["name"] = name.Length > 0 ? name : null };
            moved.Add(row);
            try
            {
                if (handle.Length == 0 && name.Length == 0) { row["error"] = "each move needs a handle or a name"; continue; }
                if (!spec.ContainsKey("x") && !spec.ContainsKey("y")) { row["error"] = "each move needs x and/or y"; continue; }
                var hits = handle.Length > 0
                    ? functions.Where(f => Safe.Text(() => f.ToStringIdentifier()) == handle).ToList()
                    : Functions.Named(functions, name);
                if (hits.Count != 1)
                {
                    row["error"] = handle.Length > 0 ? $"no function with handle '{handle}' on the page"
                                                     : $"{hits.Count} functions named '{name}' on the page; use its handle";
                    continue;
                }
                var f = hits[0];
                if (!seen.Add(f)) { row["error"] = "this function is already moved by an earlier entry"; continue; }
                row["name"] = Safe.Text(() => f.Name);
                row["handle"] = Safe.Text(() => f.ToStringIdentifier());
                var from = f.Location;
                var to = new PointD(spec.ContainsKey("x") ? PlainJson.Num(spec, "x") : from.X, spec.ContainsKey("y") ? PlainJson.Num(spec, "y") : from.Y);
                row["from_x"] = from.X; row["from_y"] = from.Y;
                row["to_x"] = to.X; row["to_y"] = to.Y;
                targets.Add((f, to, row));
            }
            catch (Exception ex) { row["error"] = Safe.Error(ex); }
        }
        int errors = moved.Count(r => r.ContainsKey("error"));
        string? refusal = errors > 0 ? $"{errors} move(s) failed their checks; nothing was moved." : null;
        if (refusal != null || ctx.DryRun)
            return new { project = project.ProjectName, page = page.Name, dry_run = ctx.DryRun, error = refusal, errors, moved };

        foreach (var (f, to, row) in targets)
        {
            ctx.Budget.Check();
            try
            {
                ctx.Lock(f);
                f.Location = to;
                var after = f.Location;
                row["after_x"] = after.X;
                row["after_y"] = after.Y;
                row["sticks"] = Math.Abs(after.X - to.X) < 0.0001 && Math.Abs(after.Y - to.Y) < 0.0001;
            }
            catch (Exception ex) { row["error"] = Safe.Error(ex); row["sticks"] = false; }
        }
        return new
        {
            project = project.ProjectName, page = page.Name, dry_run = false,
            errors = moved.Count(r => r.ContainsKey("error")),
            not_stuck = moved.Where(r => r.TryGetValue("sticks", out var s) && s is false).Select(r => r["name"]).ToList(),
            moved,
        };
    }
}
