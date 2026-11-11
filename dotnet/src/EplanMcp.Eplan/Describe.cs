using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.Graphics;

namespace EplanMcp.Eplan
{
    /// <summary>
    /// EPLAN objects as plain dictionaries for a script result. Every field is read on its own; a
    /// field that throws is null and its error is collected in "err".
    /// </summary>
    public static class Describe
    {
        /// <summary>"TypeId/ObjectId/0": the handle form Edit.SelectObjects takes (0 = persistent).
        /// Null when unreadable.</summary>
        public static string? Handle(StorableObject obj)
        {
            try
            {
                return obj.TypeIdentifier.ToString(CultureInfo.InvariantCulture) + "/" +
                       obj.ObjectIdentifier.ToString(CultureInfo.InvariantCulture) + "/0";
            }
            catch (Exception) { return null; }
        }

        /// <summary>{type, layer_name, layer_id, x, y, err}.</summary>
        public static Dictionary<string, object?> Placement(Placement p)
        {
            var item = new Dictionary<string, object?>();
            var errors = new List<string>();
            Safe.Field(item, errors, "type", () => p.GetType().Name);
            if (p is GraphicalPlacement g)
            {
                Safe.Field(item, errors, "layer_name", () => g.Layer?.Name);
                Safe.Field(item, errors, "layer_id", () => (int)g.LayerId);
            }
            else { item["layer_name"] = null; item["layer_id"] = null; }
            AddLocation(item, errors, () => p.Location);
            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>
        /// {type, raw_text_contents, display_string, writable, x, y, err}. Takes TextBase, not Text:
        /// a PropertyPlacement (device tag, description) derives from TextBase directly and would be
        /// missed by OfType&lt;Text&gt;(). Only a plain Text stores its own contents (and is writable);
        /// a PropertyPlacement shows a property of its owner.
        /// </summary>
        public static Dictionary<string, object?> Text(TextBase t)
        {
            var item = new Dictionary<string, object?>();
            var errors = new List<string>();
            Safe.Field(item, errors, "type", () => t.GetType().Name);
            // TEXT_CONTENTS is declared only on Text's own property list and the by-name indexer
            // fails for it, so read it through the typed accessor.
            if (t is Text asText) Safe.Field(item, errors, "raw_text_contents", () => asText.Properties.TEXT_CONTENTS.ToString());
            else item["raw_text_contents"] = null;
            Safe.Field(item, errors, "display_string", () => t.GetDisplayString());
            item["writable"] = t is Text;
            AddLocation(item, errors, () => t.Location);
            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>{type, name, visible_name, connection_point_count, err}.</summary>
        public static Dictionary<string, object?> Function(Function f)
        {
            var item = new Dictionary<string, object?>();
            var errors = new List<string>();
            Safe.Field(item, errors, "type", () => f.GetType().Name);
            Safe.Field(item, errors, "name", () => f.Name);
            Safe.Field(item, errors, "visible_name", () => f.VisibleName);
            Safe.Field(item, errors, "connection_point_count", () => f.ConnectionPointPositions?.Length ?? 0);
            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>
        /// One function in depth: page, device tag, type, names, optional string id, connection
        /// points (designation from the Pin, name from the ConnectionPointPosition, per index),
        /// supplementary fields 1 and 2 (raw), the active property arrangement and the symbol.
        /// The string id is opt-in: it is valid only while the project stays open, so it makes two
        /// otherwise equal reports differ.
        /// </summary>
        public static Dictionary<string, object?> FunctionFull(Function function, string? pageName, string? deviceTag, bool withId)
        {
            var item = new Dictionary<string, object?> { ["page"] = pageName, ["device_tag"] = deviceTag };
            var errors = new List<string>();
            Safe.Field(item, errors, "type", () => function.GetType().Name);
            Safe.Field(item, errors, "name", () => function.Name);
            Safe.Field(item, errors, "visible_name", () => function.VisibleName);
            if (withId) Safe.Field(item, errors, "id", () => function.ToStringIdentifier());

            var cps = new List<object>();
            int cpCount = 0;
            try
            {
                var positions = function.ConnectionPointPositions ?? Array.Empty<ConnectionPointPosition>();
                cpCount = positions.Length;
                Pin[] pins;
                try { pins = function.Pins ?? Array.Empty<Pin>(); }
                catch (Exception ex) { pins = Array.Empty<Pin>(); errors.Add("Pins: " + Safe.Error(ex)); }

                for (int i = 0; i < Math.Max(positions.Length, pins.Length); i++)
                {
                    var cp = new Dictionary<string, object?> { ["index"] = i + 1, ["designation"] = null, ["name"] = null };
                    var cpErrors = new List<string>();
                    if (i < pins.Length && pins[i] != null) { var pin = pins[i]; Safe.Field(cp, cpErrors, "designation", () => pin.Designation); }
                    if (i < positions.Length && positions[i] != null) { var pos = positions[i]; Safe.Field(cp, cpErrors, "name", () => pos.Name); }
                    cp["err"] = Safe.Join(cpErrors);
                    cps.Add(cp);
                }
            }
            catch (Exception ex) { errors.Add("connection_points: " + Safe.Error(ex)); }
            item["connection_point_count"] = cpCount;
            item["connection_points"] = cps;

            item["supplementary_1"] = PropertyReader.TryRead(function, (AnyPropertyId)PropertyReader.SupplementaryField, 1, out var e1);
            if (e1 != null) errors.Add("#20901[1]: " + e1);
            item["supplementary_2"] = PropertyReader.TryRead(function, (AnyPropertyId)PropertyReader.SupplementaryField, 2, out var e2);
            if (e2 != null) errors.Add("#20901[2]: " + e2);

            Safe.Field(item, errors, "instance_active_propertyset", () => function.Properties.INSTANCE_ACTIVE_PROPERTYSET?.ToString());

            item["symbol_name"] = null;
            item["symbol_library"] = null;
            item["variant_nr"] = null;
            try
            {
                var variant = function.SymbolVariant;
                if (variant != null)
                {
                    Safe.Field(item, errors, "symbol_name", () => variant.SymbolName);
                    Safe.Field(item, errors, "symbol_library", () => variant.SymbolLibraryName);
                    Safe.Field(item, errors, "variant_nr", () => variant.VariantNr);
                }
            }
            catch (Exception ex) { errors.Add("SymbolVariant: " + Safe.Error(ex)); }

            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>{type, type_name, handle, name, identifying_name, page, err}. For a function the
        /// identifying name is its device tag.</summary>
        public static Dictionary<string, object?> Storable(StorableObject obj)
        {
            var item = new Dictionary<string, object?>();
            var errors = new List<string>();
            Safe.Field(item, errors, "type", () => obj.GetType().Name);
            Safe.Field(item, errors, "type_name", () => obj.GetTypeName());
            item["handle"] = Handle(obj);
            item["name"] = null;
            item["identifying_name"] = null;
            item["page"] = null;

            if (obj is Page page)
            {
                item["name"] = Safe.Text(() => page.Name);
                item["identifying_name"] = Safe.Text(() => page.IdentifyingName);
                item["page"] = item["name"];
            }
            else
            {
                if (obj is Function function)
                {
                    item["name"] = Safe.Text(() => function.Name);
                    item["identifying_name"] = Functions.DeviceTag(function);
                }
                if (obj is Placement placement) Safe.Field(item, errors, "page", () => placement.Page?.Name);
            }
            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>
        /// A page with its placements, texts and/or functions, each list capped at
        /// <paramref name="max"/> (totals are always counted).
        /// </summary>
        public static Dictionary<string, object?> Page(Page page, bool placements, bool texts, bool functions, int max)
        {
            var result = new Dictionary<string, object?>
            {
                ["name"] = Safe.Text(() => page.Name),
                ["identifying_name"] = Safe.Text(() => page.IdentifyingName),
                ["page_type"] = Safe.Text(() => page.PageType.ToString()),
                ["page_type_name"] = Safe.Text(() => page.PageTypeName),
            };

            Placement[] all = Array.Empty<Placement>();
            if (placements || texts)
            {
                try { all = page.AllPlacements ?? Array.Empty<Placement>(); }
                catch (Exception ex) { result["placements_err"] = Safe.Error(ex); }
            }
            if (placements)
            {
                result["placement_total"] = all.Length;
                result["placements"] = all.Take(max).Select(p => (object)Placement(p)).ToList();
            }
            if (texts)
            {
                var list = all.OfType<TextBase>().ToList();
                result["text_total"] = list.Count;
                result["texts"] = list.Take(max).Select(t => (object)Text(t)).ToList();
            }
            if (functions)
            {
                var list = new List<object>();
                int total = 0;
                try
                {
                    foreach (var f in page.Functions ?? Array.Empty<Function>())
                    {
                        total++;
                        if (list.Count < max) list.Add(Function(f));
                    }
                }
                catch (Exception ex) { result["functions_err"] = Safe.Error(ex); }
                result["function_total"] = total;
                result["functions"] = list;
            }
            return result;
        }

        private static void AddLocation(Dictionary<string, object?> item, List<string> errors, Func<PointD> read)
        {
            try { var loc = read(); item["x"] = loc.X; item["y"] = loc.Y; }
            catch (Exception ex) { item["x"] = null; item["y"] = null; errors.Add("location: " + Safe.Error(ex)); }
        }
    }
}
