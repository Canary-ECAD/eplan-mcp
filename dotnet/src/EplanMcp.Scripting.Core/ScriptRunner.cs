using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;

namespace EplanMcp.Scripting.Core
{
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

        /// <summary>Loads the script into its own collectible context, calls its static
        /// <c>Run(ctx)</c>, and unloads. The caller must turn the result into plain data BEFORE the
        /// context is collected, so <paramref name="shape"/> runs while the script is still loaded.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        public static RunOutcome Run(byte[] image, object context, Func<object?, object?> shape)
        {
            var outcome = new RunOutcome();
            var host = AssemblyLoadContext.GetLoadContext(typeof(ScriptRunner).Assembly) ?? AssemblyLoadContext.Default;
            var alc = new ScriptLoadContext(AssemblyPrefix + Guid.NewGuid().ToString("N"), host);
            try
            {
                var asm = alc.LoadFromStream(new MemoryStream(image));
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
            catch (Exception e)
            {
                outcome.Error = e;
            }
            finally
            {
                alc.Unload();
            }
            outcome.Context = new WeakReference(alc);
            return outcome;
        }

        /// <summary>True when the script's context was collected. Call after <see cref="Run"/> has
        /// returned, so no stack frame holds a reference. Waits up to about a second: EPLAN's own
        /// AssemblyLoad subscribers hold a reference to a new assembly for a short while.</summary>
        public static bool WaitForUnload(WeakReference? weak, int attempts = 20, int pauseMs = 50)
        {
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

        internal static Assembly? FindLoaded(string? simpleName, AssemblyLoadContext hostContext)
        {
            if (string.IsNullOrEmpty(simpleName)) return null;
            Assembly? Pick(System.Collections.Generic.IEnumerable<Assembly> set) =>
                set.FirstOrDefault(a => string.Equals(a.GetName().Name, simpleName, StringComparison.OrdinalIgnoreCase));

            return Pick(hostContext.Assemblies)
                ?? Pick(AssemblyLoadContext.Default.Assemblies)
                ?? Pick(AppDomain.CurrentDomain.GetAssemblies().Where(a =>
                       !(AssemblyLoadContext.GetLoadContext(a)?.IsCollectible ?? false)));
        }
    }
}
