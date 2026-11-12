// @tool     function_dump
// @desc     Functions whose name contains a device tag, with their supplementary fields read both as one string and per language (separators escaped), and their property placements.
// @schema   1
// @arg      dt      string  required   Substring of the function name
// @arg      page    string  optional   Substring of the page name
// @arg      max     int     optional   Functions reported (default 10)
// @arg      fields  int     optional   Supplementary fields read per function (default 8)
// @writes   false
// @needs    session
//
// The supplementary field (#20901) is a MultiLangString: read as a plain string and read per
// language it can give different answers, so both are shown, with CR, LF, control characters and
// the pilcrow escaped.
using System;
using System.Collections.Generic;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.Graphics;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        string dt = ctx.Args.Require("dt");
        string? pageWanted = ctx.Args.String("page");
        int max = (int)ctx.Args.Int("max", 10);
        int fields = (int)ctx.Args.Int("fields", 8);

        var hits = new List<object>();
        int scanned = 0;
        foreach (var function in Functions.All(project))
        {
            ctx.Budget.Check();
            scanned++;
            var name = Safe.Text(() => function.Name) ?? "";
            if (name.IndexOf(dt, StringComparison.OrdinalIgnoreCase) < 0) continue;
            var pageName = Safe.Text(() => function.Page?.Name);
            if (!string.IsNullOrEmpty(pageWanted) && (pageName == null || pageName.IndexOf(pageWanted, StringComparison.OrdinalIgnoreCase) < 0)) continue;
            if (hits.Count >= max) break;

            var supplementary = new List<object>();
            for (int i = 1; i <= fields; i++)
                supplementary.Add(new Dictionary<string, object?>
                {
                    ["index"] = i,
                    ["as_string"] = PropertyReader.Escape(PropertyReader.Read(function, PropertyReader.SupplementaryField, i)),
                    ["by_language"] = PropertyReader.EveryLanguage(function, PropertyReader.SupplementaryField, i),
                });

            var row = new Dictionary<string, object?>
            {
                ["name"] = name,
                ["page"] = pageName,
                ["symbol"] = Safe.Text(() => function.SymbolVariant?.SymbolName),
                ["library"] = Safe.Text(() => function.SymbolVariant?.Parent?.Parent?.Name),
                ["variant_nr"] = Safe.Text(() => function.SymbolVariant?.VariantNr.ToString()),
                ["category"] = Safe.Text(() => function.FunctionCategory.ToString()),
                ["is_placed"] = Safe.Text(() => function.IsPlaced.ToString()),
                ["use_local_placements"] = Safe.Text(() => function.UseLocalPropertyPlacements.ToString()),
                // #19307: the active property arrangement.
                ["active_scheme"] = PropertyReader.Escape(PropertyReader.Read(function, 19307, 0)),
                ["supplementary_20901"] = supplementary,
            };

            var placements = new List<object>();
            try
            {
                foreach (var placement in function.PropertyPlacements ?? Array.Empty<PropertyPlacement>())
                    placements.Add(new Dictionary<string, object?>
                    {
                        ["property_id"] = Safe.Text(() => placement.DisplayedProperty.AsInt.ToString()),
                        ["x"] = Safe.Text(() => placement.Location.X.ToString("F4")),
                        ["y"] = Safe.Text(() => placement.Location.Y.ToString("F4")),
                    });
            }
            catch (Exception ex) { row["placements_err"] = Safe.Error(ex); }
            row["placement_count"] = placements.Count;
            row["placements"] = placements;
            hits.Add(row);
        }
        return new { project = project.ProjectFullName, dt, page = pageWanted, functions_scanned = scanned, hits };
    }
}
