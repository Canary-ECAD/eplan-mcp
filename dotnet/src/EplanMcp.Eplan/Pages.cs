using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.DataModel;

namespace EplanMcp.Eplan
{
    /// <summary>Finding pages and what is placed on them.</summary>
    public static class Pages
    {
        /// <summary>Every page of the project (never null).</summary>
        public static Page[] All(Project project) => new DMObjectsFinder(project).GetPages(null) ?? Array.Empty<Page>();

        /// <summary>True when the page's Name or IdentifyingName equals <paramref name="name"/>
        /// (case-insensitive).</summary>
        public static bool Matches(Page page, string? name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            return string.Equals(Safe.Text(() => page.Name), name, StringComparison.OrdinalIgnoreCase)
                || string.Equals(Safe.Text(() => page.IdentifyingName), name, StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// One page by name: an exact Name / IdentifyingName match, else (when
        /// <paramref name="allowPartial"/>) the first page whose Name contains it. Null with an
        /// <paramref name="error"/> naming some of the pages that do exist.
        /// </summary>
        public static Page? Find(Project project, string? name, out string? error, bool allowPartial = false)
        {
            error = null;
            if (string.IsNullOrEmpty(name)) { error = "no page name given"; return null; }
            var pages = All(project);
            var page = pages.FirstOrDefault(p => Matches(p, name));
            if (page == null && allowPartial)
                page = pages.FirstOrDefault(p => (Safe.Text(() => p.Name) ?? "").IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0);
            if (page == null)
                error = $"page '{name}' not found (have: {string.Join(", ", pages.Take(20).Select(p => Safe.Text(() => p.Name)))})";
            return page;
        }

        /// <summary>The page, or a refusal (<c>{"error": ...}</c>) carrying the not-found message.</summary>
        public static Page Require(Project project, string? name, bool allowPartial = false) =>
            Find(project, name, out var error, allowPartial) ?? throw new EplanMcp.Scripting.Core.ScriptRefusedException(error ?? "page not found");

        /// <summary>Everything placed on the page, through the finder (never null).</summary>
        public static Placement[] Placements(Page page) =>
            new DMObjectsFinder(page.Project).GetPlacements(new PlacementsFilter { Page = page }) ?? Array.Empty<Placement>();

        /// <summary>
        /// True when the page is in scope: no prefix and no names means every page; else an exact
        /// name from <paramref name="names"/>, or a Name / IdentifyingName starting with
        /// <paramref name="prefix"/>.
        /// </summary>
        public static bool InScope(Page page, string? prefix, ICollection<string>? names)
        {
            names ??= Array.Empty<string>();
            if (string.IsNullOrEmpty(prefix) && names.Count == 0) return true;
            if (names.Any(n => Matches(page, n))) return true;
            if (string.IsNullOrEmpty(prefix)) return false;
            return new[] { Safe.Text(() => page.Name), Safe.Text(() => page.IdentifyingName) }
                .Any(n => n != null && n.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
        }
    }
}
