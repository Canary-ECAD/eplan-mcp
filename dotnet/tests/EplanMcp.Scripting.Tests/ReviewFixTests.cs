using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using EplanMcp.Contracts;
using EplanMcp.Eplan;
using EplanMcp.Scripting;
using EplanMcp.Scripting.Core;
using Xunit;

namespace EplanMcp.Scripting.Tests
{
    /// <summary>The EPLAN-side rules: analyzer checks that need the EPLAN API metadata, the write
    /// gate, project matching and the helper library's pure parts. EPLAN is never started.</summary>
    public class ReviewFixTests
    {
        private static string EplanBin() =>
            typeof(ReviewFixTests).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().First(a => a.Key == "EplanBinPath").Value!;

        private static Microsoft.CodeAnalysis.CSharp.CSharpCompilation Compile(string src, string name)
        {
            var refs = ReferenceSet.FromPaths(EplanApiAssemblies.InBin(EplanBin())
                .Concat(new[] { typeof(ScriptArgs).Assembly.Location, typeof(Pages).Assembly.Location }));
            var compiled = ScriptCompiler.Compile(SourceComposer.Compose(src, name + ".cs", EplanEnvironment.DefaultSnippets), name + ".cs",
                Array.Empty<(string, string)>(), refs, "check_" + name);
            Assert.True(compiled.Success, string.Join("\n", compiled.Diagnostics.Where(d => d.Severity == "error").Select(d => d.Id + " " + d.Message)));
            return compiled.Compilation!;
        }

        [Fact]
        public void Increment_of_an_eplan_property_is_a_write()
        {
            var c = Compile("var p = ctx.RequireProject();\nforeach (var b in new DMObjectsFinder(p).GetPlacements(null).OfType<MacroBox>()) b.Variant++;\nreturn 1;", "inc");
            Assert.Contains(SafetyAnalyzer.Check(c, readOnly: true, allowUnsafe: false), d => d.Id == "EMCP002");
            Assert.DoesNotContain(SafetyAnalyzer.Check(c, readOnly: false, allowUnsafe: false), d => d.Id == "EMCP002");
        }

        [Fact]
        public void Writing_script_may_not_run_actions_by_name()
        {
            var c = Compile("// @writes true\nnew Eplan.EplApi.ApplicationFramework.CommandLineInterpreter().Execute(\"XPrjActionProjectClose\");\nreturn 1;", "cli");
            Assert.Contains(SafetyAnalyzer.Check(c, readOnly: false, allowUnsafe: false), d => d.Id == "EMCP004");
            Assert.DoesNotContain(SafetyAnalyzer.Check(c, readOnly: false, allowUnsafe: true), d => d.Id == "EMCP004");
        }

        /// <summary>ScriptContext.Lock compares an object's project with ctx.Project through this member.</summary>
        [Fact]
        public void StorableObject_Project_is_the_owning_project()
        {
            Compile("Project? owner = ((StorableObject)ctx.RequireProject().Pages[0]).Project;\nreturn owner?.ProjectLinkFilePath;", "owner");
        }

        [Fact]
        public void Real_project_write_needs_canonical_arguments()
        {
            const string hash = "0123456789abcdef0123456789abcdef";
            RunRequest Req(string? canonical) => new RunRequest
            {
                AllowRealProject = true, ScriptPath = "lib/x.cs", Confirm = hash.Substring(0, 16), ArgsCanonical = canonical,
            };
            var link = Path.Combine(Path.GetTempPath(), "eplanmcp-not-scratch-" + Guid.NewGuid().ToString("N") + ".elk");

            var without = new Preflight();
            WriteGate.Decide(without, link, Req(null), hash);
            Assert.False(without.WriteAllowed);
            Assert.Contains("args_canonical", without.Gate);

            var with = new Preflight();
            WriteGate.Decide(with, link, Req("{}"), hash);
            Assert.True(with.WriteAllowed);
            Assert.True(with.RealProject);
        }

        [Fact]
        public void Project_matching_prefers_exact_and_full_name_and_refuses_ties()
        {
            var open = new List<string[]>
            {
                new[] { @"C:\p\Alpha.elk", @"C:\p\Alpha", "Alpha", "Alpha" },
                new[] { @"C:\q\alpha.elk", @"C:\q\alpha", "alpha", "alpha" },
                new[] { @"C:\r\Beta.elk", @"C:\r\Beta", "Beta", "Beta" },
            };
            Assert.Equal(1, ProjectResolver.Pick(open, @"C:\q\alpha", out _));          // ProjectFullName
            Assert.Equal(0, ProjectResolver.Pick(open, @"c:\P\ALPHA.ELK", out _));      // link path, any case
            Assert.Equal(0, ProjectResolver.Pick(open, "Alpha", out _));                // exact case wins
            Assert.Equal(2, ProjectResolver.Pick(open, "beta", out _));
            Assert.Equal(-1, ProjectResolver.Pick(open, "ALPHA", out var tie));         // two case-insensitive hits
            Assert.NotNull(tie);
            Assert.Equal(-1, ProjectResolver.Pick(open, "Gamma", out var none));
            Assert.Null(none);
        }

        [Fact]
        public void Plain_text_strips_the_no_language_form_only()
        {
            Assert.Equal("Hello", Safe.PlainText("??_??@Hello;"));
            Assert.Equal("Hallo", Safe.PlainText("de_DE@Hallo;"));
            Assert.Equal("a;b", Safe.PlainText("??_??@a;b;"));
            Assert.Equal("ends with;", Safe.PlainText("ends with;"));
            Assert.Equal("de_DE@a;en_US@b;", Safe.PlainText("de_DE@a;en_US@b;"));   // several languages stay
            Assert.Equal("", Safe.PlainText(null));
        }

        [Fact]
        public void Record_argument_given_but_empty_is_an_error()
        {
            ScriptArgs Args(string json) => new ScriptArgs(Json.Deserialize<Dictionary<string, object?>>(json));
            Assert.Single(PlainJson.RequireRows(Args("{\"moves\":[{\"name\":\"K1\"}]}"), "moves"));
            Assert.Single(PlainJson.RequireRows(Args("{\"moves\":\"[{\\\"name\\\":\\\"K1\\\"}]\"}"), "moves"));   // JSON sent as text
            Assert.Throws<ScriptRefusedException>(() => PlainJson.RequireRows(Args("{\"moves\":[]}"), "moves"));
            Assert.Throws<ScriptRefusedException>(() => PlainJson.RequireRows(Args("{\"moves\":\"K1\"}"), "moves"));
            Assert.Throws<ScriptRefusedException>(() => PlainJson.RequireRows(Args("{}"), "moves"));
            // rows given but empty: an error, never a silent fall back to from_file
            var file = Path.GetTempFileName();
            File.WriteAllText(file, "[{\"page\":\"1\"}]");
            Assert.Throws<ScriptRefusedException>(() => PlainJson.RowsFromArgs(Args("{\"rows\":[1,2],\"from_file\":" + Json.Serialize(file) + "}"), "rows", "from_file"));
            Assert.Single(PlainJson.RowsFromArgs(Args("{\"from_file\":" + Json.Serialize(file) + "}"), "rows", "from_file"));
        }

        [Fact]
        public void Queue_file_result_path_is_recovered_from_broken_json()
        {
            Assert.Equal(@"C:\runs\r1\result.json", OfflineHost.RecoverResultPath("{\"request\": \"C:\\\\runs\\\\r1\\\\req.json\", \"result\": \"C:\\\\runs\\\\r1\\\\result.json\", oops"));
            Assert.Null(OfflineHost.RecoverResultPath("not json at all"));
        }
    }
}
