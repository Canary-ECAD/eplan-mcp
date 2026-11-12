using System.Collections.Generic;
using System.Linq;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace EplanMcp.Scripting.Core
{
    /// <summary>What a runtime contributes to snippet wrapping.</summary>
    public sealed class SnippetOptions
    {
        public IReadOnlyList<string> Usings { get; set; } = new[] { "System", "System.Linq", "System.Collections.Generic" };

        /// <summary>Fully qualified type of the <c>ctx</c> parameter.</summary>
        public string ContextType { get; set; } = "object";
    }

    /// <summary>
    /// Turns script text into a compilation unit. A full unit (a class with a static <c>Run</c>) is
    /// used as is. Anything else is a snippet: a statement body wrapped into
    /// <c>public static class Script { public static object? Run(ctx) { ... } }</c>, with
    /// <c>#line</c> directives so diagnostics point at the author's own lines.
    /// </summary>
    public static class SourceComposer
    {
        /// <summary>False when the source declares a type with a static <c>Run</c> method. Parsed,
        /// not pattern-matched, so a comment or string that mentions one does not count.</summary>
        public static bool IsSnippet(string source) =>
            !CSharpSyntaxTree.ParseText(source).GetRoot().DescendantNodes().OfType<MethodDeclarationSyntax>()
                .Any(m => m.Identifier.ValueText == "Run" && m.Modifiers.Any(SyntaxKind.StaticKeyword) && m.Parent is TypeDeclarationSyntax);

        public static string Compose(string source, string sourceName, SnippetOptions options)
        {
            if (!IsSnippet(source)) return source;

            // using directives written at the top of a snippet are lifted out of the method body.
            var lines = source.Replace("\r\n", "\n").Split('\n');
            var usings = new List<string>(options.Usings.Select(u => "using " + u + ";"));
            var body = new StringBuilder();
            int firstBodyLine = 1;
            bool inPreamble = true;
            for (int i = 0; i < lines.Length; i++)
            {
                var t = lines[i].Trim();
                if (inPreamble && (t.Length == 0 || t.StartsWith("//") || (t.StartsWith("using ") && t.EndsWith(";") && !t.Contains("("))))
                {
                    if (t.StartsWith("using ")) usings.Add(t);
                    firstBodyLine = i + 2;
                    continue;
                }
                inPreamble = false;
                body.Append(lines[i]).Append('\n');
            }

            var sb = new StringBuilder();
            foreach (var u in usings.Distinct()) sb.Append(u).Append('\n');
            sb.Append("public static class Script\n{\n");
            sb.Append("    public static object? Run(").Append(options.ContextType).Append(" ctx)\n    {\n");
            sb.Append("#line ").Append(firstBodyLine).Append(" \"").Append(sourceName.Replace("\"", "")).Append("\"\n");
            sb.Append(body);
            sb.Append("#line default\n");
            sb.Append("#pragma warning disable CS0162\n        return null;\n#pragma warning restore CS0162\n    }\n}\n");
            return sb.ToString();
        }
    }
}
