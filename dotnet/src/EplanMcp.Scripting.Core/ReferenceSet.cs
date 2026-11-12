using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using Microsoft.CodeAnalysis;

namespace EplanMcp.Scripting.Core
{
    /// <summary>
    /// The assemblies a script compiles against. Built from what the process has actually loaded,
    /// so scripts bind to the same assemblies they will run with. Inside EPLAN's native host
    /// <c>TRUSTED_PLATFORM_ASSEMBLIES</c> may be missing, so it is only one of three sources.
    /// </summary>
    public sealed class ReferenceSet
    {
        public IReadOnlyList<MetadataReference> References { get; }

        /// <summary>Hash of the EPLAN and host assemblies' identities (name + MVID). Part of the
        /// compile-cache key, so nothing compiled against one EPLAN build loads under another.</summary>
        public string Fingerprint { get; }

        public IReadOnlyDictionary<string, string> Paths { get; }

        private ReferenceSet(Dictionary<string, string> paths, string fingerprint)
        {
            Paths = paths;
            Fingerprint = fingerprint;
            References = paths.Values.Select(p => (MetadataReference)MetadataReference.CreateFromFile(p)).ToList();
        }

        private static readonly object CacheLock = new object();
        private static string? _cachedKey;
        private static ReferenceSet? _cached;

        /// <param name="searchDirs">Folders searched for loaded assemblies that have no file location
        /// (loaded from bytes by the bootstrap).</param>
        /// <param name="extra">Additional assembly paths from the request.</param>
        /// <remarks>Cached: rebuilt only when the set of (non-script) loaded assemblies grows or
        /// shrinks, or the search folders or extra references change, so a warm run does not rescan
        /// the runtime folder.</remarks>
        public static ReferenceSet FromCurrentProcess(IEnumerable<string>? searchDirs = null, IEnumerable<string>? extra = null)
        {
            var dirList = (searchDirs ?? Array.Empty<string>()).ToList();
            var extraList = (extra ?? Array.Empty<string>()).ToList();
            var key = CacheKey(dirList, extraList);
            lock (CacheLock)
            {
                if (_cached != null && _cachedKey == key) return _cached;
                _cached = Build(dirList, extraList);
                _cachedKey = key;
                return _cached;
            }
        }

        /// <summary>The count of loaded assemblies a reference set takes (collectible script
        /// assemblies come and go with every run, so they do not count), plus the folders and the
        /// extra references' file stamps.</summary>
        internal static string CacheKey(IEnumerable<string> searchDirs, IEnumerable<string> extra)
        {
            int count = AppDomain.CurrentDomain.GetAssemblies().Count(a =>
                !a.IsDynamic && !ScriptRunner.IsCollectible(a));
            return count + "|" + string.Join(";", searchDirs) + "|" + string.Join(";", extra.Select(Stamp));
        }

        private static string Stamp(string path)
        {
            try { var f = new FileInfo(path); return path + ":" + f.Length + ":" + f.LastWriteTimeUtc.Ticks; }
            catch (Exception) { return path; }
        }

        private static ReferenceSet Build(IEnumerable<string> searchDirs, IEnumerable<string> extra)
        {
            var dirs = searchDirs.Where(Directory.Exists).ToList();
            var paths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var identity = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            // 1. Loaded assemblies win: they are exactly what the script will bind to at run time.
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (asm.IsDynamic) continue;
                var name = asm.GetName().Name;
                if (string.IsNullOrEmpty(name) || name.StartsWith(ScriptRunner.AssemblyPrefix, StringComparison.Ordinal)) continue;
                string? path = SafeLocation(asm);
                if (string.IsNullOrEmpty(path))
                    path = dirs.Select(d => Path.Combine(d, name + ".dll")).FirstOrDefault(File.Exists);
                if (string.IsNullOrEmpty(path) || paths.ContainsKey(name)) continue;
                paths[name] = path!;
                if (name.StartsWith("Eplan.", StringComparison.OrdinalIgnoreCase) || name.StartsWith("EplanMcp.", StringComparison.Ordinal))
                    identity[name] = asm.ManifestModule.ModuleVersionId.ToString("N");
            }

            // 2. The trusted platform list, when the host provides one.
            if (AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") is string tpa)
                foreach (var p in tpa.Split(Path.PathSeparator))
                    AddIfManaged(paths, p);

            // 3. The runtime directory (covers framework facades nothing has loaded yet).
            AddRuntimeDirectory(paths);

            foreach (var p in extra)
                if (File.Exists(p)) paths[Path.GetFileNameWithoutExtension(p)] = Path.GetFullPath(p);

            var fp = string.Join(";", identity.Select(kv => kv.Key + "=" + kv.Value));
            return new ReferenceSet(paths, Hashing.Sha256Hex(fp));
        }

        /// <summary>A reference set from explicit files plus the runtime directory: for compiling
        /// scripts outside EPLAN (CI checks against an installed EPLAN's Bin folder).</summary>
        public static ReferenceSet FromPaths(IEnumerable<string> files)
        {
            var paths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var p in files) AddIfManaged(paths, p);
            AddRuntimeDirectory(paths);
            return new ReferenceSet(paths, Hashing.Sha256Hex(string.Join(";", paths.Keys.OrderBy(k => k))));
        }

        /// <summary>The runtime's own folder. On .NET Framework its facades (netstandard.dll,
        /// System.Runtime.dll) sit in a Facades subfolder; a script needs them as soon as it touches a
        /// type from a netstandard2.0 library (EplanMcp.Contracts, System.Text.Json).</summary>
        private static void AddRuntimeDirectory(Dictionary<string, string> paths)
        {
            var runtimeDir = Path.GetDirectoryName(typeof(object).Assembly.Location);
            if (string.IsNullOrEmpty(runtimeDir)) return;
            foreach (var p in Directory.EnumerateFiles(runtimeDir!, "*.dll")) AddIfManaged(paths, p);
            var facades = Path.Combine(runtimeDir!, "Facades");
            if (Directory.Exists(facades))
                foreach (var p in Directory.EnumerateFiles(facades, "*.dll")) AddIfManaged(paths, p);
        }

        private static void AddIfManaged(Dictionary<string, string> paths, string p)
        {
            if (string.IsNullOrEmpty(p) || !File.Exists(p)) return;
            var name = Path.GetFileNameWithoutExtension(p);
            if (paths.ContainsKey(name)) return;
            try { AssemblyName.GetAssemblyName(p); paths[name] = p; }
            catch (BadImageFormatException) { }   // native DLLs sit in the runtime directory too
        }

        private static string? SafeLocation(Assembly asm)
        {
            try { return asm.Location; } catch (NotSupportedException) { return null; }
        }
    }

    /// <summary>
    /// What a user approves before a write to a real project: the script source, every helper
    /// source, the exact argument text, the resolved target project and the dry_run flag, joined
    /// with NUL. The server computes nothing itself; it shows the first 16 hex digits a compile_only
    /// run of the same request returned and passes them back as confirm. So an approval for one
    /// project, or for a dry run, never confirms a write to another project or a real run.
    /// </summary>
    public static class Approval
    {
        public static string Hash(string source, IEnumerable<string> helperTexts, string? argsCanonical, string? project, bool dryRun) =>
            Hashing.Sha256Hex(source + "\0" + string.Join("\0", helperTexts) + "\0" + (argsCanonical ?? "{}")
                + "\0" + NormalizeProject(project) + "\0" + (dryRun ? "dry_run" : "run"));

        /// <summary>The project path in one spelling: full path, upper case ("" for none), so a
        /// compile_only run on one runtime and the write on another agree.</summary>
        internal static string NormalizeProject(string? project)
        {
            if (string.IsNullOrWhiteSpace(project)) return "";
            try { project = Path.GetFullPath(project); } catch (Exception) { }
            return project!.ToUpperInvariant();
        }
    }

    public static class Hashing
    {
        public static string Sha256Hex(string text) => Sha256Hex(Encoding.UTF8.GetBytes(text));

        public static string Sha256Hex(byte[] bytes)
        {
            using var sha = SHA256.Create();
            var h = sha.ComputeHash(bytes);
            var sb = new StringBuilder(h.Length * 2);
            foreach (var b in h) sb.Append(b.ToString("x2"));
            return sb.ToString();
        }
    }
}
