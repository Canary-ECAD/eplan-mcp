using System;
using System.IO;
using System.Linq;
using EplanMcp.Scripting.Core;
using Xunit;

namespace EplanMcp.Scripting.Core.Tests
{
    public class EplanApiAssembliesTests
    {
        private static string Bin(params string[] files)
        {
            var dir = Path.Combine(Path.GetTempPath(), "eplanbin-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            foreach (var f in files) File.WriteAllText(Path.Combine(dir, f), "");
            return dir;
        }

        private static string[] Names(string bin) =>
            EplanApiAssemblies.InBin(bin).Select(Path.GetFileName).OrderBy(n => n).ToArray()!;

        [Fact]
        public void Eplan_2027_uses_only_the_Netu_set_never_the_native_twins()
        {
            var bin = Bin("Eplan.EplApi.BaseNetu.dll", "Eplan.EplApi.DataModelNetu.dll",
                          "Eplan.EplApi.Baseu.dll", "Eplan.EplApi.DataModelu.dll");
            Assert.True(EplanApiAssemblies.UsesNetNames(bin));
            Assert.Equal(new[] { "Eplan.EplApi.BaseNetu.dll", "Eplan.EplApi.DataModelNetu.dll" }, Names(bin));
        }

        [Fact]
        public void Eplan_2026_uses_the_u_set()
        {
            var bin = Bin("Eplan.EplApi.Baseu.dll", "Eplan.EplApi.DataModelu.dll", "Eplan.EplApi.RemoteClientu.dll", "Other.dll");
            Assert.False(EplanApiAssemblies.UsesNetNames(bin));
            Assert.Equal(new[] { "Eplan.EplApi.Baseu.dll", "Eplan.EplApi.DataModelu.dll", "Eplan.EplApi.RemoteClientu.dll" }, Names(bin));
        }

        [Fact]
        public void Missing_folder_is_empty()
        {
            Assert.Empty(EplanApiAssemblies.InBin(Path.Combine(Path.GetTempPath(), "no-such-" + Guid.NewGuid().ToString("N"))));
        }

        [Theory]
        [InlineData("Eplan.EplApi.BaseNetu", true)]
        [InlineData("Eplan.EplApi.Baseu", true)]
        [InlineData("Eplan.EplApi.BaseNet", false)]
        [InlineData("Eplan.EplApi.DataModelNetu", false)]
        [InlineData(null, false)]
        public void IsModule_matches_both_schemes(string? name, bool expected)
        {
            Assert.Equal(expected, EplanApiAssemblies.IsModule(name, "Base"));
        }
    }
}
