using System;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text;
using Eplan.EplApi.ApplicationFramework;
using EplanMcp.Scripting;

namespace EplanMcp.Host.AddIn
{
    /// <summary>Registers nothing visible: the add-in only provides two actions for the MCP server.</summary>
    public class AddInModule : IEplAddIn
    {
        public bool OnRegister(ref bool bLoadOnStart)
        {
            bLoadOnStart = true;
            return true;
        }

        public bool OnUnregister() => true;

        public bool OnInit()
        {
            try { RunScriptAction.PrepareFramework(); }
            catch (Exception) { }   // reported by the first action instead
            return true;
        }

        public bool OnInitGui() => true;
        public bool OnExit() => true;
    }

    /// <summary><c>EplanMcp_RunScript /request:"...json" /result:"...json"</c>. Start it on the direct
    /// Remote Client path: an action started from inside the quiet-mode script wrapper cannot lock
    /// anything on the .NET 8 host (S511176).</summary>
    public class RunScriptAction : IEplAction
    {
        public bool OnRegister(ref string Name, ref int Ordinal)
        {
            Name = "EplanMcp_RunScript";
            Ordinal = 20;
            return true;
        }

        public void GetActionProperties(ref ActionProperties actionProperties) { }

        public bool Execute(ActionCallingContext ctx)
        {
            var request = Param(ctx, "request");
            var result = Param(ctx, "result");
            if (string.IsNullOrEmpty(request) || string.IsNullOrEmpty(result)) return false;
            try
            {
                PrepareFramework();
                LoadHelpers();
                RunHost(request!, result!);
            }
            catch (Exception e)
            {
                // A host DLL is missing or broken: the server still gets an answer, not a timeout.
                WriteFallback(result!, "The script host could not start in the add-in (" + e.GetType().Name + ": " + e.Message +
                    "). Rebuild and reinstall the add-in so EplanMcp.Scripting, EplanMcp.Scripting.Core and EplanMcp.Eplan sit beside it.");
            }
            return true;
        }

        // Each in its own non-inlined method: a missing assembly then fails at this call, inside the
        // try above, instead of when EPLAN compiles Execute.

        /// <summary>On .NET Framework (EPLAN 2026) the add-in's own Roslyn and System.Text.Json sit
        /// beside it, and EPLAN.exe.config has no binding redirects for their dependencies: resolve
        /// them by simple name from this folder. Nothing on .NET 8.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PrepareFramework()
        {
            EplanMcp.Scripting.Core.HostAssemblyResolver.AddFolder(Path.GetDirectoryName(typeof(RunScriptAction).Assembly.Location));
            EplanMcp.Scripting.Core.HostAssemblyResolver.Install();
        }

        /// <summary>Scripts compile against the assemblies already loaded; load the helper library first.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void LoadHelpers() => _ = typeof(EplanMcp.Eplan.Pages).Assembly;

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void RunHost(string request, string result) => HostEntry.Run(request, result, "addin");

        /// <summary>A minimal result envelope written by hand: it must not need any host assembly.
        /// (Protocol.Version is a constant, compiled into this DLL.)</summary>
        internal static void WriteFallback(string path, string error)
        {
            try
            {
                string Esc(string v) => v.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
                var text = "{\"protocol\":" + EplanMcp.Contracts.Protocol.Version + ",\"runtime\":\"addin\",\"ok\":false,\"phase\":\"request\",\"error\":\"" + Esc(error) + "\"}";
                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.WriteAllText(path + ".tmp", text, new UTF8Encoding(false));
#if NETFRAMEWORK
                if (File.Exists(path)) File.Delete(path);
                File.Move(path + ".tmp", path);
#else
                File.Move(path + ".tmp", path, true);
#endif
            }
            catch (Exception) { }
        }

        internal static string? Param(ActionCallingContext ctx, string name)
        {
            try
            {
                string value = string.Empty;
                ctx.GetParameter(name, ref value);   // returns void; the value comes back by ref
                return string.IsNullOrEmpty(value) ? null : value;
            }
            catch (Exception)
            {
                return null;
            }
        }
    }

    /// <summary><c>EplanMcp_Hello /result:"...json"</c>: versions, features, license, open projects.</summary>
    public class HelloAction : IEplAction
    {
        public bool OnRegister(ref string Name, ref int Ordinal)
        {
            Name = "EplanMcp_Hello";
            Ordinal = 20;
            return true;
        }

        public void GetActionProperties(ref ActionProperties actionProperties) { }

        public bool Execute(ActionCallingContext ctx)
        {
            var result = RunScriptAction.Param(ctx, "result");
            if (string.IsNullOrEmpty(result)) return false;
            try
            {
                RunScriptAction.PrepareFramework();
                HelloHost(result!);
            }
            catch (Exception e) { RunScriptAction.WriteFallback(result!, "The script host could not start in the add-in (" + e.GetType().Name + ": " + e.Message + ")."); }
            return true;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void HelloHost(string result) => HostEntry.Hello(result, "addin");
    }
}
