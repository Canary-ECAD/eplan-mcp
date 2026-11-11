using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.DataModel;

namespace EplanMcp.Eplan
{
    /// <summary>Finding functions.</summary>
    public static class Functions
    {
        /// <summary>Every function in the project database, placed or not (never null).</summary>
        public static Function[] All(Project project) =>
            new DMObjectsFinder(project).GetFunctions(new FunctionsFilter()) ?? Array.Empty<Function>();

        /// <summary>The functions placed on the page.</summary>
        public static List<Function> OnPage(Page page) => Pages.Placements(page).OfType<Function>().ToList();

        /// <summary>FUNC_DEVICETAG_FULLNAME: the device tag WITHOUT the structure prefixes; null when
        /// unreadable.</summary>
        public static string? DeviceTag(Function f) => Safe.Text(() => f.Properties.FUNC_DEVICETAG_FULLNAME?.ToString());

        /// <summary>FUNC_FULLDEVICETAG: the whole device tag including structures.</summary>
        public static string? FullDeviceTag(Function f) => Safe.Text(() => f.Properties.FUNC_FULLDEVICETAG?.ToString());

        /// <summary>The symbol name the function is placed with, or "".</summary>
        public static string SymbolName(Function f) => Safe.Text(() => f.SymbolVariant?.SymbolName) ?? "";

        /// <summary>
        /// One placed function on a page: device tag equal to <paramref name="deviceTag"/> (when
        /// given) and symbol name starting with <paramref name="symbolPrefix"/> (when given), the
        /// <paramref name="occurrence"/>-th (0-based) of the matches. A symbol prefix is the practical
        /// selector for symbols that carry no device tag.
        /// </summary>
        public static Function? Find(Page page, string? deviceTag, string? symbolPrefix, int occurrence, out string? error)
        {
            error = null;
            var matches = OnPage(page)
                .Where(f => string.IsNullOrEmpty(deviceTag) || string.Equals(DeviceTag(f), deviceTag, StringComparison.OrdinalIgnoreCase))
                .Where(f => string.IsNullOrEmpty(symbolPrefix) || SymbolName(f).StartsWith(symbolPrefix, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (matches.Count == 0)
            {
                error = $"no function matching device tag '{deviceTag}' / symbol prefix '{symbolPrefix}' on page '{Safe.Text(() => page.Name)}'";
                return null;
            }
            if (occurrence < 0 || occurrence >= matches.Count)
            {
                error = $"occurrence {occurrence} out of range - the filter matched {matches.Count} function(s)";
                return null;
            }
            return matches[occurrence];
        }

        /// <summary>The functions on the page whose placement Name equals <paramref name="name"/>
        /// (case-insensitive), skipping removed ones.</summary>
        public static List<Function> Named(IEnumerable<Function> functions, string? name) =>
            functions.Where(f => Safe.Get(() => f.IsValid, false)
                                 && string.Equals(Safe.Text(() => f.Name), name, StringComparison.OrdinalIgnoreCase)).ToList();
    }
}
