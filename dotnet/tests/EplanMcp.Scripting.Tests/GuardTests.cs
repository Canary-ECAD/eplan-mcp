using System;
using System.Collections.Generic;
using System.IO;
using EplanMcp.Eplan;
using EplanMcp.Scripting;
using EplanMcp.Scripting.Core;
using Xunit;

namespace EplanMcp.Scripting.Tests
{
    /// <summary>The write guards of the library scripts: the bulk-write limit and the snapshot
    /// envelope a restore checks before it writes. Plain data only; EPLAN is never started.</summary>
    public class GuardTests
    {
        [Fact]
        public void Bulk_write_refuses_nothing_too_many_and_a_bad_limit()
        {
            Assert.Null(Guards.OverLimit(3, 3, "lines"));
            Assert.Contains("nothing matched", Guards.OverLimit(0, 10, "lines"));
            Assert.Contains("more than limit=2", Guards.OverLimit(3, 2, "lines"));
            Assert.Contains("at least 1", Guards.OverLimit(1, 0, "lines"));
        }

        private static Dictionary<string, object?> Envelope(string kind = "parts", object? schema = null, string project = "Demo",
            List<object?>? rows = null) => new Dictionary<string, object?>
        {
            ["kind"] = kind, ["schema"] = schema ?? 1.0, ["project"] = project,
            ["rows"] = rows ?? new List<object?> { new Dictionary<string, object?> { ["page"] = "1" } },
        };

        [Fact]
        public void Snapshot_is_checked_for_kind_schema_project_and_rows()
        {
            Assert.Null(Guards.CheckSnapshot(Envelope(), "parts", 1, "demo", false, out var rows));
            Assert.Single(rows);
            Assert.Contains("bare array", Guards.CheckSnapshot(new List<object?> { new Dictionary<string, object?>() }, "parts", 1, "Demo", false, out _));
            Assert.Contains("not a 'parts' snapshot", Guards.CheckSnapshot(Envelope(kind: "macrobox"), "parts", 1, "Demo", false, out _));
            Assert.Contains("schema 2", Guards.CheckSnapshot(Envelope(schema: 2.0), "parts", 1, "Demo", false, out _));
            Assert.Contains("schema 0", Guards.CheckSnapshot(Envelope(schema: "x"), "parts", 1, "Demo", false, out _));
            Assert.Contains("allow_other_project", Guards.CheckSnapshot(Envelope(project: "Other"), "parts", 1, "Demo", false, out _));
            Assert.Null(Guards.CheckSnapshot(Envelope(project: "Other"), "parts", 1, "Demo", true, out _));
            Assert.Contains("no rows", Guards.CheckSnapshot(Envelope(rows: new List<object?>()), "parts", 1, "Demo", false, out _));
        }

        [Fact]
        public void Snapshot_file_round_trips_and_a_foreign_file_throws()
        {
            ScriptArgs Args(string file) => new ScriptArgs(Json.Deserialize<Dictionary<string, object?>>("{\"snapshot\":" + Json.Serialize(file) + "}"));
            var file = Path.GetTempFileName();
            try
            {
                PlainJson.Write(file, Guards.SnapshotEnvelope("parts", 1, "Demo", @"C:\x\Demo.elk",
                    new List<Dictionary<string, object?>> { new Dictionary<string, object?> { ["page"] = "1", ["dt"] = "K1" } }));
                var rows = PlainJson.ReadSnapshot(Args(file), "snapshot", "parts", 1, "Demo", false);
                Assert.Equal("K1", rows[0]["dt"]);
                Assert.Throws<ScriptRefusedException>(() => PlainJson.ReadSnapshot(Args(file), "snapshot", "macrobox", 1, "Demo", false));
                Assert.Throws<ScriptRefusedException>(() => PlainJson.ReadSnapshot(Args(file), "snapshot", "parts", 1, "Copy", false));
                File.WriteAllText(file, "[{\"page\":\"1\"}]");   // an older, envelope-less file
                Assert.Throws<ScriptRefusedException>(() => PlainJson.ReadSnapshot(Args(file), "snapshot", "parts", 1, "Demo", false));
                Assert.Throws<ScriptRefusedException>(() => PlainJson.ReadSnapshot(Args(file + ".missing"), "snapshot", "parts", 1, "Demo", false));
            }
            finally { File.Delete(file); }
        }

        [Fact]
        public void Snapshot_reports_its_schema_and_project_and_a_missing_argument_is_a_refusal()
        {
            ScriptArgs Args(string json) => new ScriptArgs(Json.Deserialize<Dictionary<string, object?>>(json));
            var file = Path.GetTempFileName();
            try
            {
                PlainJson.Write(file, Guards.SnapshotEnvelope("parts", 2, "Demo", "", new List<Dictionary<string, object?>> { new Dictionary<string, object?> { ["id"] = "1/2/3/0" } }));
                PlainJson.ReadSnapshot(Args("{\"snapshot\":" + Json.Serialize(file) + "}"), "snapshot", "parts", Parts.SnapshotSchema, "Copy", true, out int schema, out string from);
                Assert.Equal(2, schema);
                Assert.Equal("Demo", from);
            }
            finally { File.Delete(file); }
            var refused = Assert.Throws<ScriptRefusedException>(() => Args("{}").Require("page"));
            Assert.Contains("'page'", refused.Message);
        }

        private static Dictionary<string, object?> Fn(string id, string page, string fullDt, bool main = true, string category = "Blackbox",
            string definition = "D1", string dt = "K1") => new Dictionary<string, object?>
        {
            ["id"] = id, ["page"] = page, ["dt"] = dt, ["full_dt"] = fullDt, ["definition"] = definition, ["symbol"] = "",
            ["variant"] = -1.0, ["category"] = category, ["is_main"] = main, ["cp"] = new List<object?> { "", "", "", "" },
        };

        [Fact]
        public void Parts_match_by_id_first_then_by_the_richer_key()
        {
            // Two unplaced functions that share page and device tag: only structures tell them apart.
            var current = new List<Dictionary<string, object?>> { Fn("a", "", "=A+1-K1"), Fn("b", "", "=B+1-K1") };
            var snap = new List<Dictionary<string, object?>> { Fn("b", "", "=B+1-K1"), Fn("x", "", "=A+1-K1") };
            var plan = Parts.Plan(current, snap, useIds: true);
            Assert.Equal((1, "id"), (plan[0].Target, plan[0].How));
            Assert.Equal((0, "key"), (plan[1].Target, plan[1].How));

            // Ids from another project are never used; the key still finds both.
            plan = Parts.Plan(current, new List<Dictionary<string, object?>> { Fn("a", "", "=B+1-K1") }, useIds: false);
            Assert.Equal((1, "key"), (plan[0].Target, plan[0].How));

            // An id that now names a different kind of function is not the same object.
            plan = Parts.Plan(current, new List<Dictionary<string, object?>> { Fn("a", "", "=Z-K1", category: "Terminal") }, useIds: true);
            Assert.Equal("none", plan[0].How);
        }

        [Fact]
        public void Parts_tie_is_refused_with_its_candidates_and_a_claimed_function_is_no_candidate()
        {
            var current = new List<Dictionary<string, object?>> { Fn("a", "", "-X1", main: false), Fn("b", "", "-X1", main: false), Fn("c", "", "-X1", main: false) };
            var plan = Parts.Plan(current, new List<Dictionary<string, object?>> { Fn("gone", "", "-X1", main: false) }, useIds: true);
            Assert.Equal("ambiguous", plan[0].How);
            Assert.Equal(new[] { 0, 1, 2 }, plan[0].Candidates);

            // b is taken by its id first, so the key rows see only a and c.
            plan = Parts.Plan(current, new List<Dictionary<string, object?>> { Fn("gone", "", "-X1", main: false), Fn("b", "", "-X1", main: false) }, useIds: true);
            Assert.Equal(new[] { 0, 2 }, plan[0].Candidates);
            Assert.Equal((1, "id"), (plan[1].Target, plan[1].How));

            // Several candidates with exactly one main: the main.
            current[2]["is_main"] = true;
            plan = Parts.Plan(current, new List<Dictionary<string, object?>> { Fn("gone", "", "-X1", main: false) }, useIds: false);
            Assert.Equal((2, "key+main_of_3"), (plan[0].Target, plan[0].How));
        }

        [Fact]
        public void Parts_schema_1_rows_match_by_the_older_key()
        {
            var current = new List<Dictionary<string, object?>> { Fn("a", "1", "=A-K1"), Fn("b", "2", "=A-K1") };
            var old = new Dictionary<string, object?> { ["page"] = "2", ["dt"] = "K1", ["symbol"] = "", ["category"] = "Blackbox", ["cp"] = new List<object?> { "", "", "", "" } };
            var plan = Parts.Plan(current, new List<Dictionary<string, object?>> { old }, useIds: true);
            Assert.Equal((1, "older_key"), (plan[0].Target, plan[0].How));
        }
    }
}
