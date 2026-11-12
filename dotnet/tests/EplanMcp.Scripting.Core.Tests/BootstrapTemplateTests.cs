using System;
using System.IO;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Xunit;

namespace EplanMcp.Scripting.Core.Tests
{
    /// <summary>
    /// The bootstrap is compiled by EPLAN's own script engine, which we cannot run here. This at
    /// least proves the filled-in template is valid C# that needs nothing beyond System and the
    /// [Start] attribute, so a typo never reaches EPLAN as a silent no-op.
    /// </summary>
    public class BootstrapTemplateTests
    {
        private static string TemplatePath()
        {
            var dir = AppContext.BaseDirectory;
            while (dir != null && !Directory.Exists(Path.Combine(dir, "src", "EplanMcp.Scripting")))
                dir = Path.GetDirectoryName(dir);
            Assert.NotNull(dir);
            return Path.Combine(dir!, "src", "EplanMcp.Scripting", "Bootstrap", "bootstrap.cs.template");
        }

        /// <summary>The runtime's own assemblies: the trusted platform list on .NET 8, the
        /// framework folder on .NET Framework.</summary>
        private static System.Collections.Generic.IEnumerable<MetadataReference> RuntimeReferences()
        {
            var files = AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") is string tpa
                ? tpa.Split(Path.PathSeparator)
                : Directory.GetFiles(Path.GetDirectoryName(typeof(object).Assembly.Location)!, "*.dll");
            foreach (var file in files)
            {
                MetadataReference? reference = null;
                try { System.Reflection.AssemblyName.GetAssemblyName(file); reference = MetadataReference.CreateFromFile(file); }
                catch (BadImageFormatException) { }
                if (reference != null) yield return reference;
            }
        }

        /// <summary>EPLAN 2026's script engine is the .NET Framework one, so the template sticks to C# 5.</summary>
        [Theory]
        [InlineData("run")]
        [InlineData("hello")]
        public void Filled_template_compiles_as_csharp_5_with_only_system_and_the_start_attribute(string mode)
        {
            var text = File.ReadAllText(TemplatePath())
                .Replace("{{HOST_DIR}}", @"C:\host")
                .Replace("{{REQUEST_PATH}}", @"C:\run\request.json")
                .Replace("{{RESULT_PATH}}", @"C:\run\result.json")
                .Replace("{{MODE}}", mode)
                .Replace("{{CORE_VERSION}}", "0.1.0");
            Assert.DoesNotContain("{{", text);
            const string stub = "namespace Eplan.EplApi.Scripting { public sealed class StartAttribute : System.Attribute { } }";

            var csharp5 = new CSharpParseOptions(LanguageVersion.CSharp5);
            var comp = CSharpCompilation.Create("bootstrap",
                new[] { CSharpSyntaxTree.ParseText(text, csharp5), CSharpSyntaxTree.ParseText(stub, csharp5) }, RuntimeReferences(),
                new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
            var errors = comp.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
            Assert.True(errors.Count == 0, string.Join("\n", errors));
        }
    }
}
