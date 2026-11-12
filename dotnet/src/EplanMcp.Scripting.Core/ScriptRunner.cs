using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
#if !NETFRAMEWORK
using System.Runtime.Loader;
#endif

namespace EplanMcp.Scripting.Core
{
#if !NETFRAMEWORK
    /// <summary>
    /// A collectible context for one script. Every dependency resolves to an assembly that is
    /// ALREADY loaded (the host's own context first, then the default one, then anything loaded),
    /// so a script sees the live EPLAN API and the live add-ins, never a private second copy.
    /// </summary>
    internal sealed class ScriptLoadContext : AssemblyLoadContext
    {
        private readonly AssemblyLoadContext _hostContext;

        public ScriptLoadContext(string name, AssemblyLoadContext hostContext) : base(name, isCollectible: true)
        {
            _hostContext = hostContext;
        }

        protected override Assembly? Load(AssemblyName name) => ScriptRunner.FindLoaded(name.Name, _hostContext);
    }
#endif

    public sealed class RunOutcome
    {
        public object? Value { get; set; }
        public Exception? Error { get; set; }
        public WeakReference? Context { get; set; }
    }

    public static class ScriptRunner
    {
        /// <summary>Names of compiled scripts; excluded from reference sets.</summary>
        public const string AssemblyPrefix = "EplanMcpScript_";

        /// <summary>True where a script's assembly is unloaded after its run (.NET 8, collectible
        /// load contexts). .NET Framework (EPLAN 2026) cannot unload from the process's only
        /// AppDomain, and EPLAN's objects cannot cross into another one: there each distinct
        /// script is loaded once and stays until EPLAN closes (see <see cref="Run"/>).</summary>
        public static bool CanUnload =>
#if NETFRAMEWORK
            false;
#else
            true;
#endif

        /// <summary>The framework the host runs on: "net8" or "netfx". Names the release assets.</summary>
        public static string Flavor =>
#if NETFRAMEWORK
            "netfx";
#else
            "net8";
#endif

        /// <summary>Loads the script, calls its static <c>Run(ctx)</c>, and (where it can) unloads
        /// it. The caller must turn the result into plain data BEFORE the context is collected, so
        /// <paramref name="shape"/> runs while the script is still loaded.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        public static RunOutcome Run(byte[] image, object context, Func<object?, object?> shape)
        {
            var outcome = new RunOutcome();
#if NETFRAMEWORK
            try
            {
                var asm = LoadOnce(image);
                Invoke(asm, context, shape, outcome);
            }
            catch (Exception e)
            {
                outcome.Error = e;
            }
#else
            var host = AssemblyLoadContext.GetLoadContext(typeof(ScriptRunner).Assembly) ?? AssemblyLoadContext.Default;
            var alc = new ScriptLoadContext(AssemblyPrefix + Guid.NewGuid().ToString("N"), host);
            try
            {
                var asm = alc.LoadFromStream(new MemoryStream(image));
                Invoke(asm, context, shape, outcome);
            }
            catch (Exception e)
            {
                outcome.Error = e;
            }
            finally
            {
                alc.Unload();
            }
            outcome.Context = new WeakReference(alc);
#endif
            return outcome;
        }

        private static void Invoke(Assembly asm, object context, Func<object?, object?> shape, RunOutcome outcome)
        {
            var run = FindEntry(asm, context.GetType());
            try
            {
                outcome.Value = shape(run.Invoke(null, new[] { context }));
            }
            catch (TargetInvocationException tie) when (tie.InnerException != null)
            {
                outcome.Error = tie.InnerException;
            }
        }

#if NETFRAMEWORK
        private static readonly object LoadedLock = new object();
        private static readonly Dictionary<string, Assembly> LoadedImages = new Dictionary<string, Assembly>(StringComparer.Ordinal);

        /// <summary>How many distinct script images this process holds (they never unload here).</summary>
        public static int LoadedScriptCount
        {
            get { lock (LoadedLock) return LoadedImages.Count; }
        }

        /// <summary>A compiled image is deterministic for its source, helpers and references (the
        /// pipeline caches it by that key), so the same script run again reuses its assembly instead
        /// of loading a second copy. Only a changed script adds one. It is loaded from a file, never
        /// from bytes: EPLAN 2026's own AssemblyResolve handlers run first and throw on an assembly
        /// with no file location.</summary>
        private static Assembly LoadOnce(byte[] image)
        {
            string hash = Hashing.Sha256Hex(image);
            lock (LoadedLock)
            {
                if (LoadedImages.TryGetValue(hash, out var known)) return known;
                HostAssemblyResolver.Install();
                var asm = Assembly.LoadFrom(WriteImage(hash, image));
                LoadedImages[hash] = asm;
                return asm;
            }
        }

        /// <summary>Where compiled scripts are written before they load: one file per image, named by
        /// its hash, so the same image from another EPLAN process is shared rather than rewritten.</summary>
        public static string ImageFolder { get; set; } =
            Path.Combine(Path.Combine(Path.GetTempPath(), "EplanMcp"), "scripts");

        private static string WriteImage(string hash, byte[] image)
        {
            Directory.CreateDirectory(ImageFolder);
            var path = Path.Combine(ImageFolder, AssemblyPrefix + hash.Substring(0, 32) + ".dll");
            if (File.Exists(path) && Hashing.Sha256Hex(File.ReadAllBytes(path)) == hash) return path;
            var tmp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllBytes(tmp, image);
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
            return path;
        }
#endif

        /// <summary>True when the script's context was collected. Call after <see cref="Run"/> has
        /// returned, so no stack frame holds a reference. Waits up to about a second: EPLAN's own
        /// AssemblyLoad subscribers hold a reference to a new assembly for a short while. Null where
        /// scripts never unload (<see cref="CanUnload"/>).</summary>
        public static bool? WaitForUnload(WeakReference? weak, int attempts = 20, int pauseMs = 50)
        {
            if (!CanUnload) return null;
            if (weak == null) return true;
            for (int i = 0; i < attempts && weak.IsAlive; i++)
            {
                GC.Collect();
                GC.WaitForPendingFinalizers();
                if (weak.IsAlive && i < attempts - 1) System.Threading.Thread.Sleep(pauseMs);
            }
            return !weak.IsAlive;
        }

        internal static MethodInfo FindEntry(Assembly asm, Type contextType)
        {
            var candidates = asm.GetTypes()
                .SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.Static))
                .Where(m => m.Name == "Run" && m.GetParameters().Length == 1)
                .ToList();
            var match = candidates.FirstOrDefault(m => m.GetParameters()[0].ParameterType.IsAssignableFrom(contextType));
            if (match != null) return match;
            if (candidates.Count > 0)
                throw new InvalidOperationException(
                    $"Run's parameter type {candidates[0].GetParameters()[0].ParameterType.FullName} does not accept {contextType.FullName}. " +
                    "Declare it as Run(ScriptContext ctx).");
            throw new InvalidOperationException("The script has no public static Run(ScriptContext ctx) method.");
        }

        /// <summary>True for assemblies that come and go with script runs (a collectible context on
        /// .NET 8). Never true on .NET Framework, where nothing unloads.</summary>
        internal static bool IsCollectible(Assembly a)
        {
#if NETFRAMEWORK
            return false;
#else
            return AssemblyLoadContext.GetLoadContext(a)?.IsCollectible ?? false;
#endif
        }

#if !NETFRAMEWORK
        internal static Assembly? FindLoaded(string? simpleName, AssemblyLoadContext hostContext)
        {
            if (string.IsNullOrEmpty(simpleName)) return null;
            Assembly? Pick(IEnumerable<Assembly> set) =>
                set.FirstOrDefault(a => string.Equals(a.GetName().Name, simpleName, StringComparison.OrdinalIgnoreCase));

            return Pick(hostContext.Assemblies)
                ?? Pick(AssemblyLoadContext.Default.Assemblies)
                ?? Pick(AppDomain.CurrentDomain.GetAssemblies().Where(a => !IsCollectible(a)));
        }
#endif
    }

    /// <summary>
    /// .NET Framework has no load contexts, and EPLAN 2026's EPLAN.exe.config has no binding
    /// redirects for the libraries the host brings (Roslyn, System.Text.Json and their
    /// System.Memory, System.Collections.Immutable, ...). Their references disagree on minor
    /// versions, and a script or a host assembly loaded from bytes is found by no probing at all.
    /// This resolver answers by simple name: an assembly already loaded first (so a script binds to
    /// the live EPLAN API and the live host), then a file in one of the host's folders. On .NET 8
    /// the load contexts do this and <see cref="Install"/> does nothing.
    /// </summary>
    public static class HostAssemblyResolver
    {
        private static readonly object Lock = new object();
        private static readonly List<string> Folders = new List<string>();
#if NETFRAMEWORK
        private static bool _installed;
#endif

        /// <summary>Adds a folder the host's own dependencies are read from.</summary>
        public static void AddFolder(string? folder)
        {
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return;
            var full = Path.GetFullPath(folder!);
            lock (Lock)
                if (!Folders.Contains(full, StringComparer.OrdinalIgnoreCase)) Folders.Add(full);
        }

        public static void Install()
        {
#if NETFRAMEWORK
            lock (Lock)
            {
                if (_installed) return;
                _installed = true;
                AppDomain.CurrentDomain.AssemblyResolve += Resolve;
            }
#endif
        }

        internal static Assembly? Resolve(object? sender, ResolveEventArgs args)
        {
            var name = new AssemblyName(args.Name).Name;
            if (string.IsNullOrEmpty(name) || name!.EndsWith(".resources", StringComparison.OrdinalIgnoreCase)) return null;
            var loaded = AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a =>
                !a.IsDynamic && string.Equals(a.GetName().Name, name, StringComparison.OrdinalIgnoreCase));
            if (loaded != null) return loaded;
            string[] folders;
            lock (Lock) folders = Folders.ToArray();
            foreach (var folder in folders)
            {
                var path = Path.Combine(folder, name + ".dll");
                if (File.Exists(path)) return Assembly.LoadFrom(path);
            }
            return null;
        }
    }
}
