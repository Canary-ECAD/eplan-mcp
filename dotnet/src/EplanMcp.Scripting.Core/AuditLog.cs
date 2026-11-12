using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace EplanMcp.Scripting.Core
{
    /// <summary>
    /// Append-only record of every script run, under %LOCALAPPDATA%\EplanMcp\audit (or
    /// EPLAN_MCP_AUDIT_DIR). The start line is written BEFORE the script runs, because a crashed
    /// script takes EPLAN down with it and nothing after that point is written. Each distinct source
    /// is kept once, named by its hash.
    /// </summary>
    public sealed class AuditLog
    {
        public string Directory { get; }

        public AuditLog(string? directory = null)
        {
            Directory = directory
                ?? Environment.GetEnvironmentVariable("EPLAN_MCP_AUDIT_DIR")
                ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EplanMcp", "audit");
        }

        /// <summary>Writes the start line and keeps the source. False (with the reason) when it
        /// could not: the caller decides whether the run may go ahead without it.</summary>
        public bool Start(string runId, string sourceHash, string source, IDictionary<string, object?> fields, out string? error) =>
            Try(() =>
            {
                var sources = Path.Combine(Directory, "sources");
                System.IO.Directory.CreateDirectory(sources);
                var copy = Path.Combine(sources, sourceHash + ".cs");
                if (!File.Exists(copy)) File.WriteAllText(copy, source, Encoding.UTF8);
                Append("start", runId, fields);
            }, out error);

        public bool End(string runId, IDictionary<string, object?> fields, out string? error) =>
            Try(() => Append("end", runId, fields), out error);

        private void Append(string ev, string runId, IDictionary<string, object?> fields)
        {
            System.IO.Directory.CreateDirectory(Directory);
            var line = new Dictionary<string, object?>(fields)
            {
                ["event"] = ev,
                ["run_id"] = runId,
                ["at"] = DateTime.UtcNow.ToString("o"),
                ["user"] = Environment.UserName,
                ["machine"] = Environment.MachineName,
                ["pid"] = Compat.ProcessId,
            };
            var file = Path.Combine(Directory, "audit-" + DateTime.UtcNow.ToString("yyyy-MM") + ".jsonl");
            File.AppendAllText(file, Json.Serialize(line) + "\n", Encoding.UTF8);
        }

        // Never throws: a failure is reported to the caller, which decides what it means for the run.
        private static bool Try(Action a, out string? error)
        {
            try { a(); error = null; return true; }
            catch (Exception e) { error = e.GetType().Name + ": " + e.Message; return false; }
        }
    }
}
