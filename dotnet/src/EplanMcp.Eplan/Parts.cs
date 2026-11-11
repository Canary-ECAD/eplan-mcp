using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Eplan.EplApi.DataModel;
using EplanMcp.Scripting;

namespace EplanMcp.Eplan
{
    /// <summary>
    /// Snapshot and restore of the parts (article references) on functions, for putting parts back
    /// after an operation that drops them. A function is matched first by its object identifier
    /// (when the snapshot comes from the same project), then by a key: (page, full device tag,
    /// function definition, category, symbol, variant, connection point designations 1-4), and for
    /// an older snapshot by (page, device tag, symbol, category, connection points), then loosely by
    /// (page, device tag, symbol). See <see cref="Plan"/>.
    /// </summary>
    public static class Parts
    {
        /// <summary>The snapshot schema this code writes. Schema 1 files (no id, no full device tag)
        /// are still read, through the key path.</summary>
        public const int SnapshotSchema = 2;

        /// <summary>FUNC_CONNECTIONDESIGNATION, indexed by connection point.</summary>
        public const int ConnectionDesignation = 20022;

        /// <summary>One function: {id, page, dt, full_dt, definition, symbol, variant, category,
        /// is_main, fixed, cp[4], parts[], error?}. An unplaced function has page "", symbol "" and
        /// variant -1.</summary>
        public static Dictionary<string, object?> Row(Function f)
        {
            var page = Safe.Object(() => f.Page);
            var cp = new List<string>();
            for (int i = 1; i <= 4; i++)
            {
                int index = i;
                cp.Add(Safe.Text(() => f.Properties[(AnyPropertyId)ConnectionDesignation, index].ToString()) ?? "");
            }
            var row = new Dictionary<string, object?>
            {
                ["id"] = Safe.Text(() => f.ToStringIdentifier()) ?? "",
                ["page"] = page == null ? "" : Safe.Text(() => page.Name) ?? "",
                ["dt"] = Functions.DeviceTag(f) ?? "",
                ["full_dt"] = Functions.FullDeviceTag(f) ?? "",
                ["definition"] = Safe.Text(() => f.FunctionDefinition?.Identifier) ?? "",
                ["symbol"] = Functions.SymbolName(f),
                ["variant"] = page == null ? -1 : Safe.Get(() => f.SymbolVariant?.VariantNr ?? -1, -1),
                ["category"] = Safe.Text(() => f.FunctionCategory.ToString()) ?? "",
                ["is_main"] = Safe.Get(() => f.IsMainFunction, false),
                ["fixed"] = Safe.Get(() => f.IsFixedDevice, false),
                ["cp"] = cp,
            };
            var parts = new List<Dictionary<string, object?>>();
            try { parts = Read(f); }
            catch (Exception ex) { row["error"] = Safe.Error(ex); }
            row["parts"] = parts;
            return row;
        }

        /// <summary>The function's article references: [{part, variant, count, pos, assembly}].</summary>
        public static List<Dictionary<string, object?>> Read(Function f) =>
            (f.ArticleReferences ?? Array.Empty<ArticleReference>()).Select(ar => new Dictionary<string, object?>
            {
                ["part"] = Safe.Text(() => ar.PartNr) ?? "",
                ["variant"] = Safe.Text(() => ar.VariantNr) ?? "",
                ["count"] = Safe.Get(() => ar.Count, 0),
                ["pos"] = Safe.Get(() => ar.ReferencePos, 0),
                ["assembly"] = Safe.Get(() => ar.IsAssembly, false),
            }).ToList();

        /// <summary>A <see cref="Row"/> for every function (placed or not) whose page starts with
        /// <paramref name="pagePrefix"/> (all when empty).</summary>
        public static List<Dictionary<string, object?>> Snapshot(ScriptContext ctx, Project project, string? pagePrefix)
        {
            var rows = new List<Dictionary<string, object?>>();
            foreach (var f in Functions.All(project))
            {
                ctx.Budget.Check();
                var row = Row(f);
                if (!string.IsNullOrEmpty(pagePrefix) && !((string)row["page"]!).StartsWith(pagePrefix, StringComparison.OrdinalIgnoreCase)) continue;
                rows.Add(row);
            }
            return rows;
        }

        /// <summary>One snapshot row's match: the index into the current rows (-1 when none), how it
        /// matched ("id", "key", "older_key", "loose", with "+main_of_N" when the single main among N
        /// was taken), or "ambiguous" / "none"; for a tie, the candidate indexes.</summary>
        public sealed class Match
        {
            public int Target = -1;
            public string How = "none";
            public List<int> Candidates = new List<int>();
        }

        /// <summary>
        /// Matches snapshot rows to the current functions (both as <see cref="Row"/> data); plain data
        /// only, so it is unit-tested without EPLAN. Pass 1 (only with <paramref name="useIds"/>, i.e.
        /// the snapshot is from this project): a row whose id names a current function of the same
        /// category and device tag takes it. Pass 2, for the rest: the key (schema 2 rows) or the
        /// older key then the loose key (schema 1 rows); functions claimed by id are no candidates. Several
        /// candidates with exactly one main function take the main; otherwise the row is a tie and
        /// lists them. One <see cref="Match"/> per snapshot row, in order.
        /// </summary>
        public static List<Match> Plan(IList<Dictionary<string, object?>> current, IList<Dictionary<string, object?>> snapshot, bool useIds)
        {
            var byId = new Dictionary<string, int>(StringComparer.Ordinal);
            var byKey = new Dictionary<string, List<int>>(StringComparer.Ordinal);
            var byOlder = new Dictionary<string, List<int>>(StringComparer.Ordinal);
            var byLoose = new Dictionary<string, List<int>>(StringComparer.Ordinal);
            for (int i = 0; i < current.Count; i++)
            {
                var r = current[i];
                var id = PlainJson.Str(r, "id");
                if (id.Length > 0) byId[id] = i;
                Add(byKey, Key(r), i);
                Add(byOlder, OlderKey(r), i);
                Add(byLoose, LooseKey(r), i);
            }

            var matches = snapshot.Select(_ => new Match()).ToList();
            var claimed = new HashSet<int>();
            if (useIds)
                for (int s = 0; s < snapshot.Count; s++)
                {
                    var row = snapshot[s];
                    if (!byId.TryGetValue(PlainJson.Str(row, "id"), out int i) || claimed.Contains(i)) continue;
                    var c = current[i];
                    // The same object, not a reused id: same category and device tag.
                    if (PlainJson.Str(c, "category") != PlainJson.Str(row, "category") || PlainJson.Str(c, "dt") != PlainJson.Str(row, "dt")) continue;
                    matches[s].Target = i;
                    matches[s].How = "id";
                    claimed.Add(i);
                }

            for (int s = 0; s < snapshot.Count; s++)
            {
                var m = matches[s];
                if (m.Target >= 0) continue;
                var row = snapshot[s];
                // A schema 2 row has no loose fallback: its key IS the function's identity, and a
                // looser match could put a terminal's parts on another kind of function.
                var steps = row.ContainsKey("full_dt")
                    ? new[] { (byKey, Key(row), "key") }
                    : new[] { (byOlder, OlderKey(row), "older_key"), (byLoose, LooseKey(row), "loose") };
                foreach (var (index, key, kind) in steps)
                {
                    if (!index.TryGetValue(key, out var list)) continue;
                    var open = list.Where(i => !claimed.Contains(i)).ToList();
                    if (open.Count == 0) continue;
                    if (open.Count == 1) { m.Target = open[0]; m.How = kind; break; }
                    var mains = open.Where(i => PlainJson.Flag(current[i], "is_main")).ToList();
                    if (mains.Count == 1) { m.Target = mains[0]; m.How = kind + "+main_of_" + open.Count; break; }
                    m.How = "ambiguous";
                    m.Candidates = open;
                    break;   // a tie on the stricter key is never settled by a looser one
                }
            }
            return matches;
        }

        /// <summary>
        /// Puts snapshot parts back. Only snapshot rows WITH parts are considered; a row without
        /// parts never removes anything. A row's parts were read from that very function, so they go
        /// back on the matched function itself, auxiliary functions and terminals included: EPLAN
        /// keeps article references per function (terminals and article placements carry their own,
        /// different from the device's main function). Only a row recorded as a MAIN function that
        /// now matches a non-main one goes to the device's single main function; with
        /// <paramref name="promoteMain"/>, when the device has no main at all, the matched function is
        /// made main again. A fixed device is never changed. <paramref name="useIds"/>: the snapshot
        /// is from this project, so its ids may be used. With <paramref name="dryRun"/> nothing is
        /// written and the counts say what would change. Returns the summary; the per-row outcomes
        /// (ties with their candidates) are in "rows".
        /// </summary>
        public static Dictionary<string, object?> Restore(ScriptContext ctx, Project project,
            List<Dictionary<string, object?>> snapshot, string? pagePrefix, bool promoteMain, bool dryRun, bool useIds)
        {
            string prefix = pagePrefix ?? "";
            var functions = Functions.All(project);
            var current = new List<Dictionary<string, object?>>(functions.Length);
            var mainsByDevice = new Dictionary<string, List<int>>(StringComparer.Ordinal);
            foreach (var f in functions)
            {
                ctx.Budget.Check();
                var r = Row(f);
                if (PlainJson.Flag(r, "is_main"))
                {
                    Add(mainsByDevice, "full|" + PlainJson.Str(r, "full_dt"), current.Count);
                    Add(mainsByDevice, "dt|" + PlainJson.Str(r, "dt"), current.Count);
                }
                current.Add(r);
            }

            var wanted = snapshot.Where(s =>
                AsRows(s.TryGetValue("parts", out var p) ? p : null).Count > 0
                && (prefix.Length == 0 || PlainJson.Str(s, "page").StartsWith(prefix, StringComparison.OrdinalIgnoreCase))).ToList();
            var plan = Plan(current, wanted, useIds);

            var rows = new List<Dictionary<string, object?>>();
            var used = new HashSet<int>();
            int byId = 0, byKey = 0, unmatched = 0, ambiguous = 0, unchanged = 0, changed = 0, failed = 0, redirected = 0, promoted = 0;

            for (int n = 0; n < wanted.Count; n++)
            {
                ctx.Budget.Check();
                var s = wanted[n];
                var sParts = AsRows(s["parts"]);
                var row = new Dictionary<string, object?>
                {
                    ["id"] = PlainJson.Str(s, "id"), ["page"] = PlainJson.Str(s, "page"), ["dt"] = PlainJson.Str(s, "dt"),
                    ["full_dt"] = PlainJson.Str(s, "full_dt"), ["symbol"] = PlainJson.Str(s, "symbol"),
                    ["category"] = PlainJson.Str(s, "category"), ["is_main"] = PlainJson.Flag(s, "is_main"), ["want"] = sParts,
                };
                rows.Add(row);
                var m = plan[n];
                if (m.Target < 0)
                {
                    if (m.How == "ambiguous")
                    {
                        ambiguous++;
                        row["action"] = "ambiguous";
                        // For a person to resolve: every candidate with what tells them apart.
                        row["candidate_count"] = m.Candidates.Count;
                        row["candidates"] = m.Candidates.Take(20).Select(i => new Dictionary<string, object?>
                        {
                            ["id"] = current[i]["id"], ["page"] = current[i]["page"], ["full_dt"] = current[i]["full_dt"],
                            ["definition"] = current[i]["definition"], ["is_main"] = current[i]["is_main"], ["parts"] = current[i]["parts"],
                        }).ToList();
                    }
                    else { unmatched++; row["action"] = "unmatched"; }
                    continue;
                }

                int target = m.Target;
                string how = m.How;
                if (PlainJson.Flag(s, "is_main") && !PlainJson.Flag(current[target], "is_main"))
                {
                    var mains = mainsByDevice.TryGetValue(Device(s), out var list) ? list : new List<int>();
                    if (mains.Count == 1) { target = mains[0]; how += "+main_redirect"; redirected++; }
                    else if (promoteMain && mains.Count == 0)
                    {
                        var f = functions[target];
                        if (!dryRun)
                        {
                            try
                            {
                                ctx.Lock(f);
                                f.IsMainFunction = true;
                                if (!Safe.Get(() => f.IsMainFunction, false)) { failed++; row["action"] = "failed: promote to main read back false"; continue; }
                            }
                            catch (Exception ex) { failed++; row["action"] = "failed: promote to main: " + Safe.Error(ex); continue; }
                            current[target]["is_main"] = true;
                        }
                        Add(mainsByDevice, Device(s), target);   // never promote a second one for this device
                        how += "+promoted_main";
                        promoted++;
                    }
                    else
                    {
                        unmatched++;
                        row["action"] = $"unmatched: recorded as a main function, matched a non-main one, and the device has {mains.Count} main functions (promote_main makes it main when it has none)";
                        continue;
                    }
                }
                if (!used.Add(target)) { ambiguous++; row["action"] = "skipped: target already restored from another snapshot row"; continue; }
                if (how.StartsWith("id", StringComparison.Ordinal)) byId++; else byKey++;
                row["match"] = how;
                row["target_id"] = current[target]["id"];

                var have = (List<Dictionary<string, object?>>)current[target]["parts"]!;
                row["have"] = have;
                var wantBag = Bag(sParts);
                if (SameBag(wantBag, Bag(have))) { unchanged++; row["action"] = "unchanged"; continue; }
                if (PlainJson.Flag(current[target], "fixed")) { failed++; row["action"] = "failed: device is fixed (IsFixedDevice)"; continue; }
                if (dryRun) { changed++; row["action"] = "would_set"; continue; }

                var fn = functions[target];
                try
                {
                    ctx.Lock(fn);
                    var remaining = new Dictionary<string, int>(wantBag, StringComparer.OrdinalIgnoreCase);
                    foreach (var ar in fn.ArticleReferences ?? Array.Empty<ArticleReference>())
                    {
                        string k = ar.PartNr + "\u0001" + ar.VariantNr;
                        if (remaining.TryGetValue(k, out int count))
                        {
                            if (ar.Count != count) { ar.Count = count; ar.StoreToObject(); }
                            remaining.Remove(k);
                        }
                        else fn.RemoveArticleReference(ar);
                    }
                    foreach (var kv in remaining)
                    {
                        var pv = kv.Key.Split('\u0001');
                        fn.AddArticleReference(pv[0], pv[1], (uint)Math.Max(kv.Value, 1));
                    }
                    var after = Read(fn);
                    row["after"] = after;
                    if (SameBag(wantBag, Bag(after))) { changed++; row["action"] = "set"; }
                    else { failed++; row["action"] = "failed: read-back differs"; }
                }
                catch (Exception ex) { failed++; row["action"] = "failed: " + Safe.Error(ex); }
            }

            string Action(Dictionary<string, object?> r) => r.TryGetValue("action", out var a) ? Convert.ToString(a) ?? "" : "";
            return new Dictionary<string, object?>
            {
                ["dry_run"] = dryRun,
                ["promote_main"] = promoteMain,
                ["ids_used"] = useIds,
                ["snapshot_rows"] = snapshot.Count,
                ["considered_with_parts"] = wanted.Count,
                ["matched"] = byId + byKey,
                ["matched_by_id"] = byId,
                ["matched_by_key"] = byKey,
                ["redirected_to_main"] = redirected,
                [dryRun ? "would_promote_to_main" : "promoted_to_main"] = promoted,
                ["unmatched"] = unmatched,
                ["ambiguous"] = ambiguous,
                ["unchanged"] = unchanged,
                [dryRun ? "would_change" : "changed"] = changed,
                ["failed"] = failed,
                ["samples_changed"] = rows.Where(r => Action(r) is "set" or "would_set").Take(8).ToList(),
                ["samples_unmatched"] = rows.Where(r => Action(r).StartsWith("unmatched", StringComparison.Ordinal)).Take(8).ToList(),
                ["samples_ambiguous"] = rows.Where(r => Action(r) == "ambiguous").Take(3).ToList(),
                ["samples_failed"] = rows.Where(r => Action(r).StartsWith("failed", StringComparison.Ordinal)).Take(8).ToList(),
                ["ok"] = failed == 0,
                ["rows"] = rows,
            };
        }

        /// <summary>(part, variant) -&gt; summed count.</summary>
        public static Dictionary<string, int> Bag(IEnumerable<Dictionary<string, object?>> parts)
        {
            var bag = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var p in parts)
            {
                string k = PlainJson.Str(p, "part") + "\u0001" + PlainJson.Str(p, "variant");
                bag[k] = (bag.TryGetValue(k, out int n) ? n : 0) + (int)PlainJson.Num(p, "count");
            }
            return bag;
        }

        /// <summary>True when both bags hold the same parts with the same counts.</summary>
        public static bool SameBag(Dictionary<string, int> a, Dictionary<string, int> b) =>
            a.Count == b.Count && a.All(kv => b.TryGetValue(kv.Key, out int n) && n == kv.Value);

        private static List<string> Cp(Dictionary<string, object?> r) =>
            (r.TryGetValue("cp", out var c) ? c as IEnumerable : null)?.Cast<object?>()
            .Select(x => Convert.ToString(x, CultureInfo.InvariantCulture) ?? "").ToList() ?? new List<string>();

        private static string Key(Dictionary<string, object?> r) =>
            string.Join("|", new[] { "page", "full_dt", "definition", "category", "symbol", "variant" }.Select(k => PlainJson.Str(r, k)).Concat(Cp(r)));

        private static string OlderKey(Dictionary<string, object?> r) =>
            string.Join("|", new[] { "page", "dt", "symbol", "category" }.Select(k => PlainJson.Str(r, k)).Concat(Cp(r)));

        private static string LooseKey(Dictionary<string, object?> r) =>
            PlainJson.Str(r, "page") + "|" + PlainJson.Str(r, "dt") + "|" + PlainJson.Str(r, "symbol");

        /// <summary>The device a snapshot row belongs to: its full device tag, or its device tag for
        /// a schema 1 row (main functions are indexed under both).</summary>
        private static string Device(Dictionary<string, object?> r) =>
            r.ContainsKey("full_dt") ? "full|" + PlainJson.Str(r, "full_dt") : "dt|" + PlainJson.Str(r, "dt");

        private static void Add(Dictionary<string, List<int>> index, string key, int i)
        {
            if (!index.TryGetValue(key, out var list)) index[key] = list = new List<int>();
            list.Add(i);
        }

        private static List<Dictionary<string, object?>> AsRows(object? value) =>
            (value as IEnumerable)?.OfType<Dictionary<string, object?>>().ToList() ?? new List<Dictionary<string, object?>>();
    }
}
