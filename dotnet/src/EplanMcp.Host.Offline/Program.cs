using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using Eplan.EplApi.Starter;

namespace EplanMcp.Host.Offline
{
    /// <summary>
    /// EplanMcp.Host.Offline --queue &lt;folder&gt; [--bin &lt;Platform Bin&gt;] [--variant-bin &lt;product Bin&gt;] [--idle-minutes 30]
    /// </summary>
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            string? bin = Arg(args, "--bin")
                ?? Assembly.GetEntryAssembly()!.GetCustomAttributes<AssemblyMetadataAttribute>()
                    .FirstOrDefault(a => a.Key == "EplanBinPath")?.Value;
            string? queue = Arg(args, "--queue");
            double idle = double.TryParse(Arg(args, "--idle-minutes"), out var m) ? m : 30;
            if (string.IsNullOrEmpty(bin) || !Directory.Exists(bin))
            {
                Console.Error.WriteLine("EPLAN Bin folder not found: " + bin);
                return 2;
            }
            if (string.IsNullOrEmpty(queue))
            {
                Console.Error.WriteLine("Usage: EplanMcp.Host.Offline --queue <folder> [--bin <EPLAN Bin>] [--idle-minutes 30]");
                return 2;
            }

            var queueDir = Path.GetFullPath(queue!);   // before the current directory moves to Bin
            // EPLAN wants the PRODUCT VARIANT's Bin (where the variant's launcher lives) as well as the
            // Platform Bin that holds the API: <EPLAN>\Platform\<v>\Bin -> <EPLAN>\Electric P8\<v>\Bin.
            string variantBin = Arg(args, "--variant-bin")
                ?? bin!.Replace(Path.DirectorySeparatorChar + "Platform" + Path.DirectorySeparatorChar,
                               Path.DirectorySeparatorChar + "Electric P8" + Path.DirectorySeparatorChar);
            if (!Directory.Exists(variantBin))
            {
                Console.Error.WriteLine("EPLAN product variant Bin folder not found: " + variantBin + " (pass --variant-bin)");
                return 2;
            }

            // The Starter DLL is EPLAN's and is not shipped beside this exe: resolve it (and, until
            // PinToEplan takes over, any EPLAN assembly) from the installed Bin folder.
            AppDomain.CurrentDomain.AssemblyResolve += (_, e) =>
            {
                var file = Path.Combine(bin, new AssemblyName(e.Name).Name + ".dll");
                return File.Exists(file) ? Assembly.LoadFrom(file) : null;
            };

            // EPLAN's API assemblies have unmanaged dependencies that load from the current
            // directory, and must load from exactly this Bin: pin BEFORE touching anything EPLAN-bound.
            Environment.CurrentDirectory = bin;
            Pin(bin!, variantBin);
            return Serve(variantBin, queueDir, TimeSpan.FromMinutes(idle));
        }

        // Non-inlined: Main must not reference the Starter types, or they would be resolved when Main
        // is compiled, before the resolver above exists.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void Pin(string platformBin, string variantBin)
        {
            var resolver = new AssemblyResolver();
            resolver.SetBinPaths(platformBin, variantBin);
            resolver.PinToEplan();
        }

        // Separate, non-inlined method: its JIT is what first loads the EPLAN-bound assemblies.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private static int Serve(string variantBin, string queue, TimeSpan idle)
        {
            // Scripts compile against the assemblies already loaded; load the helper library first.
            _ = typeof(EplanMcp.Eplan.Pages).Assembly;
            return EplanMcp.Scripting.OfflineHost.Serve(variantBin, queue, idle);
        }

        private static string? Arg(string[] args, string name)
        {
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }
    }
}
