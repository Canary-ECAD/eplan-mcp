// @tool     cable_shields
// @desc     Shield functions, and every cable with shields: what GetSourcesAndTargets returns per wire, its function templates, and its connections with colour (#31004) and "shielded by" (#31049).
// @schema   1
// @arg      dt   string  optional   Substring of the cable name
// @arg      max  int     optional   Cables reported (default 10)
// @writes   false
// @needs    session
//
// At most 200 shield functions are listed ("shield_functions_capped" says when there were more);
// "max" limits the cables.
using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.EObjects;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        string? dt = ctx.Args.String("dt");
        int max = (int)ctx.Args.Int("max", 10);
        var finder = new DMObjectsFinder(project);
        var functions = Functions.All(project);

        const int shieldLimit = 200;
        var shields = new List<object>();
        bool shieldsCapped = false;
        foreach (var s in functions.OfType<Shield>())
        {
            if (shields.Count >= shieldLimit) { shieldsCapped = true; break; }
            shields.Add(new Dictionary<string, object?>
            {
                ["name"] = Safe.Text(() => s.Name),
                ["page"] = Safe.Text(() => s.Page?.Name),
                ["placed"] = Safe.Text(() => s.IsPlaced.ToString()),
                ["category"] = Safe.Text(() => s.FunctionCategory.ToString()),
                ["symbol"] = Safe.Text(() => s.SymbolVariant?.SymbolName),
                ["pins"] = Safe.Text(() => string.Join(",", (s.Pins ?? Array.Empty<Pin>()).Select(p => p.Name))),
                ["main"] = Safe.Text(() => s.IsMainFunction.ToString()),
            });
        }

        var connsByCable = new Dictionary<string, List<object>>(StringComparer.OrdinalIgnoreCase);
        foreach (var c in finder.GetConnections(new ConnectionsFilter()) ?? Array.Empty<Connection>())
        {
            ctx.Budget.Check();
            string cable = Safe.Text(() => c.CableDefinitionLine?.Name) ?? "";
            if (cable.Length == 0) continue;
            if (!connsByCable.TryGetValue(cable, out var list)) connsByCable[cable] = list = new List<object>();
            list.Add(new Dictionary<string, object?>
            {
                ["page"] = Safe.Text(() => c.Page?.Name),
                ["colour_31004"] = PropertyReader.Read(c, 31004) ?? "",
                ["shielded_by_31049"] = PropertyReader.Read(c, 31049) ?? "",
                ["start"] = Safe.Text(() => c.StartPin?.ParentFunction?.Name + ":" + c.StartPin?.Name),
                ["end"] = Safe.Text(() => c.EndPin?.ParentFunction?.Name + ":" + c.EndPin?.Name),
                ["start_type"] = Safe.Text(() => c.StartPin?.ParentFunction?.GetType().Name),
                ["end_type"] = Safe.Text(() => c.EndPin?.ParentFunction?.GetType().Name),
            });
        }

        var cables = new List<object>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var cable in functions.OfType<Cable>())
        {
            ctx.Budget.Check();
            string name = Safe.Text(() => cable.Name) ?? "";
            if (!string.IsNullOrEmpty(dt) && name.IndexOf(dt, StringComparison.OrdinalIgnoreCase) < 0) continue;
            // #35102: number of shields; empty throws from ToInt, so read through Safe.
            long nShields = Safe.Get(() => (long)cable.Properties[35102].ToInt(), 0L);
            if (nShields <= 0 || !seen.Add(name)) continue;
            if (cables.Count >= max) break;

            var wires = new List<object>();
            try
            {
                var src = new List<StorableObject>();
                var tgt = new List<StorableObject>();
                cable.GetSourcesAndTargets(src, tgt, true);
                for (int i = 0; i < Math.Max(src.Count, tgt.Count); i++)
                {
                    var a = i < src.Count ? src[i] : null;
                    var b = i < tgt.Count ? tgt[i] : null;
                    wires.Add(new Dictionary<string, object?>
                    {
                        ["src"] = (a as Function)?.Name ?? a?.GetType().Name,
                        ["src_type"] = a?.GetType().Name,
                        ["src_page"] = Safe.Text(() => (a as Function)?.Page?.Name),
                        ["tgt"] = (b as Function)?.Name ?? b?.GetType().Name,
                        ["tgt_type"] = b?.GetType().Name,
                        ["tgt_page"] = Safe.Text(() => (b as Function)?.Page?.Name),
                    });
                }
            }
            catch (Exception ex) { wires.Add(Safe.Error(ex)); }

            var templates = new List<object>();
            try
            {
                foreach (var t in cable.FunctionTemplates ?? Array.Empty<StorableObject>())
                    templates.Add(new Dictionary<string, object?>
                    {
                        ["type"] = t.GetType().Name,
                        ["colour_31004"] = PropertyReader.Read(t, 31004) ?? "",
                        ["shielded_by_31049"] = PropertyReader.Read(t, 31049) ?? "",
                        ["name"] = Safe.Text(() => (t as Function)?.Name),
                    });
            }
            catch (Exception ex) { templates.Add(Safe.Error(ex)); }

            cables.Add(new Dictionary<string, object?>
            {
                ["name"] = name,
                ["page"] = Safe.Text(() => cable.Page?.Name),
                ["shields_35102"] = nShields,
                ["all_wires_35108"] = PropertyReader.Read(cable, 35108),
                ["wires"] = wires,
                ["templates"] = templates,
                ["connections"] = connsByCable.TryGetValue(name, out var cl) ? cl : new List<object>(),
            });
        }
        return new
        {
            project = project.ProjectFullName, shield_functions = shields,
            shield_functions_limit = shieldLimit, shield_functions_capped = shieldsCapped, cables,
        };
    }
}
