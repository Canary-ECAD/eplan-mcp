using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.IO;
using System.Linq;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.HEServices;
using Eplan.EplApi.MasterData;

namespace EplanMcp.Eplan
{
    /// <summary>Reading symbol libraries through the MasterData API (opened read-only, always closed).</summary>
    public static class SymbolLibraries
    {
        /// <summary>SYMB_PROPERTYINSTANCESET: the named property-arrangement sets registered on a
        /// symbol, indexed 1..64.</summary>
        public const int PropertyArrangementSets = 16050;

        /// <summary>
        /// The .slk path of a library given by registered NAME or by path. A name is looked up in
        /// the master data system entries (which may hold bare file names), then beside any rooted
        /// entry, then in the symbols folder. <paramref name="rawEntry"/> is the entry that matched.
        /// </summary>
        public static string? ResolvePath(string? library, out string? rawEntry)
        {
            rawEntry = null;
            if (string.IsNullOrEmpty(library)) return null;

            if (library!.IndexOf(Path.DirectorySeparatorChar) >= 0 || library.IndexOf(Path.AltDirectorySeparatorChar) >= 0)
            {
                rawEntry = library;
                return string.Equals(Path.GetExtension(library), ".sdb", StringComparison.OrdinalIgnoreCase)
                    ? Path.ChangeExtension(library, ".slk") : library;
            }

            string bareName = library;
            var ext = Path.GetExtension(library);
            if (string.Equals(ext, ".slk", StringComparison.OrdinalIgnoreCase) || string.Equals(ext, ".sdb", StringComparison.OrdinalIgnoreCase))
                bareName = Path.GetFileNameWithoutExtension(library);

            try
            {
                StringCollection entries;
                using (var md = new Masterdata()) entries = md.SystemEntries;
                if (entries == null) return null;
                var all = entries.Cast<string>().Where(e => !string.IsNullOrEmpty(e)).ToList();

                var matched = all.FirstOrDefault(e =>
                    string.Equals(Path.GetExtension(e), ".slk", StringComparison.OrdinalIgnoreCase) &&
                    string.Equals(Path.GetFileNameWithoutExtension(e), bareName, StringComparison.OrdinalIgnoreCase));
                if (matched == null) return null;
                rawEntry = matched;
                if (Path.IsPathRooted(matched) && File.Exists(matched)) return matched;

                foreach (var entry in all.Where(Path.IsPathRooted))
                {
                    var e = Path.GetExtension(entry);
                    if (!string.Equals(e, ".slk", StringComparison.OrdinalIgnoreCase) && !string.Equals(e, ".sdb", StringComparison.OrdinalIgnoreCase)) continue;
                    var dir = Path.GetDirectoryName(entry);
                    if (string.IsNullOrEmpty(dir)) continue;
                    var candidate = Path.Combine(dir, Path.GetFileName(matched));
                    if (File.Exists(candidate)) return candidate;
                }

                try
                {
                    var symbolsDir = new ProjectManager().Paths?.Symbols;
                    if (!string.IsNullOrEmpty(symbolsDir))
                    {
                        var candidate = Path.Combine(symbolsDir, Path.GetFileName(matched));
                        if (File.Exists(candidate)) return candidate;
                    }
                }
                catch (Exception) { }
                return matched;
            }
            catch (Exception) { return null; }
        }

        /// <summary>
        /// Inspects a library. <paramref name="mode"/>:
        /// "symbols" (every symbol: name, id, version, variants),
        /// "variant" (one variant of <paramref name="symbol"/>: connection points, graphic element
        /// and property placement counts), or "arrangements" (the symbol's property-arrangement
        /// schemas and its registered arrangement names, #16050).
        /// </summary>
        public static Dictionary<string, object?> Inspect(string? library, string mode, string? symbol, int variant)
        {
            var data = new Dictionary<string, object?>
            {
                ["library"] = library, ["mode"] = mode, ["symbol"] = symbol, ["variant"] = variant,
                ["resolved_slk"] = null, ["resolved_sdb"] = null, ["raw_entry"] = null, ["err"] = null,
            };
            if (string.IsNullOrEmpty(library)) { data["err"] = "a library (registered name or file path) is required"; return data; }

            var slk = ResolvePath(library, out var rawEntry);
            data["raw_entry"] = rawEntry;
            data["resolved_slk"] = slk;
            if (string.IsNullOrEmpty(slk)) { data["err"] = "Could not resolve library '" + library + "' to an .slk path."; return data; }
            var sdb = Path.ChangeExtension(slk, ".sdb");
            data["resolved_sdb"] = sdb;

            MDSymbolLibrary? lib = null;
            try
            {
                lib = MDSymbolLibrary.Open(sdb, MDSymbolLibrary.Mode.ReadOnly);
                if (string.Equals(mode, "symbols", StringComparison.OrdinalIgnoreCase)) FillSymbols(lib, data);
                else if (string.Equals(mode, "variant", StringComparison.OrdinalIgnoreCase)) FillVariant(lib, symbol, variant, data);
                else if (string.Equals(mode, "arrangements", StringComparison.OrdinalIgnoreCase)) FillArrangements(lib, symbol, data);
                else data["err"] = "Unknown mode '" + mode + "'. Expected symbols|variant|arrangements.";
            }
            catch (Exception ex) { data["err"] = Safe.Error(ex); }
            finally
            {
                // A failed close must not fail the report.
                Safe.Try(() => lib?.Close());
            }
            return data;
        }

        /// <summary>The symbol named <paramref name="name"/> (case-insensitive), or null.</summary>
        public static MDSymbol? FindSymbol(MDSymbolLibrary lib, string name)
        {
            foreach (var s in Safe.Object(() => lib.Symbols) ?? Array.Empty<MDSymbol>())
                if (s != null && string.Equals(Safe.Text(() => s.Name), name, StringComparison.OrdinalIgnoreCase)) return s;
            return null;
        }

        private static void FillSymbols(MDSymbolLibrary lib, Dictionary<string, object?> data)
        {
            var list = new List<object>();
            foreach (var s in lib.Symbols ?? Array.Empty<MDSymbol>())
            {
                if (s == null) continue;
                var item = new Dictionary<string, object?>();
                var errors = new List<string>();
                Safe.Field(item, errors, "name", () => s.Name);
                Safe.Field(item, errors, "id", () => (int)s.Id);
                Safe.Field(item, errors, "version", () => s.Properties?.SYMB_VERSION?.ToString());
                try { item["variants"] = (s.Variants ?? Array.Empty<MDSymbolVariant>()).Where(v => v != null).Select(v => (object)(int)v.Index).ToList(); }
                catch (Exception ex) { item["variants"] = new List<object>(); errors.Add("variants: " + Safe.Error(ex)); }
                item["err"] = Safe.Join(errors);
                list.Add(item);
            }
            data["symbol_count"] = list.Count;
            data["symbols"] = list;
        }

        private static void FillVariant(MDSymbolLibrary lib, string? symbolName, int variantNr, Dictionary<string, object?> data)
        {
            data["symbol_found"] = false;
            data["variant_found"] = false;
            data["connection_point_count"] = null;
            data["connection_points"] = new List<object>();
            data["graphic_element_count"] = null;
            data["property_placement_count"] = null;
            if (string.IsNullOrEmpty(symbolName)) { data["err"] = "mode 'variant' needs a symbol name."; return; }

            var symbol = FindSymbol(lib, symbolName!);
            if (symbol == null) { data["err"] = "Symbol '" + symbolName + "' not found in the library."; return; }
            data["symbol_found"] = true;

            MDSymbolVariant? variant;
            try { variant = (symbol.Variants ?? Array.Empty<MDSymbolVariant>()).FirstOrDefault(v => v != null && v.Index == variantNr); }
            catch (Exception ex) { data["err"] = "Variants: " + Safe.Error(ex); return; }
            if (variant == null)
            {
                data["err"] = "Variant " + variantNr.ToString(CultureInfo.InvariantCulture) + " does not exist on symbol '" + symbolName + "'.";
                return;
            }
            data["variant_found"] = true;

            var cps = new List<object>();
            try
            {
                var points = variant.SymbolConnectionPoints ?? Array.Empty<MDSymbolConnectionPoint>();
                data["connection_point_count"] = points.Length;
                int index = 0;
                foreach (var cp in points)
                {
                    index++;
                    var item = new Dictionary<string, object?> { ["index"] = index };
                    var errors = new List<string>();
                    try { var loc = cp.Location; item["x"] = loc.X; item["y"] = loc.Y; }
                    catch (Exception ex) { item["x"] = null; item["y"] = null; errors.Add("location: " + Safe.Error(ex)); }
                    Safe.Field(item, errors, "direction", () => cp.Direction.ToString());
                    item["err"] = Safe.Join(errors);
                    cps.Add(item);
                }
            }
            catch (Exception ex) { data["connection_points_err"] = Safe.Error(ex); }
            data["connection_points"] = cps;

            try { data["graphic_element_count"] = variant.AsGroup?.SubPlacements?.Length ?? 0; }
            catch (Exception ex) { data["graphic_element_count_err"] = Safe.Error(ex); }
            try { data["property_placement_count"] = variant.PropertyPlacements?.Length ?? 0; }
            catch (Exception ex) { data["property_placement_count_err"] = Safe.Error(ex); }
        }

        private static void FillArrangements(MDSymbolLibrary lib, string? symbolName, Dictionary<string, object?> data)
        {
            data["symbol_found"] = false;
            data["schema_count"] = null;
            data["schemas"] = new List<object>();
            data["registered_names"] = new List<object>();
            if (string.IsNullOrEmpty(symbolName)) { data["err"] = "mode 'arrangements' needs a symbol name."; return; }

            var symbol = FindSymbol(lib, symbolName!);
            if (symbol == null) { data["err"] = "Symbol '" + symbolName + "' not found in the library."; return; }
            data["symbol_found"] = true;

            var schemas = new List<object>();
            try
            {
                foreach (var s in symbol.PropertyPlacementsSchemas?.All ?? Array.Empty<MDSymbol.MDPropertyPlacementsSchema>())
                {
                    if (s == null) continue;
                    var item = new Dictionary<string, object?>();
                    var errors = new List<string>();
                    Safe.Field(item, errors, "id", () => (int)s.Id);
                    Safe.Field(item, errors, "name", () => s.Name?.ToString());
                    item["err"] = Safe.Join(errors);
                    schemas.Add(item);
                }
                data["schema_count"] = schemas.Count;
            }
            catch (Exception ex) { data["schemas_err"] = Safe.Error(ex); }
            data["schemas"] = schemas;

            var registered = new List<object>();
            for (int i = 1; i <= 64; i++)
            {
                string? value;
                try
                {
                    var props = symbol.Properties;
                    if (props == null) break;
                    // MasterData property lists take MDAnyPropertyId, a different numbering space
                    // from the DataModel's AnyPropertyId; the two do not convert.
                    value = props[(MDAnyPropertyId)PropertyArrangementSets, i]?.ToString();
                }
                catch (Exception) { continue; }
                if (!string.IsNullOrEmpty(value)) registered.Add(new Dictionary<string, object?> { ["index"] = i, ["name"] = value });
            }
            data["registered_names"] = registered;
        }
    }
}
