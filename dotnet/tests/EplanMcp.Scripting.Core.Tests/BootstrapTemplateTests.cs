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

        [Fact]
        public void Filled_template_compiles_with_only_system_and_the_start_attribute()
        {
            var text = File.ReadAllText(TemplatePath())
                .Replace("{{HOST_DIR}}", @"C:\host")
                .Replace("{{REQUEST_PATH}}", @"C:\run\request.json")
                .Replace("{{RESULT_PATH}}", @"C:\run\result.json")
                .Replace("{{MODE}}", "run")
                .Replace("{{CORE_VERSION}}", "0.1.0");
            Assert.DoesNotContain("{{", text);
            const string stub = "namespace Eplan.EplApi.Scripting { public sealed class StartAttribute : System.Attribute { } }";

            var refs = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
                .Select(p => MetadataReference.CreateFromFile(p));
            var comp = CSharpCompilation.Create("bootstrap",
                new[] { CSharpSyntaxTree.ParseText(text), CSharpSyntaxTree.ParseText(stub) }, refs,
                new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
            var errors = comp.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
            Assert.True(errors.Count == 0, string.Join("\n", errors));
        }
    }
}
