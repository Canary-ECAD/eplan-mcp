using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using EplanMcp.Contracts;
using EplanMcp.Scripting.Core;
using Xunit;

namespace EplanMcp.Scripting.Core.Tests
{
    /// <summary>Stand-in for the EPLAN ScriptContext: the pipeline only needs some object to pass.</summary>
    public sealed class TestContext
    {
        public Dictionary<string, object?> Args { get; } = new Dictionary<string, object?>();
        public List<string> Log { get; set; } = new List<string>();
        public Budget Budget { get; set; } = new Budget(5, null);
        public void Write(string s) => Log.Add(s);
    }

    internal sealed class TestEnvironment : IRunEnvironment
    {
        public bool WriteAllowed { get; set; }
        public bool RealProject { get; set; }
        public bool DisposeThrows { get; set; }
        public string Project { get; set; } = "test.elk";
        public string? LastApprovalHash { get; private set; }
        public bool? ContextWriteAllowed { get; private set; }
        public string? VerifyError { get; set; }
        public int WriteSteps { get; private set; }
        public string RuntimeName => "test";
        public SnippetOptions Snippets { get; } = new SnippetOptions
        {
            ContextType = typeof(TestContext).FullName!,
            Usings = new[] { "System", "System.Linq", "System.Collections.Generic", "EplanMcp.Scripting.Core.Tests" },
        };
        public IEnumerable<string> ReferenceSearchDirs => Array.Empty<string>();
        public IRunSession Open(RunRequest request) => new Session(this);

        private sealed class Session : IRunSession
        {
            private readonly TestEnvironment _env;
            public Session(TestEnvironment env) { _env = env; }
            public Preflight Resolve(ScriptManifest manifest) => new Preflight { Project = _env.Project };
            public void Authorize(ScriptManifest manifest, Preflight pre, string approvalHash)
            {
                _env.LastApprovalHash = approvalHash;
                pre.WriteAllowed = _env.WriteAllowed;
                pre.RealProject = _env.WriteAllowed && _env.RealProject;
                pre.Gate = _env.WriteAllowed ? (_env.RealProject ? "real project, confirmed" : "scratch") : "real project";
            }
            public object CreateContext(ScriptManifest m, Preflight p, Budget b, ProgressWriter pr, List<string> log)
            {
                _env.ContextWriteAllowed = p.WriteAllowed;
                return new TestContext { Log = log, Budget = b };
            }
            public string? BeginWrite(string description) { _env.WriteSteps++; return description; }
            public string? Verify() => _env.VerifyError;
            public void Dispose() { if (_env.DisposeThrows) throw new InvalidOperationException("close failed"); }
        }
    }

    public class CoreTests
    {
        private static RunRequest Req(string source, Action<RunRequest>? tweak = null)
        {
            var r = new RunRequest { Protocol = Protocol.Version, RunId = Guid.NewGuid().ToString("N"), Source = source, SourceName = "t.cs" };
            tweak?.Invoke(r);
            return r;
        }

        private static readonly AuditLog Audit = new AuditLog(Path.Combine(Path.GetTempPath(), "eplanmcp-test-audit"));

        [Fact]
        public void Header_parses_tool_args_and_flags()
        {
            var errors = new List<string>();
            var m = HeaderParser.Parse(
                "// @tool  cable_core_links\n// @desc  Map cores.\n// @writes true\n// @needs offline\n" +
                "// @arg project string optional Scratch project path\n// @arg mode enum(read,assign) default=read Mode\n" +
                "// @requires core>=0.1\nusing System;\n// @tool not_a_header_after_code\n", errors);
            Assert.Empty(errors);
            Assert.Equal("cable_core_links", m.Tool);
            Assert.True(m.Writes);
            Assert.Equal("offline", m.Needs);
            Assert.Equal(2, m.Args.Count);
            Assert.Equal(new[] { "read", "assign" }, m.Args[1].Choices);
            Assert.Equal("read", m.Args[1].Default);
            Assert.Equal("Scratch project path", m.Args[0].Description);
        }

        [Fact]
        public void Snippet_runs_and_returns_plain_data()
        {
            var res = RunPipeline.Execute(Req("var xs = new[] { 1, 2, 3 };\nreturn new { sum = xs.Sum() };"), new TestEnvironment(), Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal("done", res.Phase);
            Assert.Equal(6, ((JsonNode)res.Result!)["sum"]!.GetValue<int>());
            Assert.True(res.Unloaded);
        }

        [Fact]
        public void Full_unit_runs()
        {
            const string src = "using EplanMcp.Scripting.Core.Tests;\npublic static class Script {\n  public static object Run(TestContext ctx) { ctx.Write(\"hi\"); return 42; }\n}\n";
            var res = RunPipeline.Execute(Req(src), new TestEnvironment(), Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal(42, ((JsonNode)res.Result!).GetValue<int>());
            Assert.Contains("hi", res.Log);
        }

        [Fact]
        public void Compile_error_maps_to_author_line_with_hint()
        {
            // Line 3 of the snippet, after a header comment and a blank line.
            var res = RunPipeline.Execute(Req("// @desc test\n\nvar s = \"abc\".Lenght;\nreturn s;"), new TestEnvironment(), Audit);
            Assert.False(res.Ok);
            Assert.Equal("compile", res.Phase);
            var d = res.Diagnostics.First(x => x.Severity == "error");
            Assert.Equal("CS1061", d.Id);
            Assert.Equal(3, d.Line);
            Assert.Equal("t.cs", d.File);
            Assert.Contains("Length", d.Hint);
        }

        [Fact]
        public void Runtime_exception_reports_message_and_unloads()
        {
            var res = RunPipeline.Execute(Req("throw new InvalidOperationException(\"boom\");"), new TestEnvironment(), Audit);
            Assert.False(res.Ok);
            Assert.Equal("run", res.Phase);
            Assert.Contains("boom", res.Error);
            Assert.True(res.Unloaded);
        }

        [Fact]
        public void Refusal_is_a_clean_error_result_without_a_stack_trace()
        {
            var res = RunPipeline.Execute(Req("throw new EplanMcp.Scripting.Core.ScriptRefusedException(\"page 'X' not found\");"), new TestEnvironment(), Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal("done", res.Phase);
            Assert.Null(res.Error);
            Assert.Equal("page 'X' not found", ((JsonNode)res.Result!)["error"]!.GetValue<string>());
            Assert.DoesNotContain(" at ", ((JsonNode)res.Result!).ToJsonString());
            Assert.True(res.Unloaded);
        }

        [Fact]
        public void Unbounded_loop_without_budget_check_is_rejected()
        {
            var res = RunPipeline.Execute(Req("while (true) { }"), new TestEnvironment(), Audit);
            Assert.False(res.Ok);
            Assert.Contains(res.Diagnostics, d => d.Id == "EMCP003");
        }

        [Fact]
        public void Budget_stops_a_long_loop()
        {
            var res = RunPipeline.Execute(Req("while (true) { ctx.Budget.Check(); }", r => r.BudgetSeconds = 0.3), new TestEnvironment(), Audit);
            Assert.False(res.Ok);
            Assert.Contains("budget", res.Error);
            Assert.True(res.Unloaded);
        }

        [Fact]
        public void Denied_api_is_rejected_unless_unsafe()
        {
            var bad = RunPipeline.Execute(Req("System.IO.File.Delete(\"x\"); return 1;"), new TestEnvironment(), Audit);
            Assert.Contains(bad.Diagnostics, d => d.Id == "EMCP001");
            // @unsafe counts in a saved library script only.
            var ok = RunPipeline.Execute(Req("// @unsafe\nSystem.IO.File.Delete(\"eplanmcp-no-such-file\"); return 1;", r => r.ScriptPath = "lib/x.cs"), new TestEnvironment(), Audit);
            Assert.True(ok.Ok, ok.Error);
        }

        [Fact]
        public void Unsafe_header_is_ignored_in_ad_hoc_code_even_after_a_saved_script_compiled_it()
        {
            const string src = "// @unsafe\nSystem.IO.File.Delete(\"eplanmcp-no-such-file-2\"); return 2;";
            var saved = RunPipeline.Execute(Req(src, r => r.ScriptPath = "lib/y.cs"), new TestEnvironment(), Audit);
            Assert.True(saved.Ok, saved.Error);
            var adHoc = RunPipeline.Execute(Req(src), new TestEnvironment(), Audit);   // same source: must not reuse the cached image
            Assert.False(adHoc.Ok);
            Assert.Contains(adHoc.Diagnostics, d => d.Id == "EMCP001");
            Assert.Contains(adHoc.Warnings, w => w.Contains("@unsafe"));
        }

        [Fact]
        public void Approval_hash_covers_project_and_dry_run()
        {
            var a = Approval.Hash("src", new string[0], "{}", @"C:\p\a.elk", false);
            Assert.NotEqual(a, Approval.Hash("src", new string[0], "{}", @"C:\p\b.elk", false));
            Assert.NotEqual(a, Approval.Hash("src", new string[0], "{}", @"C:\p\a.elk", true));
            Assert.Equal(a, Approval.Hash("src", new string[0], "{}", @"c:\P\A.elk", false));   // one spelling per path
        }

        [Fact]
        public void Approval_hash_is_computed_for_the_resolved_project()
        {
            var env = new TestEnvironment { Project = @"C:\scratch\resolved.elk" };
            var res = RunPipeline.Execute(Req("return 1;", r => { r.CompileOnly = true; r.DryRun = true; }), env, Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal(Approval.Hash("return 1;", new string[0], null, @"C:\scratch\resolved.elk", true), res.ApprovalHash);
            Assert.Equal(env.LastApprovalHash, res.ApprovalHash);
        }

        [Fact]
        public void Failed_audit_refuses_a_real_project_write_but_not_a_scratch_run()
        {
            var blocker = Path.Combine(Path.GetTempPath(), "eplanmcp-audit-blocker-" + Guid.NewGuid().ToString("N"));
            File.WriteAllText(blocker, "a file where the audit folder should be");
            var broken = new AuditLog(Path.Combine(blocker, "audit"));

            var real = new TestEnvironment { WriteAllowed = true, RealProject = true };
            var refused = RunPipeline.Execute(Req("// @writes true\nreturn 1;"), real, broken);
            Assert.False(refused.Ok);
            Assert.Equal("guard", refused.Phase);
            Assert.False(refused.AuditOk);
            Assert.Equal(0, real.WriteSteps);

            var preview = RunPipeline.Execute(Req("// @writes true\nreturn 1;", r => r.DryRun = true), new TestEnvironment { WriteAllowed = true, RealProject = true }, broken);
            Assert.True(preview.Ok, preview.Error);

            var scratch = RunPipeline.Execute(Req("// @writes true\nreturn 1;"), new TestEnvironment { WriteAllowed = true }, broken);
            Assert.True(scratch.Ok, scratch.Error);
            Assert.False(scratch.AuditOk);
            Assert.Contains(scratch.Warnings, w => w.Contains("audit"));
        }

        [Fact]
        public void Audit_start_records_the_final_write_decision()
        {
            var dir = Path.Combine(Path.GetTempPath(), "eplanmcp-audit-" + Guid.NewGuid().ToString("N"));
            // The gate is open (scratch) but the script does not declare writes: it runs read-only.
            var res = RunPipeline.Execute(Req("return 1;"), new TestEnvironment { WriteAllowed = true }, new AuditLog(dir));
            Assert.True(res.Ok, res.Error);
            Assert.True(res.AuditOk);
            var start = File.ReadAllLines(Directory.GetFiles(dir, "*.jsonl").Single()).Single(l => l.Contains("\"event\":\"start\""));
            Assert.Contains("\"write_allowed\":false", start);
        }

        [Fact]
        public void A_failure_closing_the_session_after_the_run_is_a_warning_not_a_host_error()
        {
            var res = RunPipeline.Execute(Req("// @writes true\nreturn 5;"), new TestEnvironment { WriteAllowed = true, DisposeThrows = true }, Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal(5, ((JsonNode)res.Result!).GetValue<int>());
            Assert.NotNull(res.UndoDescription);
            Assert.Contains(res.Warnings, w => w.Contains("close failed"));
        }

        [Fact]
        public void Dynamic_is_rejected()
        {
            var res = RunPipeline.Execute(Req("dynamic d = \"abc\";\nreturn d.Length;"), new TestEnvironment(), Audit);
            Assert.Contains(res.Diagnostics, d => d.Id == "EMCP005");
            var cast = RunPipeline.Execute(Req("object o = \"abc\";\nvar n = ((dynamic)o).Length;\nreturn 1;"), new TestEnvironment(), Audit);
            Assert.Contains(cast.Diagnostics, d => d.Id == "EMCP005");
        }

        [Fact]
        public void Denied_member_is_found_through_a_derived_type()
        {
            const string src = "public class P : System.Diagnostics.Process { public new bool Start() => false; }\n" +
                               "public static class Script { public static object Run(EplanMcp.Scripting.Core.Tests.TestContext ctx) => new P().Start(); }\n";
            var res = RunPipeline.Execute(Req(src), new TestEnvironment(), Audit);
            Assert.Contains(res.Diagnostics, d => d.Id == "EMCP001");
        }

        [Fact]
        public void Comments_and_strings_do_not_make_a_snippet_a_full_unit()
        {
            Assert.True(SourceComposer.IsSnippet("// public static class X { public static object Run(object ctx) { } }\nreturn 1;"));
            Assert.True(SourceComposer.IsSnippet("var s = \"class X { static object Run(\";\nreturn s;"));
            Assert.True(SourceComposer.IsSnippet("/* class X { static void Run( */ return 1;"));
            Assert.False(SourceComposer.IsSnippet("public static class Script { public static object Run(object ctx) => 1; }"));
            var res = RunPipeline.Execute(Req("// see class Script { static object Run( }\nreturn 3;"), new TestEnvironment(), Audit);
            Assert.True(res.Ok, res.Error);
        }

        [Fact]
        public void Output_path_stays_in_the_run_folder_for_a_run_that_may_not_write()
        {
            var run = Path.Combine(Path.GetTempPath(), "eplanmcp-run");
            Assert.Equal(Path.Combine(run, "a.json"), OutputPath.Resolve(run, false, null, "a.json"));
            Assert.Equal(Path.Combine(run, "sub", "b.json"), OutputPath.Resolve(run, false, Path.Combine("sub", "b.json"), "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, false, Path.Combine(Path.GetTempPath(), "elsewhere.json"), "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, false, Path.Combine("..", "up.json"), "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, false, run + "10" + Path.DirectorySeparatorChar + "x.json", "a.json"));
        }

        [Fact]
        public void Output_path_of_a_writing_run_never_lands_in_eplan_data()
        {
            var run = Path.Combine(Path.GetTempPath(), "eplanmcp-run");
            var elsewhere = Path.Combine(Path.GetTempPath(), "out", "report.json");
            Assert.Equal(elsewhere, OutputPath.Resolve(run, true, elsewhere, "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, true, Path.Combine(Path.GetTempPath(), "p.edb", "x.json"), "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, true, Path.Combine(Path.GetTempPath(), "p.elk"), "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, true, Path.Combine(Path.GetTempPath(), "lib.SLK"), "a.json"));
            Assert.Throws<ScriptRefusedException>(() => OutputPath.Resolve(run, true, Path.Combine(Path.GetTempPath(), "x.sdb"), "a.json"));
        }

        [Fact]
        public void Reference_set_is_reused_while_nothing_new_is_loaded()
        {
            var a = ReferenceSet.FromCurrentProcess();
            var b = ReferenceSet.FromCurrentProcess();
            Assert.Same(a, b);
        }

        [Fact]
        public void Unload_wait_has_a_bounded_budget()
        {
            var alive = new object();
            var sw = System.Diagnostics.Stopwatch.StartNew();
            Assert.False(ScriptRunner.WaitForUnload(new WeakReference(alive)));
            Assert.InRange(sw.ElapsedMilliseconds, 500, 5000);   // about a second of retries, not forever
            GC.KeepAlive(alive);
        }

        [Fact]
        public void Writes_script_refused_when_gate_is_closed()
        {
            var res = RunPipeline.Execute(Req("// @writes true\nreturn 1;"), new TestEnvironment { WriteAllowed = false }, Audit);
            Assert.False(res.Ok);
            Assert.Equal("guard", res.Phase);
        }

        [Fact]
        public void Writes_script_opens_an_undo_step_when_allowed()
        {
            var env = new TestEnvironment { WriteAllowed = true };
            var res = RunPipeline.Execute(Req("// @writes true\nreturn 1;"), env, Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal(1, env.WriteSteps);
            Assert.NotNull(res.UndoDescription);
        }

        [Fact]
        public void Compile_only_of_a_writing_script_returns_the_approval_hash_even_when_the_gate_is_closed()
        {
            var res = RunPipeline.Execute(Req("// @writes true\nreturn 1;", r => r.CompileOnly = true), new TestEnvironment { WriteAllowed = false }, Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Equal(64, res.ApprovalHash!.Length);
        }

        [Fact]
        public void Approval_hash_covers_args_and_helpers()
        {
            var a = Approval.Hash("src", new string[0], "{\"x\":1}", "p.elk", false);
            Assert.NotEqual(a, Approval.Hash("src", new string[0], "{\"x\":2}", "p.elk", false));
            Assert.NotEqual(a, Approval.Hash("src", new[] { "helper" }, "{\"x\":1}", "p.elk", false));
            var env = new TestEnvironment();
            var res = RunPipeline.Execute(Req("return ctx.Args.Count;", r => { r.ArgsCanonical = "{\"x\":1}"; r.Args = new Dictionary<string, object?>(); }), env, Audit);
            Assert.Equal(env.LastApprovalHash, res.ApprovalHash);
        }

        [Fact]
        public void Script_without_writes_header_gets_a_read_only_context_on_a_scratch_clone()
        {
            var env = new TestEnvironment { WriteAllowed = true };
            var res = RunPipeline.Execute(Req("return 1;"), env, Audit);
            Assert.True(res.Ok, res.Error);
            Assert.False(env.ContextWriteAllowed);
        }

        [Fact]
        public void Helper_libraries_are_not_safety_checked_but_the_script_is()
        {
            var dir = Path.Combine(Path.GetTempPath(), "eplanmcp-helper-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            var helper = Path.Combine(dir, "Lib.cs");
            File.WriteAllText(helper, "public static class Lib { public static int Spin() { while (true) { } } }");
            var ok = RunPipeline.Execute(Req("return 1;", r => r.HelperSources.Add(helper)), new TestEnvironment(), Audit);
            Assert.True(ok.Ok, ok.Error);
            var bad = RunPipeline.Execute(Req("while (true) { }", r => r.HelperSources.Add(helper)), new TestEnvironment(), Audit);
            Assert.Contains(bad.Diagnostics, d => d.Id == "EMCP003");
        }

        [Fact]
        public void Verify_failure_fails_the_run()
        {
            var res = RunPipeline.Execute(Req("return 1;"), new TestEnvironment { VerifyError = "project set changed" }, Audit);
            Assert.False(res.Ok);
            Assert.Equal("guard", res.Phase);
        }

        [Fact]
        public void Compile_only_does_not_run()
        {
            var res = RunPipeline.Execute(Req("throw new Exception(\"must not run\");", r => r.CompileOnly = true), new TestEnvironment(), Audit);
            Assert.True(res.Ok, res.Error);
            Assert.Null(res.Result);
        }

        [Fact]
        public void Protocol_mismatch_is_refused_plainly()
        {
            var res = RunPipeline.Execute(Req("return 1;", r => r.Protocol = 99), new TestEnvironment(), Audit);
            Assert.False(res.Ok);
            Assert.Contains("Protocol 99", res.Error);
        }

        [Fact]
        public void Requires_newer_core_is_refused()
        {
            var res = RunPipeline.Execute(Req("// @requires core>=99.0\nreturn 1;"), new TestEnvironment(), Audit);
            Assert.False(res.Ok);
            Assert.Contains("99.0", res.Error);
        }

        [Fact]
        public void Large_result_goes_to_a_file()
        {
            var folder = Path.Combine(Path.GetTempPath(), "eplanmcp-test-" + Guid.NewGuid().ToString("N"));
            var res = RunPipeline.Execute(Req("return new string('x', 50000);", r => r.RunFolder = folder), new TestEnvironment(), Audit);
            Assert.True(res.Ok, res.Error);
            Assert.True(res.Truncated);
            Assert.True(File.Exists(res.ResultFile));
        }

        [Fact]
        public void Audit_records_start_and_end()
        {
            var dir = Path.Combine(Path.GetTempPath(), "eplanmcp-audit-" + Guid.NewGuid().ToString("N"));
            var req = Req("return 1;");
            RunPipeline.Execute(req, new TestEnvironment(), new AuditLog(dir));
            var lines = File.ReadAllLines(Directory.GetFiles(dir, "*.jsonl").Single());
            Assert.Contains(lines, l => l.Contains("\"event\":\"start\"") && l.Contains(req.RunId));
            Assert.Contains(lines, l => l.Contains("\"event\":\"end\"") && l.Contains(req.RunId));
            Assert.Single(Directory.GetFiles(Path.Combine(dir, "sources")));
        }

        [Fact]
        public void Second_run_of_same_source_hits_the_cache_and_still_unloads()
        {
            var env = new TestEnvironment();
            var a = RunPipeline.Execute(Req("return 7;"), env, Audit);
            var b = RunPipeline.Execute(Req("return 7;"), env, Audit);
            Assert.True(a.Ok && b.Ok);
            Assert.Empty(b.Diagnostics);
            Assert.True(b.Unloaded);
        }
    }
}
