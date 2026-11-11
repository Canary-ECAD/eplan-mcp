using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using EplanMcp.Contracts;

namespace EplanMcp.Scripting.Core
{
    /// <summary>
    /// Reads the <c>// @key value</c> lines at the top of a script. Parsing stops at the first line
    /// that is neither blank nor a <c>//</c> comment, so a <c>@</c> inside code is never a header.
    /// </summary>
    public static class HeaderParser
    {
        public static ScriptManifest Parse(string source, List<string>? errors = null)
        {
            var m = new ScriptManifest();
            foreach (var raw in (source ?? "").Split('\n'))
            {
                var line = raw.Trim();
                if (line.Length == 0) continue;
                if (!line.StartsWith("//", StringComparison.Ordinal)) break;
                var body = line.Substring(2).Trim();
                if (!body.StartsWith("@", StringComparison.Ordinal)) continue;

                int space = IndexOfWhite(body);
                string key = (space < 0 ? body.Substring(1) : body.Substring(1, space - 1)).ToLowerInvariant();
                string value = space < 0 ? "" : body.Substring(space).Trim();
                switch (key)
                {
                    case "tool": m.Tool = FirstWord(value); break;
                    case "desc": m.Desc = Append(m.Desc, value); break;
                    case "schema":
                        if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var s)) m.Schema = s;
                        else errors?.Add("@schema is not a number: " + value);
                        break;
                    case "requires": m.Requires = value; break;
                    case "writes": m.Writes = ParseBool(FirstWord(value)); break;
                    case "unsafe": m.Unsafe = value.Length == 0 || ParseBool(FirstWord(value)); break;
                    case "needs":
                        var needs = FirstWord(value).ToLowerInvariant();
                        if (needs is "session" or "offline" or "either" or "gui") m.Needs = needs;
                        else errors?.Add("@needs must be session, offline, either or gui: " + value);
                        break;
                    case "arg":
                        var arg = ParseArg(value, errors);
                        if (arg != null) m.Args.Add(arg);
                        break;
                    default:
                        errors?.Add("Unknown header @" + key);
                        break;
                }
            }
            return m;
        }

        /// <summary><c>name type [optional|required] [default=x] description...</c>; type may be
        /// <c>enum(a,b,c)</c>.</summary>
        internal static ScriptArg? ParseArg(string value, List<string>? errors)
        {
            var words = value.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries).ToList();
            if (words.Count < 2) { errors?.Add("@arg needs at least a name and a type: " + value); return null; }
            var arg = new ScriptArg { Name = words[0] };
            var type = words[1];
            if (type.StartsWith("enum(", StringComparison.OrdinalIgnoreCase) && type.EndsWith(")", StringComparison.Ordinal))
            {
                arg.Type = "enum";
                arg.Choices = type.Substring(5, type.Length - 6).Split(',').Select(c => c.Trim()).Where(c => c.Length > 0).ToList();
            }
            else
            {
                arg.Type = type.ToLowerInvariant();
                if (!(arg.Type is "string" or "int" or "number" or "bool" or "list"))
                    errors?.Add("@arg " + arg.Name + ": unknown type " + type);
            }
            arg.Required = false;
            int i = 2;
            for (; i < words.Count; i++)
            {
                var w = words[i];
                if (w.Equals("optional", StringComparison.OrdinalIgnoreCase)) arg.Required = false;
                else if (w.Equals("required", StringComparison.OrdinalIgnoreCase)) arg.Required = true;
                else if (w.StartsWith("default=", StringComparison.OrdinalIgnoreCase)) arg.Default = w.Substring(8);
                else break;
            }
            if (i < words.Count) arg.Description = string.Join(" ", words.Skip(i));
            return arg;
        }

        private static int IndexOfWhite(string s)
        {
            for (int i = 0; i < s.Length; i++) if (char.IsWhiteSpace(s[i])) return i;
            return -1;
        }

        private static string FirstWord(string s)
        {
            int i = IndexOfWhite(s);
            return i < 0 ? s : s.Substring(0, i);
        }

        private static string Append(string? a, string b) => string.IsNullOrEmpty(a) ? b : a + " " + b;

        private static bool ParseBool(string s) =>
            s.Equals("true", StringComparison.OrdinalIgnoreCase) || s == "1" || s.Equals("yes", StringComparison.OrdinalIgnoreCase);
    }
}
