using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace EplanMcp.Eplan
{
    /// <summary>
    /// Checks that keep a writing script from doing more than it was asked: a count limit for bulk
    /// writes, and the envelope that ties a snapshot file to its kind, schema and project. Plain
    /// data only (no EPLAN types), so they are unit-tested without EPLAN.
    /// </summary>
    public static class Guards
    {
        /// <summary>
        /// Null when <paramref name="count"/> objects may be written under <paramref name="limit"/>;
        /// otherwise why not. A count of 0 is refused too: a bulk write that matches nothing is
        /// almost always a wrong scope, not a success.
        /// </summary>
        public static string? OverLimit(int count, long limit, string what)
        {
            if (limit < 1) return $"limit must be at least 1 (got {limit}).";
            if (count == 0) return $"nothing matched: no {what} in the given scope. Check the page and area.";
            if (count > limit)
                return $"{count} {what} match, more than limit={limit}. Nothing was written. " +
                       "Narrow the scope, or raise limit if every one of them is meant.";
            return null;
        }

        /// <summary>The snapshot envelope: {kind, schema, project, project_path, created_utc, rows}.</summary>
        public static Dictionary<string, object?> SnapshotEnvelope(string kind, int schema, string? project,
            string? projectPath, object? rows) => new Dictionary<string, object?>
        {
            ["kind"] = kind,
            ["schema"] = schema,
            ["project"] = project ?? "",
            ["project_path"] = projectPath ?? "",
            ["created_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture),
            ["rows"] = rows,
        };

        /// <summary>
        /// Checks a parsed snapshot file before anything is restored from it. Null when it is a
        /// <paramref name="kind"/> snapshot with a schema this code reads (1..<paramref name="schema"/>),
        /// taken from a project named <paramref name="project"/> (or <paramref name="allowOtherProject"/>),
        /// holding at least one row; <paramref name="rows"/> then holds the rows. Otherwise the reason.
        /// </summary>
        public static string? CheckSnapshot(object? parsed, string kind, int schema, string? project,
            bool allowOtherProject, out List<Dictionary<string, object?>> rows)
        {
            rows = new List<Dictionary<string, object?>>();
            if (parsed is not IDictionary<string, object?> file)
                return "the file is not a snapshot envelope ({kind, schema, project, rows}); a bare array " +
                       $"comes from an older version. Take a new snapshot with the {kind} snapshot tool.";
            string got = Text(file, "kind");
            if (!string.Equals(got, kind, StringComparison.Ordinal))
                return $"the file is a '{(got.Length == 0 ? "?" : got)}' snapshot, not a '{kind}' snapshot.";
            int fileSchema = Int(file, "schema");
            if (fileSchema < 1 || fileSchema > schema)
                return $"snapshot schema {fileSchema} is not supported (this version reads 1 to {schema}).";
            string from = Text(file, "project");
            if (!allowOtherProject && !string.Equals(from, project ?? "", StringComparison.OrdinalIgnoreCase))
                return $"the snapshot was taken from project '{from}', the target is '{project}'. Pass " +
                       "allow_other_project=true only if restoring into a different project (a copy) is intended.";
            if (file.TryGetValue("rows", out var value) && value is IEnumerable<object?> list)
                rows = list.OfType<Dictionary<string, object?>>().ToList();
            if (rows.Count == 0) return "the snapshot holds no rows.";
            return null;
        }

        private static string Text(IDictionary<string, object?> d, string key) =>
            d.TryGetValue(key, out var v) && v != null ? Convert.ToString(v, CultureInfo.InvariantCulture) ?? "" : "";

        private static int Int(IDictionary<string, object?> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return 0;
            try { return Convert.ToInt32(v, CultureInfo.InvariantCulture); }
            catch (Exception) { return 0; }
        }
    }
}
