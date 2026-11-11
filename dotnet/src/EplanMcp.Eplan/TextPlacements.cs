using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.Graphics;
using EplanMcp.Scripting;

namespace EplanMcp.Eplan
{
    /// <summary>
    /// The texts on a page (free texts and the property texts of symbol references) with their
    /// size and alignment-box settings, and checked writes to one of them.
    /// <para>A text is addressed by a handle that <see cref="List"/> returns: a free text by its own
    /// identifier (<c>ToStringIdentifier()</c>, the handle the live tools use), a property text by
    /// <c>"&lt;owner handle&gt;#&lt;position&gt;:&lt;property id&gt;"</c>. A property text of a symbol
    /// that shows its variant's placements is the same object on every instance, so it has no
    /// identity of its own; the owner part makes it unique, and the property id makes a handle
    /// that no longer fits (the owner's texts changed) fail instead of hitting another text.</para>
    /// <para>Every write is judged by reading the value back, never by the absence of an
    /// exception.</para>
    /// </summary>
    public static class TextPlacements
    {
        /// <summary>EPLAN's "take the value from the layer" sentinel (height, rotation, colour...).</summary>
        public const double FromLayer = -16002.0;

        /// <summary>The font size property; it can differ from <see cref="TextBase.Height"/>.</summary>
        public const int FontSizeProperty = 19017;

        /// <summary>The handle of any storable object, as the live tools report it; null when unreadable.</summary>
        public static string? Id(StorableObject o) => Safe.Text(() => o.ToStringIdentifier());

        /// <summary>The handle of the property text at <paramref name="position"/> of <paramref name="owner"/>.</summary>
        public static string? PropertyHandle(SymbolReference owner, int position, PropertyPlacement pp)
        {
            var ownerId = Id(owner);
            var prop = Safe.Maybe(() => pp.DisplayedProperty.AsInt);
            return ownerId == null || prop == null ? null : $"{ownerId}#{position}:{prop}";
        }

        /// <summary>Every symbol reference on the page (optionally only those whose symbol name
        /// starts with <paramref name="symbolPrefix"/>) with its property texts, and when
        /// <paramref name="includeFreeTexts"/> the free texts.</summary>
        public static Dictionary<string, object?> List(ScriptContext ctx, Page page, string? symbolPrefix, bool includeFreeTexts)
        {
            var data = new Dictionary<string, object?> { ["page"] = Safe.Text(() => page.Name) };
            var placements = Pages.Placements(page);
            var symbols = new List<object>();
            int textCount = 0;
            foreach (var sr in placements.OfType<SymbolReference>())
            {
                ctx.Budget.Check();
                var name = Safe.Text(() => sr.SymbolVariant?.SymbolName) ?? "";
                if (!string.IsNullOrEmpty(symbolPrefix) && !name.StartsWith(symbolPrefix, StringComparison.OrdinalIgnoreCase)) continue;
                var item = DescribeSymbolReference(sr);
                textCount += (int)item["text_count"]!;
                symbols.Add(item);
            }
            data["symbols"] = symbols;
            data["symbol_count"] = symbols.Count;
            if (includeFreeTexts)
            {
                var texts = new List<object>();
                foreach (var t in placements.OfType<Text>())
                {
                    var item = DescribeText(t);
                    item["handle"] = Id(t);
                    item["kind"] = "free_text";
                    item["display_string"] = Safe.Text(() => t.GetDisplayString());
                    AddBox(item, "bounds", () => t.GetBoundingBox());
                    texts.Add(item);
                }
                data["free_texts"] = texts;
                textCount += texts.Count;
            }
            data["text_count"] = textCount;
            return data;
        }

        /// <summary>
        /// One symbol reference and its property texts. shared_placements = true means the instance
        /// shows its VARIANT's property placements, so a write may reach every other instance of
        /// that variant.
        /// </summary>
        public static Dictionary<string, object?> DescribeSymbolReference(SymbolReference sr)
        {
            bool? local = Safe.Maybe(() => sr.UseLocalPropertyPlacements);
            var item = new Dictionary<string, object?>
            {
                ["handle"] = Id(sr),
                ["symbol"] = Safe.Text(() => sr.SymbolVariant?.SymbolName),
                ["variant"] = Safe.Maybe(() => sr.SymbolVariant?.VariantNr ?? -1),
                ["device_tag"] = sr is Function f ? Functions.DeviceTag(f) : null,
                ["shared_placements"] = local.HasValue ? !local.Value : (bool?)null,
            };
            var texts = new List<object>();
            try
            {
                int position = 0;
                foreach (var pp in sr.PropertyPlacements ?? Array.Empty<PropertyPlacement>())
                {
                    var d = DescribeText(pp);
                    d["handle"] = PropertyHandle(sr, position++, pp);
                    d["kind"] = "property_text";
                    d["property_id"] = Safe.Maybe(() => pp.DisplayedProperty.AsInt);
                    d["property_index"] = Safe.Maybe(() => (int)pp.DisplayedProperty.Index);
                    d["display_string"] = Safe.Text(() => pp.GetDisplayString());
                    // The PropertyPlacement overload with true returns coordinates relative to the
                    // placement; false returns page coordinates.
                    AddBox(d, "bounds", () => pp.GetBoundingBox(false));
                    texts.Add(d);
                }
            }
            catch (Exception ex) { item["texts_error"] = Safe.Error(ex); }
            item["texts"] = texts;
            item["text_count"] = texts.Count;
            return item;
        }

        /// <summary>Height and font size, alignment-box flags and size, location, spacing and
        /// rotation of one text, plus box_fit_ready: whether EPLAN can shrink the text into its box
        /// (box on, fixed width, fixed height, fitting permitted).</summary>
        public static Dictionary<string, object?> DescribeText(TextBase t)
        {
            var d = new Dictionary<string, object?>
            {
                ["type"] = Safe.Text(() => t.GetType().Name),
                ["height"] = Safe.Maybe(() => t.Height),
                ["height_from_layer"] = Safe.Maybe(() => Math.Abs(t.Height - FromLayer) < 0.0001),
                ["font_size"] = PropertyReader.Read(t, FontSizeProperty),
                ["has_box"] = Safe.Maybe(() => t.HasBox),
                ["draw_box"] = Safe.Text(() => t.DrawAlignmentBox.ToString()),
                ["box_fixed_width"] = Safe.Maybe(() => t.AlignmentBoxFixedWidth),
                ["box_fixed_height"] = Safe.Maybe(() => t.AlignmentBoxFixedHeight),
                ["box_width"] = Safe.Maybe(() => t.AlignmentBoxWidth),
                ["box_height"] = Safe.Maybe(() => t.AlignmentBoxHeight),
                ["fitting_permitted"] = Safe.Maybe(() => t.AlignmentBoxTextFittingPermitted),
                ["never_hyphenate"] = Safe.Maybe(() => t.AlignmentBoxNeverHyphenateWords),
                ["remove_breaks"] = Safe.Maybe(() => t.AlignmentBoxRemoveBreaks),
                ["x"] = Safe.Maybe(() => t.Location.X),
                ["y"] = Safe.Maybe(() => t.Location.Y),
                ["row_spacing"] = Safe.Maybe(() => t.RowSpacing),
                ["paragraph_spacing"] = Safe.Maybe(() => t.ParagraphSpacing),
                ["rotation"] = Safe.Maybe(() => t.Rotation),
            };
            d["box_fit_ready"] = (d["has_box"] as bool?) == true && (d["box_fixed_width"] as bool?) == true
                                 && (d["box_fixed_height"] as bool?) == true && (d["fitting_permitted"] as bool?) == true;
            return d;
        }

        /// <summary>
        /// The text a handle from <see cref="List"/> names, searched on <paramref name="page"/> only
        /// (a handle from another page never resolves). <paramref name="owner"/> is the symbol
        /// reference of a property text, null for a free text. Null with the reason when the handle
        /// does not resolve.
        /// </summary>
        public static TextBase? Resolve(Page page, string? handle, out SymbolReference? owner, out string? error)
        {
            owner = null;
            error = null;
            if (string.IsNullOrWhiteSpace(handle)) { error = "handle is required (from text_placements)."; return null; }
            string pageName = Safe.Text(() => page.Name) ?? "?";
            string again = " The object no longer exists, or the symbol's texts changed; re-read the page with text_placements.";
            var placements = Pages.Placements(page);
            int hash = handle!.LastIndexOf('#');
            if (hash < 0)
            {
                var text = placements.OfType<Text>().FirstOrDefault(t => Id(t) == handle);
                if (text == null) error = $"no free text with handle '{handle}' on page '{pageName}'." + again;
                return text;
            }

            string ownerId = handle.Substring(0, hash);
            var rest = handle.Substring(hash + 1).Split(':');
            if (rest.Length != 2 || !int.TryParse(rest[0], out int position) || !int.TryParse(rest[1], out int property))
            {
                error = $"malformed property text handle '{handle}' (expected '<owner>#<position>:<property id>').";
                return null;
            }
            owner = placements.OfType<SymbolReference>().FirstOrDefault(s => Id(s) == ownerId);
            if (owner == null) { error = $"no symbol reference with handle '{ownerId}' on page '{pageName}'." + again; return null; }
            PropertyPlacement[] pps;
            try { pps = owner.PropertyPlacements ?? Array.Empty<PropertyPlacement>(); }
            catch (Exception ex) { error = "reading the property texts failed: " + Safe.Error(ex); return null; }
            if (position < 0 || position >= pps.Length) { error = $"the symbol has {pps.Length} property text(s), none at position {position}." + again; return null; }
            var pp = pps[position];
            var shown = Safe.Maybe(() => pp.DisplayedProperty.AsInt);
            if (shown != property) { error = $"the text at position {position} now shows property {shown}, not {property}." + again; return null; }
            return pp;
        }

        /// <summary>Null when the text may be written; otherwise why not. A property text of a
        /// symbol that shows its variant's placements is shared by every instance of the variant.</summary>
        public static string? SharedRefusal(SymbolReference? owner, bool allowShared)
        {
            if (owner == null || allowShared) return null;
            bool local = Safe.Maybe(() => owner.UseLocalPropertyPlacements) ?? false;
            return local ? null :
                "refusing to write: this symbol shows its VARIANT's property placements, so the write would change " +
                "every instance of the variant in the project. Pass allow_shared=true only if that is intended.";
        }

        /// <summary>
        /// Null unless the text is a property text shown from its symbol VARIANT (not local): EPLAN
        /// keeps that placement in the variant and refuses both the TextBase.Height setter and the
        /// font size property ("The database is write-protected", measured on EPLAN 2027). The API
        /// offers no way to set a variant placement's height, only to make one instance local
        /// (SymbolReference.SwitchLocalPropertyPlacements), which is a different change.
        /// </summary>
        public static string? SharedHeightRefusal(SymbolReference? owner)
        {
            if (owner == null) return null;
            bool local = Safe.Maybe(() => owner.UseLocalPropertyPlacements) ?? false;   // unreadable counts as shared
            return local ? null :
                "EPLAN does not allow changing the height or font size of a property text that the symbol shows from its variant " +
                "(shared_placements=true): the variant's placements are write-protected, so nothing was written. Use " +
                "text_set_box (its box settings reach the variant), or make this symbol's property placements local in " +
                "EPLAN first (only this instance changes), then set the height.";
        }

        /// <summary>
        /// Writes a height to the text (<paramref name="target"/> "height": TextBase.Height;
        /// "font_size": the font size property), either <paramref name="height"/> or the current
        /// height times <paramref name="factor"/>, and reads both back. A dry run returns the plan.
        /// </summary>
        public static Dictionary<string, object?> SetHeight(ScriptContext ctx, TextBase text, SymbolReference? owner,
            double? height, double? factor, string target, bool allowShared)
        {
            var data = new Dictionary<string, object?> { ["dry_run"] = ctx.DryRun, ["target"] = target, ["written"] = false };
            if (height.HasValue == factor.HasValue) return Fail(data, "pass exactly one of height (mm) or factor.");
            if (factor.HasValue && !(factor.Value > 0)) return Fail(data, "factor must be greater than 0.");
            if (height.HasValue && !(height.Value > 0) && Math.Abs(height.Value - FromLayer) > 0.0001)
                return Fail(data, $"height must be greater than 0 mm, or {FromLayer} for 'from layer'.");
            if (target != "height" && target != "font_size") return Fail(data, "target must be 'height' or 'font_size'.");
            var refusal = SharedHeightRefusal(owner) ?? SharedRefusal(owner, allowShared);   // a variant text is refused whatever allow_shared says
            if (refusal != null) return Fail(data, refusal);

            double? before = Safe.Maybe(() => text.Height);
            data["height_before"] = before;
            data["font_size_before"] = PropertyReader.Read(text, FontSizeProperty);
            double wanted;
            if (height.HasValue) wanted = height.Value;
            else if (!before.HasValue) return Fail(data, "the current height is unreadable; pass an explicit height.");
            else if (Math.Abs(before.Value - FromLayer) < 0.0001) return Fail(data, "the height comes from the layer; a factor cannot scale it. Pass an explicit height.");
            else wanted = before.Value * factor!.Value;
            data["height_wanted"] = wanted;
            if (ctx.DryRun) return data;

            ctx.Lock(text);
            try
            {
                if (target == "font_size") text.Properties[(AnyPropertyId)FontSizeProperty] = wanted;
                else text.Height = wanted;
            }
            catch (Exception ex) { return Fail(data, $"EPLAN refused the {target} write: {Safe.Error(ex)}"); }
            data["written"] = true;

            double? after = Safe.Maybe(() => text.Height);
            data["height_after"] = after;
            data["font_size_after"] = PropertyReader.Read(text, FontSizeProperty);
            bool sticks = target == "font_size"
                ? double.TryParse(Convert.ToString(data["font_size_after"], System.Globalization.CultureInfo.InvariantCulture),
                      System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var fs) && Math.Abs(fs - wanted) < 0.0001
                : after.HasValue && Math.Abs(after.Value - wanted) < 0.0001;
            data["sticks"] = sticks;
            data["not_stuck"] = sticks ? new List<string>() : new List<string> { target };
            return data;
        }

        /// <summary>
        /// Writes the alignment-box settings present in <paramref name="args"/> (has_box,
        /// box_fixed_width, box_fixed_height, fitting_permitted, never_hyphenate, remove_breaks,
        /// box_width, box_height), each read back on its own:
        /// {changes: [{field, before, requested, after, sticks, error?}], not_stuck: [fields]}. A dry
        /// run lists before and requested only.
        /// </summary>
        public static Dictionary<string, object?> SetBox(ScriptContext ctx, TextBase t, SymbolReference? owner, ScriptArgs args, bool allowShared)
        {
            var changes = new List<Dictionary<string, object?>>();
            var data = new Dictionary<string, object?> { ["dry_run"] = ctx.DryRun, ["changes"] = changes };
            var refusal = SharedRefusal(owner, allowShared);
            if (refusal != null) return Fail(data, refusal);
            foreach (var key in new[] { "box_width", "box_height" })
                if (args.Has(key) && !(args.Number(key) > 0)) return Fail(data, key + " must be greater than 0 mm.");

            bool write = !ctx.DryRun;
            if (write) ctx.Lock(t);
            Apply(args, "has_box", changes, write, v => t.HasBox = v, () => t.HasBox);
            Apply(args, "box_fixed_width", changes, write, v => t.AlignmentBoxFixedWidth = v, () => t.AlignmentBoxFixedWidth);
            Apply(args, "box_fixed_height", changes, write, v => t.AlignmentBoxFixedHeight = v, () => t.AlignmentBoxFixedHeight);
            Apply(args, "fitting_permitted", changes, write, v => t.AlignmentBoxTextFittingPermitted = v, () => t.AlignmentBoxTextFittingPermitted);
            Apply(args, "never_hyphenate", changes, write, v => t.AlignmentBoxNeverHyphenateWords = v, () => t.AlignmentBoxNeverHyphenateWords);
            Apply(args, "remove_breaks", changes, write, v => t.AlignmentBoxRemoveBreaks = v, () => t.AlignmentBoxRemoveBreaks);
            Apply(args, "box_width", changes, write, v => t.AlignmentBoxWidth = v, () => t.AlignmentBoxWidth);
            Apply(args, "box_height", changes, write, v => t.AlignmentBoxHeight = v, () => t.AlignmentBoxHeight);
            if (changes.Count == 0) return Fail(data, "nothing to set: pass at least one of has_box, box_fixed_width, box_fixed_height, fitting_permitted, never_hyphenate, remove_breaks, box_width, box_height.");
            if (write)
                data["not_stuck"] = changes.Where(c => c["sticks"] as bool? != true).Select(c => c["field"]).ToList();
            return data;
        }

        private static Dictionary<string, object?> Fail(Dictionary<string, object?> data, string error)
        {
            data["error"] = error;
            return data;
        }

        private static void Apply(ScriptArgs args, string key, List<Dictionary<string, object?>> changes, bool write, Action<bool> set, Func<bool> read)
        {
            if (!args.Has(key)) return;
            bool requested = args.Bool(key);
            Record(changes, key, requested, write, Safe.Maybe(read), () => set(requested), () => { bool? a = Safe.Maybe(read); return (a, a == requested); });
        }

        private static void Apply(ScriptArgs args, string key, List<Dictionary<string, object?>> changes, bool write, Action<double> set, Func<double> read)
        {
            if (!args.Has(key)) return;
            double requested = args.Number(key);
            Record(changes, key, requested, write, Safe.Maybe(read), () => set(requested),
                () => { double? a = Safe.Maybe(read); return (a, a.HasValue && Math.Abs(a.Value - requested) < 0.0001); });
        }

        private static void Record(List<Dictionary<string, object?>> changes, string key, object requested, bool write, object? before,
            Action set, Func<(object? after, bool sticks)> readBack)
        {
            var row = new Dictionary<string, object?> { ["field"] = key, ["before"] = before, ["requested"] = requested };
            if (write)
            {
                try
                {
                    set();
                    var (after, sticks) = readBack();
                    row["after"] = after;
                    row["sticks"] = sticks;
                }
                catch (Exception ex) { row["error"] = Safe.Error(ex); row["sticks"] = false; }
            }
            changes.Add(row);
        }

        private static void AddBox(Dictionary<string, object?> d, string key, Func<PointD[]> read)
        {
            try
            {
                var box = read();
                if (box == null || box.Length < 2) { d[key] = null; return; }
                if (box[0].X == 0 && box[0].Y == 0 && box[1].X == 0 && box[1].Y == 0)
                {
                    // Not a real box at the page origin: EPLAN gives no extent for this text.
                    d[key] = null;
                    d[key + "_reason"] = "EPLAN reports no extent (0,0,0,0): the text shows an empty value, or EPLAN computes no bounds for it (seen on some symbol types)";
                    return;
                }
                d[key] = new Dictionary<string, object?>
                {
                    ["x1"] = box[0].X, ["y1"] = box[0].Y, ["x2"] = box[1].X, ["y2"] = box[1].Y,
                    ["w"] = box[1].X - box[0].X, ["h"] = box[1].Y - box[0].Y,
                };
            }
            catch (Exception ex) { d[key] = null; d[key + "_error"] = Safe.Error(ex); }
        }
    }
}
