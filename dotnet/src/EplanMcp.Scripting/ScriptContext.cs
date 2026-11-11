using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using Eplan.EplApi.DataModel;
using EplanMcp.Scripting.Core;

namespace EplanMcp.Scripting
{
    /// <summary>
    /// Everything a script gets. Scripts reach EPLAN through this object rather than through
    /// <c>ActionCallingContext</c> or the selection, which is what lets one script run in the add-in,
    /// the bootstrap and the offline host. Project access is already inside a <see cref="LockingStep"/>:
    /// the host's own on the bootstrap and offline paths, EPLAN's action lock in the add-in.
    /// </summary>
    public sealed class ScriptContext
    {
        private readonly List<string> _log;
        private readonly ProgressWriter _progress;

        internal ScriptContext(Project? project, ScriptArgs args, Budget budget, ProgressWriter progress,
            List<string> log, bool dryRun, bool writeAllowed, string runId, string runFolder)
        {
            Project = project;
            Args = args;
            Budget = budget;
            _progress = progress;
            _log = log;
            DryRun = dryRun;
            WriteAllowed = writeAllowed;
            RunId = runId;
            RunFolder = runFolder;
        }

        /// <summary>The project this run acts on; null when none is open.</summary>
        public Project? Project { get; }

        public ScriptArgs Args { get; }

        /// <summary>Call <c>Budget.Check()</c> inside every long loop: it is the only way a run
        /// can be stopped (time limit or a cancel request).</summary>
        public Budget Budget { get; }

        /// <summary>True when the caller asked for a preview: report what would change, change nothing.</summary>
        public bool DryRun { get; }

        /// <summary>True when this run passed the write gate (scratch clone, or a confirmed saved script).</summary>
        public bool WriteAllowed { get; }

        public string RunId { get; }

        /// <summary>A folder this run may write files to.</summary>
        public string RunFolder { get; }

        public void Log(string message)
        {
            if (_log.Count < 2000) _log.Add(message);
        }

        public void Progress(double done, double? total = null, string? message = null) => _progress.Report(done, total, message);

        /// <summary>The project, or a clear error when none is open.</summary>
        public Project RequireProject() =>
            Project ?? throw new ScriptRefusedException("No project to act on. Open a project (a scratch clone for writes) or pass the 'project' argument.");

        /// <summary>Locks an object for writing (SmartLock also locks the parent page). Refuses when
        /// the run may not write, is a dry run, or the object does not belong to <see cref="Project"/>
        /// (the write gate approved that project only).</summary>
        public T Lock<T>(T obj) where T : StorableObject
        {
            if (!WriteAllowed) throw new InvalidOperationException("This run may not write. Use a scratch clone, and declare '// @writes true'.");
            if (DryRun) throw new InvalidOperationException("Dry run: report the change instead of making it (check ctx.DryRun).");
            if (obj == null) throw new ArgumentNullException(nameof(obj));
            string? owner = obj.Project?.ProjectLinkFilePath, target = Project?.ProjectLinkFilePath;
            if (!SameProject(owner, target))
                throw new InvalidOperationException($"This object belongs to {(owner == null ? "no project" : "project '" + owner + "'")}, not to the run's project '{target}'. A run may change only its own project.");
            obj.SmartLock();
            return obj;
        }

        private static bool SameProject(string? a, string? b)
        {
            if (string.IsNullOrEmpty(a) || string.IsNullOrEmpty(b)) return false;
            try { return string.Equals(System.IO.Path.GetFullPath(a), System.IO.Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase); }
            catch { return string.Equals(a, b, StringComparison.OrdinalIgnoreCase); }
        }
    }

    /// <summary>Typed access to the run's arguments.</summary>
    public sealed class ScriptArgs
    {
        private readonly Dictionary<string, object?> _raw;

        public ScriptArgs(Dictionary<string, object?>? raw)
        {
            _raw = new Dictionary<string, object?>(raw ?? new Dictionary<string, object?>(), StringComparer.OrdinalIgnoreCase);
        }

        public IEnumerable<string> Names => _raw.Keys;

        public bool Has(string name) => _raw.TryGetValue(name, out var v) && v != null && !(v is JsonElement e && e.ValueKind == JsonValueKind.Null);

        public string? String(string name, string? fallback = null)
        {
            if (!_raw.TryGetValue(name, out var v) || v == null) return fallback;
            if (v is JsonElement e)
                return e.ValueKind switch
                {
                    JsonValueKind.String => e.GetString(),
                    JsonValueKind.Null or JsonValueKind.Undefined => fallback,
                    _ => e.GetRawText(),
                };
            return Convert.ToString(v, CultureInfo.InvariantCulture);
        }

        public long Int(string name, long fallback = 0) =>
            long.TryParse(String(name), NumberStyles.Integer, CultureInfo.InvariantCulture, out var n) ? n : fallback;

        public double Number(string name, double fallback = 0) =>
            double.TryParse(String(name), NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d : fallback;

        public bool Bool(string name, bool fallback = false)
        {
            var s = String(name);
            if (s == null) return fallback;
            return s.Equals("true", StringComparison.OrdinalIgnoreCase) || s == "1" || s.Equals("yes", StringComparison.OrdinalIgnoreCase);
        }

        public List<string> List(string name)
        {
            if (!_raw.TryGetValue(name, out var v) || v == null) return new List<string>();
            if (v is JsonElement e && e.ValueKind == JsonValueKind.Array)
                return e.EnumerateArray().Select(x => x.ValueKind == JsonValueKind.String ? x.GetString() ?? "" : x.GetRawText()).ToList();
            var s = String(name) ?? "";
            return s.Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries).Select(x => x.Trim()).ToList();
        }

        /// <summary>The raw JSON text of one argument (an object or array stays JSON), or null.</summary>
        public string? Json(string name)
        {
            if (!_raw.TryGetValue(name, out var v) || v == null) return null;
            return v is JsonElement e ? e.GetRawText() : JsonSerializer.Serialize(v);
        }

        /// <summary>All arguments as one JSON object.</summary>
        public string ToJson() =>
            "{" + string.Join(",", _raw.Select(kv => JsonSerializer.Serialize(kv.Key) + ":" + (Json(kv.Key) ?? "null"))) + "}";

        public string Require(string name) =>
            String(name) ?? throw new ScriptRefusedException($"Missing required argument '{name}'.");
    }
}
