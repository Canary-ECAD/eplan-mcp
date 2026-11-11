using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using EplanMcp.Scripting;

namespace EplanMcp.Eplan
{
    /// <summary>
    /// Defensive reads. Many EPLAN getters throw instead of returning null (a property an object
    /// does not carry, a member a placement type does not support), so a report reads each value on
    /// its own and records a failure instead of losing the whole row.
    /// </summary>
    public static class Safe
    {
        /// <summary>The value, or null when the read throws.</summary>
        public static string? Text(Func<string?> read)
        {
            try { return read(); }
            catch (Exception) { return null; }
        }

        /// <summary>The value, or <paramref name="fallback"/> when the read throws.</summary>
        public static T Get<T>(Func<T> read, T fallback)
        {
            try { return read(); }
            catch (Exception) { return fallback; }
        }

        /// <summary>The value, or null when the read throws.</summary>
        public static T? Maybe<T>(Func<T> read) where T : struct
        {
            try { return read(); }
            catch (Exception) { return null; }
        }

        /// <summary>The object, or null when the read throws.</summary>
        public static T? Object<T>(Func<T?> read) where T : class
        {
            try { return read(); }
            catch (Exception) { return null; }
        }

        /// <summary>Runs <paramref name="action"/> and ignores a failure. For best-effort writes
        /// whose result is checked by reading back.</summary>
        public static void Try(Action action)
        {
            try { action(); }
            catch (Exception) { }
        }

        private static readonly Regex LanguagePrefix = new Regex(@"^[A-Za-z?]{2}_[A-Za-z?]{2}@");
        private static readonly Regex LanguageSegment = new Regex(@";[A-Za-z?]{2}_[A-Za-z?]{2}@");

        /// <summary>
        /// A text read through ToString() as the user sees it. EPLAN stores a text with no language
        /// as a one-entry MultiLangString, which reads back as "??_??@text;" (or "de_DE@text;"):
        /// the language prefix and the closing ';' go. A text with several languages, and any text
        /// without such a prefix, comes back unchanged. Null reads as "".
        /// </summary>
        public static string PlainText(string? text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            var m = LanguagePrefix.Match(text);
            if (!m.Success) return text!;
            var rest = text!.Substring(m.Length);
            if (rest.EndsWith(";", StringComparison.Ordinal)) rest = rest.Substring(0, rest.Length - 1);
            return LanguageSegment.IsMatch(rest) ? text : rest;
        }

        /// <summary>"ExceptionType: message", the form every report uses.</summary>
        public static string Error(Exception ex) => ex.GetType().Name + ": " + ex.Message;

        /// <summary>Reads into <paramref name="row"/>[<paramref name="key"/>]; on failure stores null and
        /// appends "key: error" to <paramref name="errors"/>.</summary>
        public static void Field(Dictionary<string, object?> row, List<string> errors, string key, Func<object?> read)
        {
            try { row[key] = read(); }
            catch (Exception ex) { row[key] = null; errors.Add(key + ": " + Error(ex)); }
        }

        /// <summary>Joins collected per-field errors, or null when there were none.</summary>
        public static string? Join(List<string> errors) => errors.Count == 0 ? null : string.Join(" | ", errors);

        /// <summary>
        /// Throws unless the run may change the project now: it passed the write gate and is not a
        /// dry run. The script safety check cannot see inside this library, so every helper that
        /// writes calls this (or <see cref="ScriptContext.Lock{T}"/>) before its first change.
        /// </summary>
        public static void RequireWrite(ScriptContext ctx)
        {
            if (!ctx.WriteAllowed) throw new InvalidOperationException("This run may not write. Use a scratch clone, and declare '// @writes true'.");
            if (ctx.DryRun) throw new InvalidOperationException("Dry run: report the change instead of making it (check ctx.DryRun).");
        }
    }
}
