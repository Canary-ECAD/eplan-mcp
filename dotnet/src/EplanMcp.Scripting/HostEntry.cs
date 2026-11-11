using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text;
using EplanMcp.Contracts;
using EplanMcp.Scripting.Core;

namespace EplanMcp.Scripting
{
    /// <summary>
    /// The two entry points every runtime calls: <see cref="Run"/> and <see cref="Hello"/>. Both read
    /// and write files and never throw, so the caller always gets a JSON answer.
    /// </summary>
    public static class HostEntry
    {
        /// <summary>Runs the request file and writes the result file.</summary>
        public static void Run(string requestPath, string resultPath, string runtime, string? hostDir = null)
        {
            string text;
            try
            {
                var req = Json.Deserialize<RunRequest>(File.ReadAllText(requestPath, Encoding.UTF8))
                          ?? throw new InvalidDataException("The request file is empty.");
                if (string.IsNullOrEmpty(req.RunFolder)) req.RunFolder = Path.GetDirectoryName(resultPath) ?? "";
                AddEplanApiReferences(req);
                var result = RunPipeline.Execute(req, new EplanEnvironment(runtime, hostDir == null ? null : new[] { hostDir }));
                try { text = Json.Serialize(result); }
                catch (Exception e)
                {
                    // The run happened: say so, even if its full result cannot be written.
                    text = Json.Serialize(new RunResult
                    {
                        CoreVersion = RunPipeline.CoreVersion, Runtime = runtime, RunId = result.RunId, Ok = false, Phase = result.Phase,
                        Error = "The result could not be serialized: " + e.Message + (result.Ok ? " (the script itself ran without error)" : " | " + result.Error),
                        Warnings = result.Warnings, UndoDescription = result.UndoDescription, Project = result.Project,
                    });
                }
            }
            catch (Exception e)
            {
                text = Json.Serialize(new RunResult { CoreVersion = RunPipeline.CoreVersion, Runtime = runtime, Phase = "request", Error = "Could not read the request: " + e.Message });
            }
            TryWrite(resultPath, text);
        }

        /// <summary>Never throws into EPLAN: a result that cannot be written is lost, and the
        /// server reports "no result" (the audit log still has the run).</summary>
        private static void TryWrite(string path, string text)
        {
            try { WriteAtomically(path, text); } catch { }
        }

        /// <summary>Handshake: versions, features, EPLAN version, license and open projects.</summary>
        public static void Hello(string resultPath, string runtime)
        {
            var hello = new HelloResult
            {
                CoreVersion = RunPipeline.CoreVersion,
                Runtime = runtime,
                ProcessId = Environment.ProcessId,
                RoslynVersion = typeof(Microsoft.CodeAnalysis.CSharp.CSharpCompilation).Assembly.GetName().Version?.ToString(),
            };
            try
            {
                var app = new Eplan.EplApi.System.EplApplication();
                hello.EplanVersion = app.Version;
                hello.License = app.License;
            }
            catch (Exception e) { hello.Error = "EPLAN version/license unavailable: " + e.Message; }
            try
            {
                using (new Eplan.EplApi.DataModel.LockingStep())
                    hello.OpenProjects = new Eplan.EplApi.DataModel.ProjectManager().OpenProjects.Select(p => p.ProjectLinkFilePath).ToArray();
            }
            catch (Exception e) { hello.Error = (hello.Error == null ? "" : hello.Error + "; ") + "open projects unavailable: " + e.Message; }
            TryWrite(resultPath, Json.Serialize(hello));
        }

        /// <summary>EPLAN loads its API assemblies lazily and the compile references come from what is
        /// loaded, so a script using one nothing has touched yet (MasterData in a fresh session) failed
        /// with CS0234. Reference every API assembly in EPLAN's Bin, as the offline host does. Found by
        /// name, so no EPLAN type is touched here (the bootstrap resolver may not be in place yet).</summary>
        private static void AddEplanApiReferences(RunRequest req)
        {
            string? bin = null;
            foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (a.IsDynamic || a.GetName().Name != "Eplan.EplApi.BaseNetu") continue;
                try { bin = Path.GetDirectoryName(a.Location); } catch (NotSupportedException) { }
                if (!string.IsNullOrEmpty(bin)) break;
            }
            if (string.IsNullOrEmpty(bin) || !Directory.Exists(bin)) return;
            foreach (var dll in Directory.GetFiles(bin!, "Eplan.EplApi.*Netu.dll"))
                if (!req.References.Contains(dll)) req.References.Add(dll);
        }

        // ------------------------------------------------------------------ bootstrap path

        /// <summary>Called by the reflection-only bootstrap script after it loaded the host
        /// assemblies from bytes. No EPLAN types appear in this method's body, so the resolver is in
        /// place before anything EPLAN-bound is JIT-compiled.</summary>
        public static void RunFromBootstrap(string requestPath, string resultPath, string hostDir)
        {
            InstallResolver();
            RunCore(requestPath, resultPath, hostDir);
        }

        public static void HelloFromBootstrap(string resultPath)
        {
            InstallResolver();
            HelloCore(resultPath);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void RunCore(string requestPath, string resultPath, string hostDir) => Run(requestPath, resultPath, "bootstrap", hostDir);

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void HelloCore(string resultPath) => Hello(resultPath, "bootstrap");

        private static bool _resolverInstalled;

        /// <summary>Our context was created by the bootstrap from bytes; anything it does not hold
        /// (the EPLAN API, Roslyn) resolves to the copy EPLAN has already loaded.</summary>
        private static void InstallResolver()
        {
            if (_resolverInstalled) return;
            _resolverInstalled = true;
            var own = AssemblyLoadContext.GetLoadContext(typeof(HostEntry).Assembly);
            if (own == null || own == AssemblyLoadContext.Default) return;
            own.Resolving += (ctx, name) =>
                AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a =>
                    string.Equals(a.GetName().Name, name.Name, StringComparison.OrdinalIgnoreCase)
                    && AssemblyLoadContext.GetLoadContext(a) != ctx
                    && !(AssemblyLoadContext.GetLoadContext(a)?.IsCollectible ?? false));
        }

        /// <summary>The server polls for the result file, so it must never see half a file.</summary>
        private static void WriteAtomically(string path, string text)
        {
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, text, new UTF8Encoding(false));
            File.Move(tmp, path, overwrite: true);
        }
    }
}
