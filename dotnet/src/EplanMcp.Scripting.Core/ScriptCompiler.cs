using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Emit;
using Microsoft.CodeAnalysis.Text;
using Diag = EplanMcp.Contracts.Diagnostic;

namespace EplanMcp.Scripting.Core
{
    public sealed class CompileOutput
    {
        public bool Success { get; set; }
        public byte[]? Assembly { get; set; }
        public List<Diag> Diagnostics { get; } = new List<Diag>();
        public CSharpCompilation? Compilation { get; set; }
        public long ElapsedMs { get; set; }
    }

    /// <summary>
    /// Compiles one script (plus helper sources) to an in-memory assembly with an embedded PDB, so
    /// run-time exceptions carry the author's line numbers. Error diagnostics get "did you mean"
    /// hints drawn from the referenced assemblies.
    /// </summary>
    public static class ScriptCompiler
    {
        private const int MaxWarnings = 20;

        /// <summary>The symbols MSBuild would define for the framework the script runs on, so one
        /// script can serve EPLAN 2027 (.NET 8) and EPLAN 2026 (.NET Framework) with #if.</summary>
        public static readonly string[] PreprocessorSymbols =
#if NETFRAMEWORK
            { "NETFRAMEWORK", "NET481" };
#else
            { "NET", "NET8_0", "NET8_0_OR_GREATER" };
#endif

        public static CompileOutput Compile(string composedSource, string sourceName,
            IEnumerable<(string path, string text)> helpers, ReferenceSet refs, string assemblyName)
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            var parse = new CSharpParseOptions(LanguageVersion.Latest, preprocessorSymbols: PreprocessorSymbols);
            var trees = new List<SyntaxTree>
            {
                CSharpSyntaxTree.ParseText(SourceText.From(composedSource, Encoding.UTF8), parse, sourceName),
            };
            trees.AddRange(helpers.Select(h => CSharpSyntaxTree.ParseText(SourceText.From(h.text, Encoding.UTF8), parse, h.path)));

            var options = new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary,
                optimizationLevel: OptimizationLevel.Debug,
                nullableContextOptions: NullableContextOptions.Annotations,   // "?" allowed, no nullable warnings
                allowUnsafe: false,
                platform: Platform.AnyCpu);
            var compilation = CSharpCompilation.Create(assemblyName, trees, refs.References, options);

            var output = new CompileOutput { Compilation = compilation };
            using var pe = new MemoryStream();
            var emit = compilation.Emit(pe, options: new EmitOptions(debugInformationFormat: DebugInformationFormat.Embedded));
            output.Success = emit.Success;
            if (emit.Success) output.Assembly = pe.ToArray();

            int warnings = 0;
            foreach (var d in emit.Diagnostics.OrderBy(d => d.Severity == DiagnosticSeverity.Error ? 0 : 1))
            {
                if (d.Severity == DiagnosticSeverity.Hidden || d.Severity == DiagnosticSeverity.Info) continue;
                if (d.Severity == DiagnosticSeverity.Warning && ++warnings > MaxWarnings) continue;
                var diag = ToDiag(d);
                if (d.Severity == DiagnosticSeverity.Error) diag.Hint = Hints.For(d, compilation);
                output.Diagnostics.Add(diag);
            }
            output.ElapsedMs = sw.ElapsedMilliseconds;
            return output;
        }

        internal static Diag ToDiag(Microsoft.CodeAnalysis.Diagnostic d)
        {
            var span = d.Location.GetMappedLineSpan();
            string? snippet = null;
            if (d.Location.IsInSource)
            {
                var text = d.Location.SourceTree!.GetText();
                var line = d.Location.GetLineSpan().StartLinePosition.Line;
                if (line >= 0 && line < text.Lines.Count) snippet = text.Lines[line].ToString().Trim();
            }
            return new Diag
            {
                Id = d.Id,
                Severity = d.Severity == DiagnosticSeverity.Error ? "error" : "warning",
                File = span.Path ?? "",
                Line = span.IsValid ? span.StartLinePosition.Line + 1 : 0,
                Col = span.IsValid ? span.StartLinePosition.Character + 1 : 0,
                Message = d.GetMessage(),
                Snippet = snippet,
            };
        }
    }

    /// <summary>Spelling suggestions for unknown types and members.</summary>
    internal static class Hints
    {
        public static string? For(Microsoft.CodeAnalysis.Diagnostic d, CSharpCompilation c)
        {
            try
            {
                switch (d.Id)
                {
                    case "CS1061": // 'T' does not contain a definition for 'M'
                    case "CS0117":
                        return MemberHint(d, c);
                    case "CS0246": // type or namespace 'X' could not be found
                    case "CS0103": // name 'X' does not exist
                        return TypeHint(d, c);
                    case "CS0234": // 'X' does not exist in namespace 'N'
                        return TypeHint(d, c, "Check the namespace; the EPLAN API types live under Eplan.EplApi.*.");
                }
            }
            catch { }
            return null;
        }

        private static string? MemberHint(Microsoft.CodeAnalysis.Diagnostic d, CSharpCompilation c)
        {
            if (!d.Location.IsInSource) return null;
            var tree = d.Location.SourceTree!;
            var node = tree.GetRoot().FindNode(d.Location.SourceSpan);
            var access = node.FirstAncestorOrSelf<Microsoft.CodeAnalysis.CSharp.Syntax.MemberAccessExpressionSyntax>();
            if (access == null) return null;
            var model = c.GetSemanticModel(tree);
            var type = model.GetTypeInfo(access.Expression).Type;
            if (type == null) return null;
            var wanted = access.Name.Identifier.ValueText;
            var names = AllMembers(type).Where(m => m.DeclaredAccessibility == Accessibility.Public && m.CanBeReferencedByName)
                .Select(m => m.Name).Distinct();
            var best = Closest(wanted, names, 3);
            return best.Count == 0 ? null : "Did you mean: " + string.Join(", ", best) + " (on " + type.ToDisplayString() + ")";
        }

        private static IEnumerable<ISymbol> AllMembers(ITypeSymbol t)
        {
            for (var cur = t; cur != null; cur = cur.BaseType)
                foreach (var m in cur.GetMembers()) yield return m;
            foreach (var i in t.AllInterfaces)
                foreach (var m in i.GetMembers()) yield return m;
        }

        private static string? TypeHint(Microsoft.CodeAnalysis.Diagnostic d, CSharpCompilation c, string? extra = null)
        {
            if (!d.Location.IsInSource) return extra;
            var wanted = d.Location.SourceTree!.GetText().ToString(d.Location.SourceSpan);
            wanted = wanted.Split('.').Last().Split('<')[0].Trim();
            if (wanted.Length < 2) return extra;
            var candidates = new List<string>();
            CollectTypes(c.GlobalNamespace, candidates, 0);
            var best = Closest(wanted, candidates.Select(n => n.Split('.').Last()).Distinct(), 3);
            if (best.Count == 0) return extra;
            var full = best.Select(b => candidates.First(n => n.EndsWith("." + b, StringComparison.Ordinal) || n == b));
            return "Did you mean: " + string.Join(", ", full) + (extra != null ? ". " + extra : "");
        }

        private static void CollectTypes(INamespaceSymbol ns, List<string> into, int depth)
        {
            if (depth > 8 || into.Count > 20000) return;
            foreach (var t in ns.GetTypeMembers())
                if (t.DeclaredAccessibility == Accessibility.Public) into.Add(t.ToDisplayString());
            foreach (var child in ns.GetNamespaceMembers())
            {
                var n = child.ToDisplayString();
                // Keep the search to the API surface a script plausibly means.
                if (depth == 0 && !(n == "Eplan" || n == "System" || n == "EplanMcp")) continue;
                CollectTypes(child, into, depth + 1);
            }
        }

        internal static List<string> Closest(string wanted, IEnumerable<string> names, int take)
        {
            var w = wanted.ToLowerInvariant();
            return names
                .Select(n => (n, score: Score(w, n.ToLowerInvariant())))
                .Where(x => x.score <= Math.Max(2, w.Length / 3) || x.n.ToLowerInvariant().Contains(w))
                .OrderBy(x => x.score).ThenBy(x => x.n.Length)
                .Take(take).Select(x => x.n).ToList();
        }

        private static int Score(string a, string b)
        {
            var d = new int[a.Length + 1, b.Length + 1];
            for (int i = 0; i <= a.Length; i++) d[i, 0] = i;
            for (int j = 0; j <= b.Length; j++) d[0, j] = j;
            for (int i = 1; i <= a.Length; i++)
                for (int j = 1; j <= b.Length; j++)
                    d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1), d[i - 1, j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1));
            return d[a.Length, b.Length];
        }
    }
}
