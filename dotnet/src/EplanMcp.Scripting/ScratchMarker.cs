using System;
using System.IO;
using System.Text.Json;

namespace EplanMcp.Scripting
{
    /// <summary>
    /// A scratch clone is recognised by a marker file written by <c>scratch_project_create</c> beside
    /// its link file (<c>&lt;name&gt;.elk.eplanmcp-scratch</c>), not by where it sits on disk: a path
    /// rule is easy to defeat with a junction or a misconfigured scratch root. The marker names its own
    /// link file, so a marker copied next to another project does not count. This is a guard against
    /// mistakes, not a security boundary: code running in EPLAN could write a marker itself.
    /// </summary>
    public static class ScratchMarker
    {
        public const string Suffix = ".eplanmcp-scratch";
        public const string Kind = "eplan-mcp-scratch";

        public static string PathFor(string projectLinkFile) => projectLinkFile + Suffix;

        public static bool IsScratch(string? projectLinkFile, out string why)
        {
            why = "";
            if (string.IsNullOrEmpty(projectLinkFile)) { why = "the project has no link file"; return false; }
            var marker = PathFor(projectLinkFile);
            if (!File.Exists(marker)) { why = "no marker file"; return false; }
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(marker));
                var root = doc.RootElement;
                if (!root.TryGetProperty("kind", out var k) || k.GetString() != Kind) { why = "its marker file is not an EplanMcp marker"; return false; }
                if (!root.TryGetProperty("nonce", out var n) || string.IsNullOrWhiteSpace(n.GetString())) { why = "its marker file has no nonce"; return false; }
                if (!root.TryGetProperty("project_link", out var p) || !SamePath(p.GetString(), projectLinkFile))
                {
                    why = "its marker file belongs to a different project";
                    return false;
                }
                return true;
            }
            catch (Exception e)
            {
                why = "its marker file is unreadable (" + e.Message + ")";
                return false;
            }
        }

        /// <summary>The marker already sits beside the link file, so the folder is proven by where it
        /// was found; comparing file names avoids false refusals from mapped-drive vs UNC, 8.3 or
        /// junction spellings of the same folder.</summary>
        private static bool SamePath(string? a, string b)
        {
            if (string.IsNullOrEmpty(a)) return false;
            try { return string.Equals(Path.GetFileName(a), Path.GetFileName(b), StringComparison.OrdinalIgnoreCase); }
            catch { return false; }
        }
    }
}
