using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using EplanMcp.Scripting;
using EplanMcp.Scripting.Core;

// Usage:
//   EplanMcp.ScriptCheck [--bin <EPLAN Bin>] [--helpers <file|dir>]... [--ref <dll>]... <script.cs|dir>...
// Compiles each script with the helpers against the EPLAN API metadata (EPLAN is not started),
// runs the safety check in the mode the script's header asks for, prints every problem as
// "file:line id message", and exits 1 if anything failed.

var bin = Assembly.GetEntryAssembly()!.GetCustomAttributes<AssemblyMetadataAttribute>()
    .FirstOrDefault(a => a.Key == "EplanBinPath")?.Value ?? "";
var helpers = new List<string>();
var refs = new List<string>();
var scripts = new List<string>();
for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--bin": bin = args[++i]; break;
        case "--helpers": helpers.AddRange(Expand(args[++i])); break;
        case "--ref": refs.Add(args[++i]); break;
        default: scripts.AddRange(Expand(args[i]).Where(p => !Path.GetFileName(p).StartsWith("_"))); break;
    }
}
if (!Directory.Exists(bin)) { Console.Error.WriteLine("EPLAN Bin folder not found: " + bin); return 2; }
if (scripts.Count == 0) { Console.Error.WriteLine("No scripts given."); return 2; }

var referenceSet = ReferenceSet.FromPaths(Directory.GetFiles(bin, "Eplan.EplApi.*Netu.dll")
    .Concat(new[] { typeof(ScriptArgs).Assembly.Location, typeof(RunPipeline).Assembly.Location, typeof(EplanMcp.Eplan.Pages).Assembly.Location })
    .Concat(refs));
var helperSources = helpers.Select(h => (path: h, text: File.ReadAllText(h))).ToList();

int failed = 0;
foreach (var script in scripts)
{
    var source = File.ReadAllText(script);
    var headerErrors = new List<string>();
    var manifest = HeaderParser.Parse(source, headerErrors);
    var name = Path.GetFileName(script);
    var composed = SourceComposer.Compose(source, name, EplanEnvironment.DefaultSnippets);
    var compiled = ScriptCompiler.Compile(composed, name, helperSources, referenceSet, "check_" + Path.GetFileNameWithoutExtension(script));
    var problems = headerErrors.Select(e => $"{script}: header {e}").ToList();
    problems.AddRange(compiled.Diagnostics.Where(d => d.Severity == "error")
        .Select(d => $"{d.File}:{d.Line} {d.Id} {d.Message}{(d.Hint != null ? " (" + d.Hint + ")" : "")}"));
    if (compiled.Success)
        problems.AddRange(SafetyAnalyzer.Check(compiled.Compilation!, !manifest.Writes, manifest.Unsafe,
                compiled.Compilation!.SyntaxTrees.Take(1))
            .Select(d => $"{script}:{d.Line} {d.Id} {d.Message}"));
    Console.WriteLine((problems.Count == 0 ? "ok    " : "FAIL  ") + script + $"  ({compiled.ElapsedMs} ms)");
    foreach (var p in problems) Console.WriteLine("      " + p);
    if (problems.Count > 0) failed++;
}
Console.WriteLine($"{scripts.Count - failed}/{scripts.Count} scripts ok");
return failed == 0 ? 0 : 1;

static IEnumerable<string> Expand(string path) =>
    Directory.Exists(path) ? Directory.GetFiles(path, "*.cs").OrderBy(p => p) : new[] { path };
