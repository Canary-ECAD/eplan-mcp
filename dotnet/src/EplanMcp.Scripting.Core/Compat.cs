using System;
using System.IO;

namespace EplanMcp.Scripting.Core
{
    /// <summary>
    /// The few .NET 8 APIs the host uses that .NET Framework 4.8.1 (EPLAN 2026) lacks, in one place
    /// so the rest of the code reads the same on both.
    /// </summary>
    public static class Compat
    {
        public static int ProcessId =>
#if NETFRAMEWORK
            System.Diagnostics.Process.GetCurrentProcess().Id;
#else
            Environment.ProcessId;
#endif

        public static bool IsFinite(double d) => !double.IsNaN(d) && !double.IsInfinity(d);

        public static bool IsFinite(float f) => !float.IsNaN(f) && !float.IsInfinity(f);

        /// <summary>File.Move with overwrite, which .NET Framework does not have.</summary>
        public static void MoveOver(string from, string to)
        {
#if NETFRAMEWORK
            if (File.Exists(to))
            {
                File.Replace(from, to, null);
                return;
            }
            File.Move(from, to);
#else
            File.Move(from, to, overwrite: true);
#endif
        }

        /// <summary>The folder an assembly was loaded from, or null for one loaded from bytes (the
        /// bootstrap's host). .NET Framework throws on Path.GetDirectoryName("") where .NET 8 returns
        /// null, and its Location is "" for such an assembly.</summary>
        public static string? DirectoryOf(System.Reflection.Assembly assembly)
        {
            string location;
            try { location = assembly.Location; }
            catch (NotSupportedException) { return null; }
            return string.IsNullOrEmpty(location) ? null : Path.GetDirectoryName(location);
        }

        /// <summary>What the host runs on, e.g. ".NET 8.0.11" or ".NET Framework 4.8.9290.0".</summary>
        public static string FrameworkDescription =>
            System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription;
    }
}
