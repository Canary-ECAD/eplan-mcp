using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.HEServices;

namespace EplanMcp.Eplan
{
    /// <summary>Reading the editor (GED) selection and the page-navigator selection.</summary>
    public static class Selection
    {
        /// <summary>
        /// The current selection: {project, selection, selection_count, selection_recursive,
        /// selection_recursive_count, pages, page_count, currently_edited, is_page_selected}, plus
        /// "*_err" keys for parts that could not be read. Entries are <see cref="Describe.Storable"/>
        /// rows; pages are {name, identifying_name, page_type, handle}.
        /// </summary>
        public static Dictionary<string, object?> Read()
        {
            var data = new Dictionary<string, object?>
            {
                ["project"] = null, ["selection"] = new List<object>(), ["selection_count"] = 0,
                ["selection_recursive"] = new List<object>(), ["selection_recursive_count"] = 0,
                ["pages"] = new List<object>(), ["page_count"] = 0, ["currently_edited"] = null, ["is_page_selected"] = null,
            };

            SelectionSet ss;
            try
            {
                // LockSelectionByDefault must be cleared BEFORE anything is read, or the read
                // locks the project (S063110).
                ss = new SelectionSet { LockSelectionByDefault = false };
            }
            catch (Exception ex) { data["err"] = Safe.Error(ex); return data; }

            try
            {
                // false: never show the project-selection dialog.
                var project = ss.GetCurrentProject(false);
                data["project"] = project == null ? null : Safe.Text(() => project.ProjectFullName);
            }
            catch (Exception ex) { data["project_err"] = Safe.Error(ex); }

            try
            {
                var list = (ss.Selection ?? Array.Empty<StorableObject>()).Where(o => o != null).Select(o => (object)Describe.Storable(o)).ToList();
                data["selection"] = list;
                data["selection_count"] = list.Count;
            }
            catch (Exception ex) { data["selection_err"] = Safe.Error(ex); }

            try
            {
                var list = (ss.SelectionRecursive ?? Array.Empty<StorableObject>()).Where(o => o != null).Select(o => (object)Describe.Storable(o)).ToList();
                data["selection_recursive"] = list;
                data["selection_recursive_count"] = list.Count;
            }
            catch (Exception ex) { data["selection_recursive_err"] = Safe.Error(ex); }

            try
            {
                var list = new List<object>();
                foreach (var page in ss.GetSelectedPages() ?? Array.Empty<Page>())
                {
                    if (page == null) continue;
                    list.Add(new Dictionary<string, object?>
                    {
                        ["name"] = Safe.Text(() => page.Name),
                        ["identifying_name"] = Safe.Text(() => page.IdentifyingName),
                        ["page_type"] = Safe.Text(() => page.PageType.ToString()),
                        ["handle"] = Describe.Handle(page),
                    });
                }
                data["pages"] = list;
                data["page_count"] = list.Count;
            }
            catch (Exception ex) { data["pages_err"] = Safe.Error(ex); }

            try
            {
                var edited = ss.CurrentlyEdited;
                data["currently_edited"] = edited == null ? null : Describe.Storable(edited);
            }
            catch (Exception ex) { data["currently_edited_err"] = Safe.Error(ex); }

            try { data["is_page_selected"] = ss.IsPageSelected; }
            catch (Exception ex) { data["is_page_selected_err"] = Safe.Error(ex); }

            return data;
        }

        /// <summary>The names (Name and IdentifyingName) of the pages in a <see cref="Read"/> result.</summary>
        public static HashSet<string> SelectedPageNames(Dictionary<string, object?> selection)
        {
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (selection.TryGetValue("pages", out var pages) && pages is List<object> entries)
                foreach (var entry in entries.OfType<Dictionary<string, object?>>())
                    foreach (var key in new[] { "name", "identifying_name" })
                        if (entry.TryGetValue(key, out var v) && v is string s) names.Add(s);
            return names;
        }
    }
}
