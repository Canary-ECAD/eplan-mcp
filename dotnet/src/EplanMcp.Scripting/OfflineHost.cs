using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using Eplan.EplApi.DataModel;
using EplanMcp.Contracts;
using EplanMcp.Scripting.Core;

namespace EplanMcp.Scripting
{
    /// <summary>
    /// The script host without an EPLAN window: one long-lived process that initialises EPLAN's
    /// offline API once, then serves requests dropped into a queue folder until told to stop.
    ///
    /// EPLAN's rules for offline applications shape it (2027 docs, "Eplan API offline applications"):
    /// Init once and Exit once, Exit on the main thread (never the finalizer), API assemblies loaded
    /// from EPLAN's Bin (the exe pins to it before calling here), no GUI, and a LockingStep before a
    /// project is opened. Each request opens its project and closes it again, so the interactive
    /// session can open it afterwards; a project the interactive session holds cannot be opened here.
    /// If a project cannot be closed, the host stops (Exit releases it) rather than keep its lock.
    ///
    /// Queue protocol: the server writes &lt;run_id&gt;.json = {"request": path, "result": path} into the
    /// queue folder; the host runs it and deletes the queue file. A queue file that cannot be read
    /// gets an error result when its result path can still be recovered, else it is renamed to
    /// *.bad. "stop" in the folder ends the host; a "stop" already there at start is stale and is
    /// deleted. "status.json" there is rewritten every few seconds from a timer (a heartbeat while a
    /// long script runs) with pid, versions, "busy_run_id" and "updated_at".
    /// </summary>
    public static class OfflineHost
    {
        public const string Runtime = "offline";

        private static readonly TimeSpan StatusEvery = TimeSpan.FromMilliseconds(2500);
        private static volatile string? _busyRunId;
        private static readonly object StatusLock = new object();

        /// <param name="binPath">The product variant's Bin (e.g. ...\Electric P8\&lt;version&gt;\Bin).</param>
        /// <returns>0 after a stop request or the idle timeout; 3 when the host stopped because a
        /// project could not be closed.</returns>
        public static int Serve(string binPath, string queueDir, TimeSpan idleTimeout)
        {
            Directory.CreateDirectory(queueDir);
            var stopFile = Path.Combine(queueDir, "stop");
            TryDelete(stopFile);   // left over from an earlier host: not meant for this one
            var app = new Eplan.EplApi.System.EplApplication { EplanBinFolder = binPath };
            app.Init("");
            int exitCode = 0;
            Timer? heartbeat = null;
            try
            {
                app.QuietMode = Eplan.EplApi.System.EplApplication.QuietModes.ShowNoDialogs;
                // Read on this thread once: the timer thread must never call into EPLAN.
                string? version = null, license = null;
                try { version = app.Version; license = app.License; } catch { }
                heartbeat = new Timer(_ => WriteStatus(queueDir, version, license), null, TimeSpan.Zero, StatusEvery);

                var lastWork = DateTime.UtcNow;
                while (true)
                {
                    if (File.Exists(stopFile)) break;
                    if (DateTime.UtcNow - lastWork > idleTimeout) break;
                    var next = Directory.GetFiles(queueDir, "*.json")
                        .Where(f => !Path.GetFileName(f).Equals("status.json", StringComparison.OrdinalIgnoreCase))
                        .OrderBy(File.GetCreationTimeUtc).FirstOrDefault();
                    if (next == null) { Thread.Sleep(200); continue; }
                    bool keepServing = ServeOne(next);
                    lastWork = DateTime.UtcNow;   // idle time counts from the END of the last run
                    if (!keepServing) { exitCode = 3; break; }
                }
            }
            finally
            {
                if (heartbeat != null)
                {
                    // Wait for a callback in flight, or it would write status.json again after the delete.
                    using var stopped = new ManualResetEvent(false);
                    if (heartbeat.Dispose(stopped)) stopped.WaitOne(TimeSpan.FromSeconds(5));
                }
                TryDelete(stopFile);
                lock (StatusLock) TryDelete(Path.Combine(queueDir, "status.json"));
                app.Exit();   // once, on this (the main) thread
            }
            return exitCode;
        }

        /// <summary>Runs one queue file. False when the host must stop serving (a project it opened
        /// could not be closed).</summary>
        private static bool ServeOne(string queueFile)
        {
            string? resultPath = null;
            bool keepServing = true, movedAside = false;
            try
            {
                var text = File.ReadAllText(queueFile);
                string requestPath;
                try
                {
                    using var doc = System.Text.Json.JsonDocument.Parse(text);
                    resultPath = doc.RootElement.GetProperty("result").GetString();
                    requestPath = doc.RootElement.GetProperty("request").GetString()
                                  ?? throw new InvalidDataException("'request' is null.");
                }
                catch (Exception e)
                {
                    resultPath ??= RecoverResultPath(text);
                    if (string.IsNullOrEmpty(resultPath))
                    {
                        movedAside = MoveAside(queueFile);
                        return true;
                    }
                    throw new InvalidDataException("The queue file could not be read: " + e.Message);
                }

                var req = Json.Deserialize<RunRequest>(File.ReadAllText(requestPath, Encoding.UTF8))
                          ?? throw new InvalidDataException("The request file is empty.");
                if (string.IsNullOrEmpty(req.RunFolder)) req.RunFolder = Path.GetDirectoryName(resultPath) ?? "";
                // In this process EPLAN loads its API assemblies lazily, so the compile references
                // would miss any not yet touched (HEServices, MasterData...). Reference them all.
                foreach (var dll in EplanApiAssemblies.InBin(Environment.CurrentDirectory))
                    if (!req.References.Contains(dll)) req.References.Add(dll);
                _busyRunId = req.RunId;
                var env = new OfflineEnvironment();
                var result = RunPipeline.Execute(req, env);
                if (env.CloseError != null)
                {
                    result.Warnings.Add("Closing the project after the run failed: " + env.CloseError);
                    if (env.ProjectLeftOpen)
                    {
                        result.Warnings.Add("The project is still open in the offline host, so the host stops now (exiting releases the project).");
                        keepServing = false;
                    }
                }
                Write(resultPath!, Json.Serialize(result));
            }
            catch (Exception e)
            {
                if (!string.IsNullOrEmpty(resultPath))
                    Write(resultPath!, Json.Serialize(new RunResult
                    {
                        CoreVersion = RunPipeline.CoreVersion, Runtime = Runtime, Phase = "request",
                        Error = "Offline host could not run the request: " + e.Message,
                    }));
            }
            finally
            {
                _busyRunId = null;
                if (!movedAside) TryDelete(queueFile);
            }
            return keepServing;
        }

        private static readonly Regex ResultField = new Regex(@"""result""\s*:\s*""((?:[^""\\]|\\.)*)""");

        /// <summary>The "result" path from a queue file that is not valid JSON as a whole, or null.</summary>
        public static string? RecoverResultPath(string? text)
        {
            var m = ResultField.Match(text ?? "");
            if (!m.Success) return null;
            try { return System.Text.Json.JsonSerializer.Deserialize<string>("\"" + m.Groups[1].Value + "\""); }
            catch { return null; }
        }

        /// <summary>Renames an unusable queue file to *.bad, so it is kept for a look but never
        /// picked up again. True when it was renamed.</summary>
        private static bool MoveAside(string queueFile)
        {
            try { File.Move(queueFile, queueFile + ".bad", overwrite: true); return true; }
            catch { return false; }
        }

        private static void WriteStatus(string queueDir, string? version, string? license)
        {
            try
            {
                var status = System.Text.Json.JsonSerializer.SerializeToNode(new HelloResult
                {
                    CoreVersion = RunPipeline.CoreVersion, Runtime = Runtime, ProcessId = Environment.ProcessId,
                    EplanVersion = version, License = license,
                }, Json.Options) as JsonObject ?? new JsonObject();
                status["busy_run_id"] = _busyRunId;
                status["updated_at"] = DateTime.UtcNow.ToString("o");
                lock (StatusLock) Write(Path.Combine(queueDir, "status.json"), status.ToJsonString());
            }
            catch { }   // a heartbeat must never take the host down
        }

        private static void Write(string path, string text)
        {
            try
            {
                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.WriteAllText(path + ".tmp", text, new UTF8Encoding(false));
                File.Move(path + ".tmp", path, overwrite: true);
            }
            catch { }
        }

        private static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); } catch { }
        }
    }

    /// <summary>The offline host's environment: the project is opened for the run and closed after.</summary>
    public sealed class OfflineEnvironment : IRunEnvironment
    {
        public string RuntimeName => OfflineHost.Runtime;
        public SnippetOptions Snippets => EplanEnvironment.DefaultSnippets;
        public IEnumerable<string> ReferenceSearchDirs
        {
            get
            {
                var own = Path.GetDirectoryName(typeof(OfflineEnvironment).Assembly.Location);
                return string.IsNullOrEmpty(own) ? Array.Empty<string>() : new[] { own! };
            }
        }

        /// <summary>Set when closing the run's project failed (even if the retry then worked).</summary>
        public string? CloseError { get; internal set; }

        /// <summary>True when the project could not be closed and is still open.</summary>
        public bool ProjectLeftOpen { get; internal set; }

        public IRunSession Open(RunRequest request) => new Session(request, this);

        private sealed class Session : IRunSession
        {
            private readonly RunRequest _req;
            private readonly OfflineEnvironment _env;
            private readonly LockingStep _locking = new LockingStep();   // before any project access
            private Project? _project;
            private UndoStep? _undo;

            public Session(RunRequest req, OfflineEnvironment env) { _req = req; _env = env; }

            public Preflight Resolve(ScriptManifest manifest)
            {
                var pre = new Preflight();
                if (manifest.Needs == "session" || manifest.Needs == "gui")
                {
                    pre.Ok = false;
                    pre.Error = $"This script declares '@needs {manifest.Needs}': it needs the interactive EPLAN, not the offline host. Run it with runtime='auto'.";
                    return pre;
                }
                if (string.IsNullOrWhiteSpace(_req.Project) || !File.Exists(_req.Project))
                {
                    pre.Ok = false;
                    pre.Error = "The offline host needs 'project': the full path of an existing .elk file.";
                    return pre;
                }
                pre.Project = Path.GetFullPath(_req.Project);
                return pre;
            }

            public void Authorize(ScriptManifest manifest, Preflight pre, string approvalHash)
            {
                WriteGate.Decide(pre, pre.Project, _req, approvalHash);
                try
                {
                    // Exclusive only for a run that will really write; a check or a preview reads.
                    var mode = manifest.Writes && pre.WriteAllowed && !_req.CompileOnly && !_req.DryRun
                        ? ProjectManager.OpenMode.Exclusive : ProjectManager.OpenMode.ReadOnly;
                    _project = new ProjectManager().OpenProject(pre.Project, mode);
                }
                catch (Exception e)
                {
                    pre.Ok = false;
                    pre.Error = "Could not open the project offline (is it open in EPLAN or locked by another user?): " +
                                (e.InnerException ?? e).Message;
                }
            }

            public object CreateContext(ScriptManifest manifest, Preflight pre, Budget budget, ProgressWriter progress, List<string> log) =>
                new ScriptContext(_project, new ScriptArgs(_req.Args), budget, progress, log, _req.DryRun, pre.WriteAllowed,
                    _req.RunId, _req.RunFolder);

            public string? BeginWrite(string description)
            {
                try
                {
                    _undo = new UndoManager().CreateUndoStep();
                    _undo.SetUndoDescription(description);
                    return description;
                }
                catch { return null; }
            }

            public string? Verify() => null;   // the offline host opens nothing else; EMCP004 keeps scripts on ctx.Project

            public void Dispose()
            {
                try { _undo?.CloseUndo(); } catch { }
                try { _undo?.Dispose(); } catch { }
                if (_project != null)
                {
                    var first = TryClose();
                    if (first != null)
                    {
                        var second = TryClose();
                        _env.CloseError = second == null ? first + " (closed on the retry)" : first + "; retry: " + second;
                        if (second != null) _env.ProjectLeftOpen = StillOpen();
                    }
                }
                _locking.Dispose();
            }

            private string? TryClose()
            {
                try { _project!.Close(); return null; }
                catch (Exception e) { return (e.InnerException ?? e).Message; }
            }

            private bool StillOpen()
            {
                try
                {
                    var path = Path.GetFullPath(_req.Project!);
                    return new ProjectManager().OpenProjects.Any(p =>
                        string.Equals(Path.GetFullPath(p.ProjectLinkFilePath), path, StringComparison.OrdinalIgnoreCase));
                }
                catch { return true; }   // cannot tell: assume the lock is still held
            }
        }
    }
}
