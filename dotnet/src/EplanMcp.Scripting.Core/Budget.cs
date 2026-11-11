using System;
using System.Diagnostics;
using System.IO;

namespace EplanMcp.Scripting.Core
{
    /// <summary>Thrown by <see cref="Budget.Check"/> when the run is out of time or was cancelled.</summary>
    public sealed class ScriptStoppedException : Exception
    {
        public ScriptStoppedException(string message) : base(message) { }
    }

    /// <summary>
    /// The cooperative stop for a script. EPLAN runs scripts on its UI thread and .NET cannot abort
    /// a thread, so a script stops only where it calls <see cref="Check"/>. Each call also refreshes
    /// the heartbeat file the server watches, and looks for the cancel file the server writes.
    /// </summary>
    public sealed class Budget
    {
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private readonly string? _cancelPath;
        private readonly string? _heartbeatPath;
        private long _lastFileCheckMs = -1000;

        public TimeSpan Limit { get; }
        public TimeSpan Elapsed => _clock.Elapsed;
        public TimeSpan Remaining => Limit - _clock.Elapsed;

        public Budget(double seconds, string? runFolder)
        {
            Limit = TimeSpan.FromSeconds(seconds <= 0 ? 120 : seconds);
            if (!string.IsNullOrEmpty(runFolder))
            {
                _cancelPath = Path.Combine(runFolder, "cancel");
                _heartbeatPath = Path.Combine(runFolder, "heartbeat");
            }
        }

        /// <summary>Throws <see cref="ScriptStoppedException"/> when time is up or the run was
        /// cancelled. Cheap: the file system is touched at most every 250 ms.</summary>
        public void Check()
        {
            if (_clock.Elapsed > Limit)
                throw new ScriptStoppedException($"Stopped: the run used its {Limit.TotalSeconds:0} s budget. Raise budget_seconds or do less per run.");
            var now = _clock.ElapsedMilliseconds;
            if (now - _lastFileCheckMs < 250) return;
            _lastFileCheckMs = now;
            Beat();
            if (_cancelPath != null && File.Exists(_cancelPath))
                throw new ScriptStoppedException("Stopped: the run was cancelled.");
        }

        internal void Beat()
        {
            if (_heartbeatPath == null) return;
            try { File.WriteAllText(_heartbeatPath, DateTime.UtcNow.ToString("o")); } catch { }
        }
    }

    /// <summary>Writes <c>progress.json</c> in the run folder for the server to relay.</summary>
    public sealed class ProgressWriter
    {
        private readonly string? _path;
        private readonly Budget _budget;
        private readonly Stopwatch _since = Stopwatch.StartNew();

        public ProgressWriter(string? runFolder, Budget budget)
        {
            _path = string.IsNullOrEmpty(runFolder) ? null : Path.Combine(runFolder, "progress.json");
            _budget = budget;
        }

        public void Report(double done, double? total, string? message)
        {
            if (_path == null) return;
            if (_since.ElapsedMilliseconds < 200 && total.HasValue && done < total) return;
            _since.Restart();
            try
            {
                File.WriteAllText(_path, Json.Serialize(new { done, total, message, at = DateTime.UtcNow.ToString("o") }));
            }
            catch { }
            _budget.Beat();
        }
    }
}
