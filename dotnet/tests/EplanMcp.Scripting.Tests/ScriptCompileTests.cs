using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using EplanMcp.Scripting;
using EplanMcp.Scripting.Core;
using Xunit;

namespace EplanMcp.Scripting.Tests
{
    /// <summary>
    /// Every shipped script must compile against the installed EPLAN API and pass the safety check
    /// in the mode its header asks for. A script that only fails on the user's PC is the failure
    /// this catches.
    /// </summary>
    public class ScriptCompileTests
    {
        private static string DotnetRoot()
        {
            var dir = AppContext.BaseDirectory;
            while (dir != null && !File.Exists(Path.Combine(dir, "EplanMcp.sln"))) dir = Path.GetDirectoryName(dir);
            return dir ?? throw new InvalidOperationException("dotnet folder not found");
        }

        private static string EplanBin() =>
            typeof(ScriptCompileTests).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
                .First(a => a.Key == "EplanBinPath").Value!;

        /// <summary>EplanMcp.Eplan: the host loads it and snippets get its namespace, so every check compiles with it.</summary>
        private static string EplanHelpers => typeof(EplanMcp.Eplan.Pages).Assembly.Location;

        public static IEnumerable<object[]> Scripts()
        {
            var root = DotnetRoot();
            return Directory.GetFiles(Path.Combine(root, "scripts"), "*.cs")
                .Concat(Directory.GetFiles(Path.Combine(root, "tests", "live"), "*.cs"))
                .Select(p => new object[] { Path.GetRelativePath(root, p) });
        }

        [Theory]
        [MemberData(nameof(Scripts))]
        public void Script_compiles_against_installed_eplan(string relativePath)
        {
            var bin = EplanBin();
            Assert.True(Directory.Exists(bin), "No EPLAN at " + bin);
            var path = Path.Combine(DotnetRoot(), relativePath);
            var source = File.ReadAllText(path);
            var headerErrors = new List<string>();
            var manifest = HeaderParser.Parse(source, headerErrors);
            Assert.True(headerErrors.Count == 0, string.Join("; ", headerErrors));

            var snippets = EplanEnvironment.DefaultSnippets;
            var composed = SourceComposer.Compose(source, Path.GetFileName(path), snippets);
            var refs = ReferenceSet.FromPaths(
                EplanApiAssemblies.InBin(bin)
                    .Concat(new[] { typeof(ScriptArgs).Assembly.Location, typeof(RunPipeline).Assembly.Location, EplanHelpers }));
            var compiled = ScriptCompiler.Compile(composed, Path.GetFileName(path),
                Array.Empty<(string, string)>(), refs, "check_" + Path.GetFileNameWithoutExtension(path));
            var errors = compiled.Diagnostics.Where(d => d.Severity == "error").ToList();
            Assert.True(compiled.Success, string.Join("\n", errors.Select(e => $"{e.File}:{e.Line} {e.Id} {e.Message} {e.Hint}")));

            var safety = SafetyAnalyzer.Check(compiled.Compilation!, readOnly: !manifest.Writes, allowUnsafe: manifest.Unsafe);
            Assert.True(safety.Count == 0, string.Join("\n", safety.Select(e => $"{e.Line} {e.Id} {e.Message}")));
        }

        [Fact]
        public void Read_only_mode_rejects_an_eplan_write()
        {
            var bin = EplanBin();
            const string src = "var p = ctx.RequireProject();\nforeach (var f in new DMObjectsFinder(p).GetFunctions(null)) { f.SmartLock(); }\nreturn 1;";
            var snippets = EplanEnvironment.DefaultSnippets;
            var refs = ReferenceSet.FromPaths(EplanApiAssemblies.InBin(bin)
                .Concat(new[] { typeof(ScriptArgs).Assembly.Location, EplanHelpers }));
            var compiled = ScriptCompiler.Compile(SourceComposer.Compose(src, "w.cs", snippets), "w.cs",
                Array.Empty<(string, string)>(), refs, "check_write");
            Assert.True(compiled.Success);
            var safety = SafetyAnalyzer.Check(compiled.Compilation!, readOnly: true, allowUnsafe: false);
            Assert.Contains(safety, d => d.Id == "EMCP002");
        }

        [Fact]
        public void Writing_script_may_not_reach_other_projects()
        {
            var bin = EplanBin();
            const string src = "// @writes true\nvar all = new ProjectManager().OpenProjects;\nreturn all.Length;";
            var refs = ReferenceSet.FromPaths(EplanApiAssemblies.InBin(bin)
                .Concat(new[] { typeof(ScriptArgs).Assembly.Location, EplanHelpers }));
            var compiled = ScriptCompiler.Compile(SourceComposer.Compose(src, "p.cs", EplanEnvironment.DefaultSnippets), "p.cs",
                Array.Empty<(string, string)>(), refs, "check_other_projects");
            Assert.True(compiled.Success);
            Assert.Contains(SafetyAnalyzer.Check(compiled.Compilation!, readOnly: false, allowUnsafe: false), d => d.Id == "EMCP004");
            Assert.DoesNotContain(SafetyAnalyzer.Check(compiled.Compilation!, readOnly: true, allowUnsafe: false), d => d.Id == "EMCP004");
        }
    }
}
