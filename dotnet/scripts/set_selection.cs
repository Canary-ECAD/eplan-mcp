// @tool     set_selection
// @desc     Selects pages of the target project in the page navigator (and optionally everything on them in the editor), then reads the selection back.
// @schema   1
// @arg      pages               list    optional   Page names to select
// @arg      page                string  optional   One more page name
// @arg      select_all_on_page  bool    optional   Also open each page and select all its placements in the editor
// @arg      clear               bool    optional   Clear the current selection first
// @writes   true
// @needs    gui
// @unsafe
//
// Changes the selection, not project data. It is '@unsafe' because a writing script may not
// otherwise touch the selection; every page it selects is resolved in ctx.Project only. "verified"
// is true when every requested page comes back from the page-navigator selection.
using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Linq;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.HEServices;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var requested = ctx.Args.List("pages").Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        var single = ctx.Args.String("page");
        if (!string.IsNullOrEmpty(single) && !requested.Contains(single, StringComparer.OrdinalIgnoreCase)) requested.Add(single!);
        bool selectAll = ctx.Args.Bool("select_all_on_page");
        bool clear = ctx.Args.Bool("clear");
        var data = new Dictionary<string, object?> { ["project"] = project.ProjectFullName, ["requested_pages"] = requested };
        if (ctx.DryRun) { data["dry_run"] = true; return data; }

        if (clear)
        {
            try { using (var edit = new Edit()) edit.ClearSelection(); data["cleared"] = true; }
            catch (Exception ex) { data["clear_err"] = Safe.Error(ex); }
        }

        var all = Pages.All(project);
        var resolved = new List<Page>();
        var unresolved = new List<string>();
        foreach (var name in requested)
        {
            var match = all.FirstOrDefault(p => Pages.Matches(p, name));
            if (match == null) unresolved.Add(name); else resolved.Add(match);
        }
        data["resolved_pages"] = resolved.Select(p => new { name = Safe.Text(() => p.Name), identifying_name = Safe.Text(() => p.IdentifyingName) }).ToList();
        data["unresolved_pages"] = unresolved;

        if (resolved.Count > 0)
        {
            // The page-navigator selection is what GetSelectedPages() reports; an open page is not it.
            try { using (var edit = new Edit()) edit.SynchronizeObjectsToNavigators(resolved.Cast<StorableObject>().ToArray()); data["navigator_ok"] = true; }
            catch (Exception ex) { data["navigator_err"] = Safe.Error(ex); }
        }

        if (selectAll && resolved.Count > 0)
        {
            var opened = new List<string?>();
            var ids = new StringCollection();
            var errors = new List<string>();
            // Edit wants the full link file path (.elk), not the project name.
            string link = project.ProjectLinkFilePath;
            foreach (var page in resolved)
            {
                ctx.Budget.Check();
                // An editor selection exists only on an open page.
                try { using (var edit = new Edit()) edit.OpenPageWithName(link, page.Name); opened.Add(Safe.Text(() => page.Name)); }
                catch (Exception ex) { errors.Add("open '" + Safe.Text(() => page.Name) + "': " + Safe.Error(ex)); }
                foreach (var placement in Pages.Placements(page))
                {
                    var id = placement == null ? null : Describe.Handle(placement);
                    if (id != null) ids.Add(id);
                }
            }
            data["opened_pages"] = opened;
            data["ged_object_ids"] = ids.Cast<string>().ToList();
            data["ged_object_count"] = ids.Count;
            if (ids.Count > 0)
            {
                try { using (var edit = new Edit()) edit.SelectObjects(link, ids, true); data["ged_ok"] = true; }
                catch (Exception ex) { errors.Add("SelectObjects: " + Safe.Error(ex)); }
            }
            if (errors.Count > 0) data["ged_err"] = string.Join(" | ", errors);
        }

        var selection = Selection.Read();
        data["selection"] = selection;
        var selected = Selection.SelectedPageNames(selection);
        data["verified"] = requested.Count > 0 && requested.All(selected.Contains);
        return data;
    }
}
