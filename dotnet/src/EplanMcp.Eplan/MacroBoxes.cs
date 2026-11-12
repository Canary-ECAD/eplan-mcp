using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.Graphics;
using EplanMcp.Scripting;
using RepresentationType = Eplan.EplApi.DataModel.MasterData.WindowMacro.Enums.RepresentationType;

namespace EplanMcp.Eplan
{
    /// <summary>
    /// Survey and restore of macro boxes, and how EPLAN ties placements to them.
    /// <para>A <see cref="MacroBox"/> is its own placement type: a check that counts functions,
    /// texts and property placements does not see it. Its <c>Location</c> getter throws; the
    /// geometry is <see cref="MacroBox.InsertionPoint"/> and the logical area, with the bounding box
    /// as a fallback for boxes whose logical area is degenerate.</para>
    /// </summary>
    public static class MacroBoxes
    {
        /// <summary>The macro file name, read through the property system.</summary>
        public const int MacroFileNameProperty = 23001;

        /// <summary>Every macro box on the page.</summary>
        public static List<MacroBox> OnPage(Page page) => Pages.Placements(page).OfType<MacroBox>().ToList();

        /// <summary>
        /// One box as a restorable row: identity (page, macro, variant), flags, geometry (insertion
        /// point, logical area, bounding box), appearance (layer, pen) and its property texts.
        /// </summary>
        public static Dictionary<string, object?> Describe(MacroBox box, string? pageName)
        {
            var row = new Dictionary<string, object?>
            {
                ["page"] = pageName,
                ["macro"] = Safe.Text(() => box.MacroName) ?? "",
                ["variant"] = Safe.Get(() => box.Variant, 0),
                ["macro_property"] = Safe.Text(() => box.Properties[(AnyPropertyId)MacroFileNameProperty].ToString()) ?? "",
                ["representation_type"] = Safe.Text(() => box.RepresentationType.ToString()),
                ["type_of_usage"] = Safe.Text(() => box.TypeOfUsage.ToString()),
                ["insert_macro_box"] = Safe.Text(() => box.InsertMacroBox.ToString()),
                ["take_cp_designations"] = Safe.Text(() => box.TakeConnectionPointDesignationsIntoAccount.ToString()),
                ["references_active"] = Safe.Get(() => box.ReferencesActive, false),
                ["insertion_point_active"] = Safe.Get(() => box.InsertionPointActive, false),
                ["generate_protected_group"] = Safe.Get(() => box.GenerateProtectedGroup, false),
                ["surface_filled"] = Safe.Get(() => box.IsSurfaceFilled, false),
                // Visible / Invisible / ByLayer: an enum, not a bool.
                ["visibility"] = Safe.Text(() => box.IsSetAsVisible.ToString()),
            };

            double ipx = 0, ipy = 0;
            Safe.Try(() => { var ip = box.InsertionPoint; ipx = ip.X; ipy = ip.Y; });
            row["ip_x"] = ipx; row["ip_y"] = ipy;

            LogicalArea(box, out var x1, out var y1, out var x2, out var y2);
            row["x1"] = x1; row["y1"] = y1; row["x2"] = x2; row["y2"] = y2;

            // GetBoundingBox returns corner points, not a rectangle: take the extremes.
            double bx1 = 0, by1 = 0, bx2 = 0, by2 = 0;
            Safe.Try(() =>
            {
                var pts = box.GetBoundingBox();
                if (pts == null || pts.Length == 0) return;
                bx1 = pts.Min(q => q.X); by1 = pts.Min(q => q.Y);
                bx2 = pts.Max(q => q.X); by2 = pts.Max(q => q.Y);
            });
            row["bb_x1"] = bx1; row["bb_y1"] = by1; row["bb_x2"] = bx2; row["bb_y2"] = by2;
            row["drawing_order"] = Safe.Get(() => (int)box.DrawingOrder, 0);

            // Appearance: a box created with Create(Page) gets the default layer and pen.
            Safe.Try(() =>
            {
                if (!(box.GetGraphics() is GraphicalPlacement g)) return;
                row["layer_id"] = Safe.Get(() => (int)g.LayerId, 0);
                row["layer_name"] = Safe.Text(() => g.Layer.Name) ?? "";
                row["gfx_visible"] = Safe.Get(() => g.IsVisible, false);
                var pen = g.Pen;
                row["pen_color"] = (int)pen.ColorId;
                row["pen_style"] = (int)pen.StyleId;
                row["pen_width"] = pen.Width;
                row["pen_style_factor"] = pen.StyleFactor;
                row["pen_line_end"] = (int)pen.LineEndType;
            });

            var texts = new List<object>();
            Safe.Try(() =>
            {
                foreach (var pp in box.PropertyPlacements ?? Array.Empty<PropertyPlacement>()) texts.Add(DescribeText(pp));
            });
            row["texts"] = texts;
            return row;
        }

        /// <summary>Every macro box in the project as <see cref="Describe"/> rows, plus the boxes
        /// that could not be read: {rows, problems, pages}.</summary>
        public static (List<Dictionary<string, object?>> rows, List<object> problems, int pages) Survey(ScriptContext ctx, Project project)
        {
            var rows = new List<Dictionary<string, object?>>();
            var problems = new List<object>();
            var pages = Pages.All(project);
            foreach (var page in pages)
            {
                ctx.Budget.Check();
                string? pageName = Safe.Text(() => page.Name);
                string? pageId = Safe.Text(() => page.IdentifyingName);
                List<MacroBox> boxes;
                try { boxes = OnPage(page); }
                catch (Exception) { continue; }
                foreach (var box in boxes)
                {
                    try
                    {
                        var row = Describe(box, pageName);
                        row["page_identifying_name"] = pageId;   // Restore keys pages by both names
                        rows.Add(row);
                    }
                    catch (Exception ex) { problems.Add(new Dictionary<string, object?> { ["page"] = pageName, ["error"] = Safe.Error(ex) }); }
                }
            }
            return (rows, problems, pages.Length);
        }

        /// <summary>
        /// Re-creates the boxes the project is missing from survey rows. A box is identified by
        /// (page, macro, variant, rectangle rounded to 0.01 mm): one page can hold several boxes of
        /// the same macro and variant. An existing box is re-styled (flags, drawing order,
        /// appearance) when <paramref name="updateExisting"/>, never duplicated. With
        /// <paramref name="dryRun"/> nothing is written; "would_create" and "would_restyle" count what
        /// a real run changes. "rows" holds one outcome per survey row (page, macro, variant, action,
        /// error).
        /// </summary>
        public static Dictionary<string, object?> Restore(ScriptContext ctx, Project project,
            List<Dictionary<string, object?>> wanted, bool updateExisting, bool dryRun)
        {
            // Pages by full Name and by IdentifyingName; a name two pages share is ambiguous.
            var pages = Pages.All(project);
            var pageIndex = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
            var boxByKey = new Dictionary<string, MacroBox>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < pages.Length; i++)
            {
                ctx.Budget.Check();
                var page = pages[i];
                foreach (var n in new[] { Safe.Text(() => page.Name), Safe.Text(() => page.IdentifyingName) }
                             .Where(n => !string.IsNullOrEmpty(n)).Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    if (!pageIndex.TryGetValue(n!, out var list)) pageIndex[n!] = list = new List<int>();
                    list.Add(i);
                }
                int pageNo = i;
                Safe.Try(() =>
                {
                    foreach (var box in OnPage(page))
                    {
                        LogicalArea(box, out var x1, out var y1, out var x2, out var y2);
                        boxByKey[Key(pageNo, Safe.Text(() => box.MacroName) ?? "", Safe.Get(() => box.Variant, 0), x1, y1, x2, y2)] = box;
                    }
                });
            }
            var present = new HashSet<string>(boxByKey.Keys, StringComparer.OrdinalIgnoreCase);
            int before = present.Count;

            int created = 0, alreadyThere = 0, noPage = 0, ambiguous = 0, failed = 0, restyled = 0, partial = 0;
            var problems = new List<object>();
            var plan = new List<object>();
            var outcomes = new List<Dictionary<string, object?>>();
            int wouldRestyle = 0;

            foreach (var row in wanted)
            {
                ctx.Budget.Check();
                string pageName = PlainJson.Str(row, "page"), macro = PlainJson.Str(row, "macro");
                int variant = (int)PlainJson.Num(row, "variant");
                Area(row, out double ax1, out double ay1, out double ax2, out double ay2);
                var outcome = new Dictionary<string, object?> { ["page"] = pageName, ["macro"] = macro, ["variant"] = variant };
                outcomes.Add(outcome);

                int pageNo = FindPage(pageIndex, pageName, PlainJson.Str(row, "page_identifying_name"), out var pageError);
                if (pageNo < 0)
                {
                    if (pageError == null) noPage++; else ambiguous++;
                    outcome["action"] = pageError == null ? "page_not_found" : "page_ambiguous";
                    problems.Add(Problem(macro, pageName, pageError ?? "the project has no page with this name"));
                    continue;
                }
                var target = pages[pageNo];
                string key = Key(pageNo, macro, variant, ax1, ay1, ax2, ay2);

                if (present.Contains(key))
                {
                    alreadyThere++;
                    outcome["action"] = "present";
                    if (!updateExisting || !boxByKey.TryGetValue(key, out var existing)) continue;
                    if (dryRun) { wouldRestyle++; outcome["action"] = "would_restyle"; continue; }
                    var errors = new List<string>();
                    try
                    {
                        ctx.Lock(existing);
                        SetEnums(existing, row, errors);
                        Try(errors, "drawing_order", () => existing.DrawingOrder = (short)PlainJson.Num(row, "drawing_order"));
                        ApplyAppearance(existing, row, errors);
                        outcome["action"] = errors.Count == 0 ? "restyled" : "partly_restyled";
                        if (errors.Count == 0) restyled++;
                        else { partial++; outcome["error"] = string.Join(" | ", errors); problems.Add(Problem(macro, pageName, "restyled, but these settings failed: " + string.Join(" | ", errors))); }
                    }
                    catch (Exception ex)
                    {
                        failed++;
                        outcome["action"] = "failed";
                        outcome["error"] = "restyling: " + Safe.Error(ex);
                        problems.Add(Problem(macro, pageName, "restyling: " + Safe.Error(ex)));
                    }
                    continue;
                }

                plan.Add(new Dictionary<string, object?> { ["page"] = pageName, ["macro"] = macro, ["variant"] = variant, ["x1"] = ax1, ["y1"] = ay1, ["x2"] = ax2, ["y2"] = ay2 });
                // Reserve the key in a dry run too, so would_create equals what a real run creates.
                if (dryRun) { present.Add(key); outcome["action"] = "would_create"; continue; }

                var fieldErrors = new List<string>();
                try
                {
                    // Create(page) writes to the page: it must be locked first.
                    ctx.Lock(target);
                    target.LockObject();
                    var box = new MacroBox();
                    box.Create(target);
                    // From here the box exists: reserve its key even if a setting below fails, so a
                    // second row with the same key never creates it twice.
                    present.Add(key);
                    box.MacroName = macro;
                    box.Variant = variant;
                    box.SetLogicalArea(new PointD(ax1, ay1), new PointD(ax2, ay2));
                    Try(fieldErrors, "insertion_point", () => box.InsertionPoint = new PointD(PlainJson.Num(row, "ip_x"), PlainJson.Num(row, "ip_y")));
                    Try(fieldErrors, "insertion_point_active", () => box.InsertionPointActive = PlainJson.Flag(row, "insertion_point_active"));
                    Try(fieldErrors, "references_active", () => box.ReferencesActive = PlainJson.Flag(row, "references_active"));
                    Try(fieldErrors, "generate_protected_group", () => box.GenerateProtectedGroup = PlainJson.Flag(row, "generate_protected_group"));
                    Try(fieldErrors, "surface_filled", () => box.IsSurfaceFilled = PlainJson.Flag(row, "surface_filled"));
                    Try(fieldErrors, "visibility", () =>
                    {
                        var v = PlainJson.Str(row, "visibility");
                        if (v.Length > 0) box.IsSetAsVisible = (Placement.Visibility)Enum.Parse(typeof(Placement.Visibility), v, true);
                    });
                    SetEnums(box, row, fieldErrors);
                    Try(fieldErrors, "drawing_order", () => box.DrawingOrder = (short)PlainJson.Num(row, "drawing_order"));
                    ApplyAppearance(box, row, fieldErrors);
                    // Read back the identity: a box that does not carry its macro is not restored.
                    if (!string.Equals(Safe.Text(() => box.MacroName) ?? "", macro, StringComparison.OrdinalIgnoreCase))
                        fieldErrors.Add("macro: read back '" + Safe.Text(() => box.MacroName) + "'");
                    if (Safe.Get(() => box.Variant, -1) != variant) fieldErrors.Add("variant: read back " + Safe.Get(() => box.Variant, -1));
                    outcome["action"] = fieldErrors.Count == 0 ? "created" : "partly_created";
                    if (fieldErrors.Count > 0) outcome["error"] = string.Join(" | ", fieldErrors);
                    if (fieldErrors.Count == 0) created++;
                    else { partial++; problems.Add(Problem(macro, pageName, "created, but these settings failed: " + string.Join(" | ", fieldErrors))); }
                }
                catch (Exception ex)
                {
                    failed++;
                    outcome["action"] = "failed";
                    outcome["error"] = Safe.Error(ex);
                    problems.Add(Problem(macro, pageName, Safe.Error(ex)));
                }
            }

            return new Dictionary<string, object?>
            {
                ["dry_run"] = dryRun,
                ["rows_given"] = wanted.Count,
                ["macro_boxes_before"] = before,
                ["already_present"] = alreadyThere,
                ["restyled"] = restyled,
                ["update_existing"] = updateExisting,
                ["would_create"] = plan.Count,
                ["would_restyle"] = wouldRestyle,
                ["created"] = created,
                ["partly_applied"] = partial,
                ["page_not_found"] = noPage,
                ["page_ambiguous"] = ambiguous,
                ["failed"] = failed,
                ["problems"] = problems.Take(40).ToList(),
                ["plan"] = plan.Take(60).ToList(),
                ["ok"] = failed == 0 && noPage == 0 && ambiguous == 0 && partial == 0,
                ["rows"] = outcomes,
            };
        }

        /// <summary>The index of the one page a row names: by its "page" (full Name or
        /// IdentifyingName) and, when the row has it, "page_identifying_name". -1 with
        /// <paramref name="error"/> null when no page matches, or set when several do.</summary>
        private static int FindPage(Dictionary<string, List<int>> index, string name, string identifyingName, out string? error)
        {
            error = null;
            IEnumerable<int>? hits = null;
            foreach (var n in new[] { name, identifyingName }.Where(n => n.Length > 0))
            {
                var these = index.TryGetValue(n, out var list) ? list : new List<int>();
                hits = hits == null ? these : hits.Intersect(these);
            }
            var found = (hits ?? Enumerable.Empty<int>()).Distinct().ToList();
            if (found.Count == 1) return found[0];
            if (found.Count > 1)
                error = $"{found.Count} pages are named '{name}'; the row is ambiguous (survey again to record page_identifying_name)";
            return -1;
        }

        private static Dictionary<string, object?> Problem(string macro, string page, string error) =>
            new Dictionary<string, object?> { ["macro"] = macro, ["page"] = page, ["error"] = error };

        /// <summary>Runs one setting; a failure is recorded as "name: error", never thrown.</summary>
        private static void Try(List<string> errors, string name, Action set)
        {
            try { set(); }
            catch (Exception ex) { errors.Add(name + ": " + Safe.Error(ex)); }
        }

        /// <summary>
        /// How EPLAN links placements to the boxes on the given pages: per box its ReferencesActive
        /// flag, how many placements it references, which referenced objects are other boxes, its
        /// group chain, the boxes that reference it, and the boxes sharing objects with it.
        /// </summary>
        public static List<object> Links(ScriptContext ctx, Project project, ICollection<string> pageNames)
        {
            var rows = new List<object>();
            foreach (var page in Pages.All(project).Where(p => Pages.InScope(p, null, pageNames)))
            {
                ctx.Budget.Check();
                var boxes = OnPage(page);
                var refs = new Dictionary<string, List<string>>();
                foreach (var b in boxes)
                    refs[Safe.Text(() => b.ToStringIdentifier()) ?? ""] = (Safe.Object(() => b.ReferencedPlacements) ?? Array.Empty<Placement>())
                        .Select(p => Safe.Text(() => p.ToStringIdentifier()) ?? "").ToList();
                foreach (var box in boxes)
                {
                    string id = Safe.Text(() => box.ToStringIdentifier()) ?? "";
                    var chain = new List<string?>();
                    for (var g = Safe.Object(() => box.Group); g != null && chain.Count < 10; g = Safe.Object(() => g.Group))
                        chain.Add(Safe.Text(() => g.ToStringIdentifier()));
                    var mine = refs[id];
                    rows.Add(new Dictionary<string, object?>
                    {
                        ["page"] = Safe.Text(() => page.Name),
                        ["box"] = id,
                        ["macro"] = Safe.Text(() => box.MacroName),
                        ["ip_x"] = Safe.Maybe(() => box.InsertionPoint.X),
                        ["ip_y"] = Safe.Maybe(() => box.InsertionPoint.Y),
                        ["refs_active"] = Safe.Get(() => box.ReferencesActive, false),
                        ["referenced"] = mine.Count,
                        ["referenced_boxes"] = mine.Where(refs.ContainsKey).ToList(),
                        ["group_chain"] = chain,
                        ["referenced_by"] = refs.Where(kv => kv.Key != id && kv.Value.Contains(id)).Select(kv => kv.Key).ToList(),
                        ["shares_objects_with"] = refs.Where(kv => kv.Key != id && mine.Count > 0 && kv.Value.Intersect(mine).Any())
                            .Select(kv => $"{kv.Key} ({kv.Value.Intersect(mine).Count()}/{mine.Count})").ToList(),
                    });
                }
            }
            return rows;
        }

        /// <summary>
        /// What "Prepare macros for automatic generation" leaves on each box of the given pages:
        /// usage, stored vs. automatic name / version / part number / part variant, the insertion
        /// point (handle) flag, references, and how the box and the placements inside its area are
        /// grouped.
        /// </summary>
        public static List<object> PrepareInspect(ScriptContext ctx, Project project, ICollection<string> pageNames)
        {
            var rows = new List<object>();
            foreach (var page in Pages.All(project).Where(p => Pages.InScope(p, null, pageNames)))
            {
                ctx.Budget.Check();
                var all = Pages.Placements(page).ToList();
                foreach (var box in all.OfType<MacroBox>())
                {
                    string P(int id) => Safe.Text(() => box.Properties[(AnyPropertyId)id].ToString()) ?? "";
                    var group = Safe.Object(() => box.Group);
                    var members = group == null ? new List<Placement>() : (Safe.Object(() => group.SubPlacements) ?? Array.Empty<Placement>()).ToList();
                    var inArea = all.Where(p => !(p is MacroBox) && !ReferenceEquals(p, box)
                                                && Safe.Get(() => box.IsPointInsideLogicalArea(LocationOf(p)), false)).ToList();
                    rows.Add(new Dictionary<string, object?>
                    {
                        ["page"] = Safe.Text(() => page.Name),
                        ["box"] = Safe.Text(() => box.ToStringIdentifier()),
                        ["usage"] = P(23011), ["name"] = P(23001), ["name_auto"] = P(23021),
                        ["version"] = P(23002), ["version_auto"] = P(23023),
                        ["part"] = P(23020), ["part_auto"] = P(23024),
                        ["part_var"] = P(23027), ["part_var_auto"] = P(23028),
                        ["handle_active"] = Safe.Get(() => box.InsertionPointActive, false),
                        ["refs_active"] = Safe.Get(() => box.ReferencesActive, false),
                        ["referenced"] = (Safe.Object(() => box.ReferencedPlacements) ?? Array.Empty<Placement>()).Length,
                        ["group"] = group == null ? null : Safe.Text(() => group.ToStringIdentifier()),
                        ["group_parent"] = group == null ? null : Safe.Text(() => group.Group?.ToStringIdentifier()),
                        ["group_members"] = members.Count,
                        ["group_member_types"] = members.GroupBy(m => m.GetType().Name).ToDictionary(g => g.Key, g => (object)g.Count()),
                        ["in_area"] = inArea.Count,
                        ["in_area_types"] = inArea.GroupBy(m => m.GetType().Name).ToDictionary(g => g.Key, g => (object)g.Count()),
                        ["in_area_in_box_group"] = group == null ? 0 : inArea.Count(p => InGroupTree(p, group)),
                        ["in_area_other_group"] = inArea.Count(p => Safe.Object(() => p.Group) != null && (group == null || !InGroupTree(p, group))),
                    });
                }
            }
            return rows;
        }

        /// <summary>True when <paramref name="p"/> sits in <paramref name="group"/> at any depth.</summary>
        public static bool InGroupTree(Placement p, Group group)
        {
            for (var g = Safe.Object(() => p.Group); g != null; g = Safe.Object(() => g.Group))
                if (g.Equals(group)) return true;
            return false;
        }

        /// <summary>A symbol reference's location, else the centre of the bounding box.</summary>
        public static PointD LocationOf(Placement p)
        {
            if (p is SymbolReference s) return s.Location;
            var bb = p.GetBoundingBox();
            return new PointD((bb[0].X + bb[1].X) / 2, (bb[0].Y + bb[1].Y) / 2);
        }

        private static void LogicalArea(MacroBox box, out double x1, out double y1, out double x2, out double y2)
        {
            x1 = y1 = x2 = y2 = 0;
            try
            {
                var area = box.GetLogicalArea();
                x1 = area.LowerLeft.X; y1 = area.LowerLeft.Y;
                x2 = area.UpperRight.X; y2 = area.UpperRight.Y;
            }
            catch (Exception) { }
        }

        private static Dictionary<string, object?> DescribeText(PropertyPlacement pp)
        {
            double x = 0, y = 0;
            Safe.Try(() => { var l = pp.Location; x = l.X; y = l.Y; });
            return new Dictionary<string, object?>
            {
                ["property"] = Safe.Get(() => pp.DisplayedProperty.AsInt, 0),
                ["index"] = Safe.Get(() => (int)pp.DisplayedProperty.Index, 0),
                ["x"] = x, ["y"] = y,
                ["height"] = Safe.Get(() => pp.Height, 0.0),
                ["rotation"] = Safe.Get(() => pp.Rotation, 0.0),
                ["justification"] = Safe.Text(() => pp.Justification.ToString()),
                ["text_color"] = Safe.Get(() => (int)pp.TextColorId, 0),
                ["visible"] = Safe.Get(() => pp.IsVisible, false),
                ["has_box"] = Safe.Get(() => pp.HasBox, false),
                ["is_docked"] = Safe.Get(() => pp.IsDocked, false),
                ["docking_direction"] = Safe.Text(() => pp.DockingDirection.ToString()),
                ["contents"] = Safe.PlainText(Safe.Text(() => pp.Contents.ToString())),
            };
        }

        /// <summary>The enum-valued settings, set by NAME so no numeric value is hard-coded. A name
        /// the enum does not have leaves the value Create gave it.</summary>
        private static void SetEnums(MacroBox box, Dictionary<string, object?> row, List<string> errors)
        {
            static T? Parse<T>(string v) where T : struct => v.Length == 0 ? null : (T)Enum.Parse(typeof(T), v, true);
            Try(errors, "representation_type", () => { var v = Parse<RepresentationType>(PlainJson.Str(row, "representation_type")); if (v.HasValue) box.RepresentationType = v.Value; });
            Try(errors, "type_of_usage", () => { var v = Parse<MacroBox.Enums.TypeOfUsage>(PlainJson.Str(row, "type_of_usage")); if (v.HasValue) box.TypeOfUsage = v.Value; });
            Try(errors, "insert_macro_box", () => { var v = Parse<MacroBox.Enums.InsertMacroBox>(PlainJson.Str(row, "insert_macro_box")); if (v.HasValue) box.InsertMacroBox = v.Value; });
            Try(errors, "take_cp_designations", () =>
            {
                var v = Parse<MacroBox.Enums.TakeConnectionPointDesignationsIntoAccount>(PlainJson.Str(row, "take_cp_designations"));
                if (v.HasValue) box.TakeConnectionPointDesignationsIntoAccount = v.Value;
            });
        }

        /// <summary>The source's layer, pen and visibility on the drawn rectangle, and the source's
        /// text formats on the box's own texts, matched by (property, index). Create(Page) already
        /// gives a default set of texts, so they are re-formatted, not doubled.</summary>
        private static void ApplyAppearance(MacroBox box, Dictionary<string, object?> row, List<string> errors)
        {
            Try(errors, "graphics", () =>
            {
                if (!(box.GetGraphics() is GraphicalPlacement g)) return;
                // LayerId is read-only; Layer is set by NAME, because a layer id need not mean the
                // same layer in another project. It must be the project's own layer object: a
                // new GraphicalLayer(name, ...) is refused with S511249 "Invalid layer cannot be
                // transferred" (measured on EPLAN 2027.0.3).
                Try(errors, "layer", () =>
                {
                    var name = PlainJson.Str(row, "layer_name");
                    if (name.Length == 0) return;
                    var layer = (box.Project?.LayerTable?.Layers ?? Array.Empty<GraphicalLayer>())
                        .FirstOrDefault(l => string.Equals(Safe.Text(() => l.Name), name, StringComparison.OrdinalIgnoreCase));
                    if (layer == null) throw new InvalidOperationException($"the project has no layer named '{name}'");
                    g.Layer = layer;
                    var after = Safe.Text(() => g.Layer.Name);
                    if (!string.Equals(after, name, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException($"read back '{after}', not '{name}'");
                });
                Try(errors, "pen", () =>
                {
                    var pen = g.Pen;
                    pen.ColorId = (short)PlainJson.Num(row, "pen_color");
                    pen.StyleId = (short)PlainJson.Num(row, "pen_style");
                    pen.Width = PlainJson.Num(row, "pen_width");
                    pen.StyleFactor = PlainJson.Num(row, "pen_style_factor");
                    pen.LineEndType = (sbyte)PlainJson.Num(row, "pen_line_end");
                    g.Pen = pen;
                });
                Try(errors, "gfx_visible", () => g.IsVisible = PlainJson.Flag(row, "gfx_visible"));
            });

            if (!row.TryGetValue("texts", out var raw) || !(raw is IEnumerable en)) return;
            var have = Safe.Object(() => box.PropertyPlacements);
            if (have == null) return;
            foreach (var spec in en.OfType<Dictionary<string, object?>>())
            {
                int id = (int)PlainJson.Num(spec, "property"), idx = (int)PlainJson.Num(spec, "index");
                var target = have.FirstOrDefault(pp => Safe.Get(() => pp.DisplayedProperty.AsInt, 0) == id
                                                      && Safe.Get(() => (int)pp.DisplayedProperty.Index, 0) == idx);
                if (target == null) continue;
                Try(errors, $"text {id}/{idx} location", () => target.Location = new PointD(PlainJson.Num(spec, "x"), PlainJson.Num(spec, "y")));
                Try(errors, $"text {id}/{idx} height", () => target.Height = PlainJson.Num(spec, "height"));
                Try(errors, $"text {id}/{idx} rotation", () => target.Rotation = PlainJson.Num(spec, "rotation"));
                Try(errors, $"text {id}/{idx} text_color", () => target.TextColorId = (short)PlainJson.Num(spec, "text_color"));
                Try(errors, $"text {id}/{idx} has_box", () => target.HasBox = PlainJson.Flag(spec, "has_box"));
                Try(errors, $"text {id}/{idx} justification", () =>
                {
                    var v = PlainJson.Str(spec, "justification");
                    if (v.Length > 0) target.Justification = (TextBase.JustificationType)Enum.Parse(typeof(TextBase.JustificationType), v, true);
                });
                Try(errors, $"text {id}/{idx} visible", () => target.IsVisible = PlainJson.Flag(spec, "visible"));
            }
        }

        /// <summary>The rectangle for a restored box: the logical area, or the bounding box when
        /// the logical area is degenerate.</summary>
        private static void Area(Dictionary<string, object?> row, out double x1, out double y1, out double x2, out double y2)
        {
            x1 = PlainJson.Num(row, "x1"); y1 = PlainJson.Num(row, "y1");
            x2 = PlainJson.Num(row, "x2"); y2 = PlainJson.Num(row, "y2");
            if (Math.Abs(x2 - x1) > 1e-6 || Math.Abs(y2 - y1) > 1e-6) return;
            x1 = PlainJson.Num(row, "bb_x1"); y1 = PlainJson.Num(row, "bb_y1");
            x2 = PlainJson.Num(row, "bb_x2"); y2 = PlainJson.Num(row, "bb_y2");
        }

        private static string Key(int page, string macro, int variant, double x1, double y1, double x2, double y2) =>
            page + "\u0001" + macro + "\u0001" + variant + "\u0001" + R(x1) + "," + R(y1) + "," + R(x2) + "," + R(y2);

        private static string R(double v) => Math.Round(v, 2).ToString("0.00", CultureInfo.InvariantCulture);
    }
}
