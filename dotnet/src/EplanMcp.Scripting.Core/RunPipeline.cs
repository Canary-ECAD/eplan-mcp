using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using EplanMcp.Contracts;

namespace EplanMcp.Scripting.Core
{
    /// <summary>What a runtime (add-in, bootstrap, offline host, tests) provides to the pipeline.</summary>
    public interface IRunEnvironment
    {
        /// <summary>addin | bootstrap | offline | test.</summary>
        string RuntimeName { get; }
        SnippetOptions Snippets { get; }

        /// <summary>Where to find files for loaded assemblies that have no location.</summary>
        IEnumerable<string> ReferenceSearchDirs { get; }

        /// <summary>Opens the run: e.g. takes EPLAN's LockingStep for the whole run (bootstrap and
        /// offline; the add-in runs inside EPLAN's own action lock).</summary>
        IRunSession Open(RunRequest request);
    }

    public sealed class Preflight
    {
        public bool Ok { get; set; } = true;
        public string? Error { get; set; }
        public string? Project { get; set; }
        public bool WriteAllowed { get; set; }

        /// <summary>Why writes are or are not allowed, in plain words.</summary>
        public string Gate { get; set; } = "";

        /// <summary>True when the gate opened for a real (non-scratch) project: a confirmed saved
        /// script. Such a run is refused when its audit start line cannot be written.</summary>
        public bool RealProject { get; set; }
        public List<string> Warnings { get; } = new List<string>();
    }

    public interface IRunSession : IDisposable
    {
        /// <summary>Resolves the target project into <see cref="Preflight.Project"/> (its link-file
        /// path). Decides nothing about writes yet: the approval hash covers the resolved project,
        /// so it can only be computed after this.</summary>
        Preflight Resolve(ScriptManifest manifest);

        /// <summary>Decides whether this run may write (the write gate), given the approval hash
        /// computed for the resolved project, and finishes preparing the project (the offline host
        /// opens it in the mode the gate allows). Reports failure through <see cref="Preflight.Ok"/>.</summary>
        void Authorize(ScriptManifest manifest, Preflight preflight, string approvalHash);

        /// <summary>The object passed to the script's Run(ctx).</summary>
        object CreateContext(ScriptManifest manifest, Preflight preflight, Budget budget, ProgressWriter progress, List<string> log);

        /// <summary>Called before a run that may write (opens one undo step).</summary>
        string? BeginWrite(string description);

        /// <summary>Called after the run; returns an error when the run broke an invariant (for
        /// example it changed which projects are open).</summary>
        string? Verify();
    }

    /// <summary>
    /// The whole life of one run: header, write gate, compile, safety check, run, unload, result.
    /// Every exit path produces a <see cref="RunResult"/>; nothing escapes as an exception.
    /// </summary>
    public static class RunPipeline
    {
        public static readonly string CoreVersion =
            typeof(RunPipeline).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion?.Split('+')[0]
            ?? typeof(RunPipeline).Assembly.GetName().Version?.ToString() ?? "0.0.0";

        /// <summary>Compiled images by cache key, bounded to the most recent <see cref="CacheLimit"/>.</summary>
        private static readonly ConcurrentDictionary<string, byte[]> Cache = new ConcurrentDictionary<string, byte[]>();
        private static readonly ConcurrentQueue<string> CacheOrder = new ConcurrentQueue<string>();
        internal const int CacheLimit = 200;
        internal static int CacheCount => Cache.Count;

        public static RunResult Execute(RunRequest req, IRunEnvironment env, AuditLog? audit = null)
        {
            var sw = Stopwatch.StartNew();
            var res = new RunResult { CoreVersion = CoreVersion, Runtime = env.RuntimeName, RunId = req.RunId };
            audit ??= new AuditLog();
            IRunSession? session = null;
            bool ran = false;   // the script has run: from here on a host failure must not undo its outcome
            try
            {
                if (req.Protocol != Protocol.Version)
                    return Fail(res, "request", $"Protocol {req.Protocol} is not supported by host {CoreVersion} (protocol {Protocol.Version}). Update the server or the host.");
                if (string.IsNullOrWhiteSpace(req.Source))
                    return Fail(res, "request", "The request has no script source.");

                var headerErrors = new List<string>();
                var manifest = HeaderParser.Parse(req.Source, headerErrors);
                res.Manifest = manifest;
                res.Warnings.AddRange(headerErrors);
                res.SourceHash = Hashing.Sha256Hex(req.Source);

                if (!RequirementMet(manifest.Requires, out var why))
                    return Fail(res, "request", why);

                // '// @unsafe' is honoured only in a saved library script: the server sets ScriptPath
                // only for scripts inside registered library folders. Ad-hoc code cannot grant it.
                bool allowUnsafe = manifest.Unsafe && !string.IsNullOrEmpty(req.ScriptPath);
                if (manifest.Unsafe && !allowUnsafe)
                    res.Warnings.Add("'// @unsafe' is ignored in ad-hoc code; only a saved library script may use it. The safety check ran as if it were absent.");

                // The arguments the script sees are exactly the canonical text that was approved.
                if (req.ArgsCanonical != null)
                    req.Args = Json.Deserialize<Dictionary<string, object?>>(req.ArgsCanonical) ?? new Dictionary<string, object?>();
                var helpers = req.HelperSources.Select(p => (path: p, text: File.ReadAllText(p))).ToList();

                session = env.Open(req);
                var pre = session.Resolve(manifest);
                if (pre.Ok)
                {
                    // After resolving: the approval covers the project it was given for, and dry_run.
                    res.ApprovalHash = Approval.Hash(req.Source, helpers.Select(h => h.text), req.ArgsCanonical, pre.Project, req.DryRun);
                    session.Authorize(manifest, pre, res.ApprovalHash);
                }
                res.Project = pre.Project;
                res.WriteAllowed = pre.WriteAllowed;
                res.WriteGate = pre.Gate;
                res.Warnings.AddRange(pre.Warnings);
                if (!pre.Ok) return Fail(res, "guard", pre.Error ?? "Refused.");
                // A compile_only run goes on, so the caller gets the approval hash it needs to ask for
                // a real-project write; the gate is still reported in write_gate.
                if (manifest.Writes && !pre.WriteAllowed && !req.CompileOnly)
                    return Fail(res, "guard", "This script declares '// @writes true' but this run may not write: " + pre.Gate);

                // A compile_only check of a writing script uses the write rules it would run under.
                bool readOnly = !(manifest.Writes && (pre.WriteAllowed || req.CompileOnly));

                // ---- compile (cached) + safety check
                var composed = SourceComposer.Compose(req.Source, SafeName(req.SourceName), env.Snippets);
                var refs = ReferenceSet.FromCurrentProcess(env.ReferenceSearchDirs, req.References);
                // allowUnsafe, not manifest.Unsafe: an ad-hoc copy of a saved @unsafe script must not
                // reuse the image that skipped the check.
                var key = Hashing.Sha256Hex(string.Join("\n", new[] { CoreVersion, refs.Fingerprint, readOnly.ToString(), allowUnsafe.ToString(), composed }
                    .Concat(helpers.Select(h => h.path + "\n" + h.text))
                    .Concat(req.References.Select(FileStamp))));

                if (!Cache.TryGetValue(key, out var image))
                {
                    var compiled = ScriptCompiler.Compile(composed, SafeName(req.SourceName), helpers, refs,
                        ScriptRunner.AssemblyPrefix + key.Substring(0, 16));
                    res.Diagnostics.AddRange(compiled.Diagnostics);
                    if (!compiled.Success)
                        return Fail(res, "compile", "The script did not compile. See diagnostics.");
                    // Only the script itself: helper libraries are reviewed code (a probe library,
                    // say) and legitimately use APIs a script may not.
                    var safety = SafetyAnalyzer.Check(compiled.Compilation!, readOnly, allowUnsafe,
                        compiled.Compilation!.SyntaxTrees.Take(1));
                    if (safety.Count > 0)
                    {
                        res.Diagnostics.InsertRange(0, safety);
                        return Fail(res, "compile", "The script failed the safety check. See diagnostics.");
                    }
                    image = compiled.Assembly!;
                    Remember(key, image);
                }

                if (req.CompileOnly)
                {
                    res.Ok = true;
                    res.Phase = "done";
                    res.Log.Add("compile_only: compiled and checked; not run.");
                    return res;
                }

                // ---- run
                // The script may write only if the gate allows it AND it declared '// @writes true'.
                // Decided before the audit line, so the audit records the real decision.
                pre.WriteAllowed = !readOnly;
                res.WriteAllowed = pre.WriteAllowed;
                res.AuditOk = audit.Start(req.RunId, res.SourceHash!, req.Source, new Dictionary<string, object?>
                {
                    ["runtime"] = env.RuntimeName, ["project"] = pre.Project, ["write_allowed"] = pre.WriteAllowed,
                    ["write_gate"] = pre.Gate, ["real_project"] = pre.RealProject,
                    ["script_path"] = req.ScriptPath, ["source_name"] = req.SourceName, ["args"] = req.Args,
                    ["dry_run"] = req.DryRun, ["core_version"] = CoreVersion,
                }, out var auditError);
                if (res.AuditOk == false)
                {
                    if (pre.WriteAllowed && !req.DryRun && pre.RealProject)
                        return Fail(res, "guard", "The audit log could not be written (" + auditError + "). A real project is never changed without an audit record. Fix the audit folder (EPLAN_MCP_AUDIT_DIR) and run again.");
                    res.Warnings.Add("The audit log could not be written: " + auditError);
                }

                var budget = new Budget(req.BudgetSeconds, req.RunFolder);
                var progress = new ProgressWriter(req.RunFolder, budget);
                var ctx = session.CreateContext(manifest, pre, budget, progress, res.Log);
                if (!readOnly && !req.DryRun)
                    res.UndoDescription = session.BeginWrite($"EplanMcp {manifest.Tool ?? SafeName(req.SourceName)} {req.RunId}");

                res.Phase = "run";
                var run = RunIsolated(image, ctx);
                ctx = null!;
                ran = true;

                var verify = session.Verify();
                if (ScriptRunner.CanUnload)
                    res.Unloaded = Guard(res, "checking the script unloaded", () => ScriptRunner.WaitForUnload(run.Context) ?? true);
                else
                    res.Log.Add("This EPLAN runs on .NET Framework, which cannot unload a script: it stays loaded until EPLAN closes (the same script run again reuses it).");
                if (res.Unloaded == false)
                    res.Warnings.Add("The script's code was still loaded after the run. Usually harmless (one small assembly, measured with no visible memory growth); if it keeps happening the script may leave an event handler, timer or static reference behind.");

                Guard(res, "placing the result", () =>
                {
                    var placed = Json.Place(run.Value, req.RunFolder);
                    res.Result = placed.inline;
                    res.ResultFile = placed.file;
                    res.Truncated = placed.truncated;
                    return true;
                });

                if (verify != null) { res.Error = verify; res.Phase = "guard"; }
                else if (run.Error != null) { res.Error = run.Error; res.Phase = "run"; }
                else { res.Ok = true; res.Phase = "done"; }
                if (!res.Ok && res.UndoDescription != null)
                    res.Warnings.Add(UndoHint(res.UndoDescription));
                if (run.Stopped) res.Warnings.Add("Stopped by the budget or a cancel request.");

                if (!audit.End(req.RunId, new Dictionary<string, object?>
                    {
                        ["ok"] = res.Ok, ["phase"] = res.Phase, ["error"] = res.Error, ["unloaded"] = res.Unloaded,
                        ["duration_ms"] = sw.ElapsedMilliseconds,
                    }, out var endError))
                    res.Warnings.Add("The audit end line could not be written: " + endError);
                return res;
            }
            catch (Exception e)
            {
                if (!ran) return Fail(res, res.Phase == "request" ? "request" : res.Phase, "Host error: " + Describe(e));
                // The script already ran: keep its outcome and the undo hint, report the host failure.
                res.Warnings.Add("Host error after the script ran: " + Describe(e));
                if (res.UndoDescription != null && !res.Warnings.Contains(UndoHint(res.UndoDescription)))
                    res.Warnings.Add(UndoHint(res.UndoDescription));
                return res;
            }
            finally
            {
                if (session != null)
                {
                    try { session.Dispose(); }
                    catch (Exception e) { res.Warnings.Add("Closing the run failed: " + Describe(e)); }
                }
                res.DurationMs = sw.ElapsedMilliseconds;
            }
        }

        private static string UndoHint(string undo) =>
            $"The run may have changed data before it stopped. Undo it in EPLAN with Edit > Undo \"{undo}\", or discard the scratch clone.";

        /// <summary>A step after the script ran: a failure becomes a warning, never a failed run.</summary>
        private static T? Guard<T>(RunResult res, string what, Func<T> step) where T : struct
        {
            try { return step(); }
            catch (Exception e) { res.Warnings.Add($"Host error while {what}: " + Describe(e)); return null; }
        }

        private static void Remember(string key, byte[] image)
        {
            if (!Cache.TryAdd(key, image)) return;
            CacheOrder.Enqueue(key);
            while (Cache.Count > CacheLimit && CacheOrder.TryDequeue(out var old))
                Cache.TryRemove(old, out _);
        }

        private sealed class Isolated
        {
            public System.Text.Json.Nodes.JsonNode? Value;
            public string? Error;
            public bool Stopped;
            public WeakReference? Context;
        }

        /// <summary>Runs the script and reduces everything it produced to plain data before
        /// returning. Its own frame, so no temporary (the exception, the raw return value) outlives
        /// it and keeps the script's context from unloading, Debug builds included.</summary>
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
        private static Isolated RunIsolated(byte[] image, object ctx)
        {
            var outcome = ScriptRunner.Run(image, ctx, value => Json.ToPlain(value));
            // An expected refusal is the script's answer, not a failure: {"error": message}, no stack.
            if (outcome.Error is ScriptRefusedException refused)
                return new Isolated
                {
                    Value = new System.Text.Json.Nodes.JsonObject { ["error"] = refused.Message },
                    Context = outcome.Context,
                };
            return new Isolated
            {
                Value = outcome.Value as System.Text.Json.Nodes.JsonNode,
                Error = outcome.Error == null ? null : Describe(outcome.Error),
                Stopped = outcome.Error is ScriptStoppedException,
                Context = outcome.Context,
            };
        }

        private static RunResult Fail(RunResult res, string phase, string error)
        {
            res.Ok = false;
            res.Phase = phase;
            res.Error = error;
            return res;
        }

        /// <summary>Exception text with the inner chain flattened and the stack cut to script frames
        /// first (EPLAN wraps real failures in TargetInvocationException).</summary>
        internal static string Describe(Exception e)
        {
            var parts = new List<string>();
            for (var cur = e; cur != null; cur = cur.InnerException)
                parts.Add(cur.GetType().Name + ": " + cur.Message);
            var frames = (e.StackTrace ?? "").Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0).Take(8);
            return string.Join(" -> ", parts) + "\n" + string.Join("\n", frames);
        }

        /// <summary>Supports <c>core&gt;=X.Y.Z</c> (several separated by commas).</summary>
        internal static bool RequirementMet(string? requires, out string why)
        {
            why = "";
            if (string.IsNullOrWhiteSpace(requires)) return true;
            foreach (var part in requires!.Split(',').Select(p => p.Trim()).Where(p => p.Length > 0))
            {
                if (part.StartsWith("core>=", StringComparison.OrdinalIgnoreCase))
                {
                    if (Version.TryParse(part.Substring(6), out var need) && Version.TryParse(CoreVersion, out var have) && have < need)
                    {
                        why = $"The script needs host core {need} or newer; this host is {CoreVersion}. Update the host (restart EPLAN after installing it).";
                        return false;
                    }
                }
                else if (part.StartsWith("feature:", StringComparison.OrdinalIgnoreCase))
                {
                    var f = part.Substring(8);
                    if (!Protocol.Features.Contains(f, StringComparer.OrdinalIgnoreCase))
                    {
                        why = $"The script needs host feature '{f}', which this host ({CoreVersion}) does not have.";
                        return false;
                    }
                }
            }
            return true;
        }

        private static string FileStamp(string path)
        {
            try { var f = new FileInfo(path); return path + "|" + f.Length + "|" + f.LastWriteTimeUtc.Ticks; }
            catch { return path; }
        }

        private static string SafeName(string name) =>
            string.IsNullOrWhiteSpace(name) ? "script.cs" : Path.GetFileName(name);
    }
}
