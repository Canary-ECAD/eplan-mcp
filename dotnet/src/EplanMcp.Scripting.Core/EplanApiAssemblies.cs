using System;
using System.IO;
using System.Linq;

namespace EplanMcp.Scripting.Core
{
    /// <summary>
    /// Which EPLAN API assemblies to reference, for either naming scheme.
    /// EPLAN 2027 (.NET 8) ships the managed API as <c>Eplan.EplApi.*Netu.dll</c> and keeps
    /// <c>Eplan.EplApi.*u.dll</c> only as mixed-mode native twins that throw
    /// BadImageFormatException when referenced. EPLAN 2026 and earlier (.NET Framework) have only
    /// the managed <c>Eplan.EplApi.*u.dll</c>. So: the *Netu set when the folder has one, else *u.
    /// </summary>
    public static class EplanApiAssemblies
    {
        public const string NetSuffix = "Netu";
        public const string LegacySuffix = "u";

        /// <summary>True when <paramref name="bin"/> holds the 2027+ (*Netu) naming scheme.</summary>
        public static bool UsesNetNames(string bin) =>
            Directory.Exists(bin) && Directory.GetFiles(bin, "Eplan.EplApi.*" + NetSuffix + ".dll").Length > 0;

        /// <summary>The managed EPLAN API assemblies in <paramref name="bin"/>, newest scheme first;
        /// empty when the folder does not exist.</summary>
        public static string[] InBin(string bin)
        {
            if (!Directory.Exists(bin)) return new string[0];
            var net = Directory.GetFiles(bin, "Eplan.EplApi.*" + NetSuffix + ".dll");
            if (net.Length > 0) return net;
            return Directory.GetFiles(bin, "Eplan.EplApi.*" + LegacySuffix + ".dll")
                .Where(p => !Path.GetFileNameWithoutExtension(p).EndsWith(NetSuffix, StringComparison.OrdinalIgnoreCase))
                .ToArray();
        }

        /// <summary>The simple name of EPLAN's managed API assembly <paramref name="module"/>
        /// ("Base", "DataModel", ...) in either scheme.</summary>
        public static bool IsModule(string? assemblyName, string module) =>
            assemblyName == "Eplan.EplApi." + module + NetSuffix ||
            assemblyName == "Eplan.EplApi." + module + LegacySuffix;
    }
}
