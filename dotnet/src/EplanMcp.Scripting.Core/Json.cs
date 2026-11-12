using System;
using System.IO;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace EplanMcp.Scripting.Core
{
    /// <summary>The one serializer configuration for requests, results and audit lines.</summary>
    public static class Json
    {
        public static readonly JsonSerializerOptions Options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DictionaryKeyPolicy = null,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented = false,
            ReferenceHandler = ReferenceHandler.IgnoreCycles,
            MaxDepth = 32,
            NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals,
        };

        /// <summary>Inline results larger than this go to a file instead.</summary>
        public const int InlineLimitBytes = 20_000;

        public static string Serialize<T>(T value) => JsonSerializer.Serialize(value, Options);

        public static T? Deserialize<T>(string json) => JsonSerializer.Deserialize<T>(json, Options);

        /// <summary>
        /// Turns whatever a script returned into plain JSON data while the script is still loaded,
        /// so nothing in the result keeps the script's context alive. EPLAN objects do not
        /// serialize sensibly; when serialization fails the result falls back to ToString().
        /// </summary>
        /// <remarks>Deliberately not JsonSerializer: its reflection layer caches emitted accessors
        /// per type in a static cache, which keeps a script type (an anonymous result) alive and
        /// stops the script from unloading. This walker reads properties and caches nothing.</remarks>
        public static JsonNode? ToPlain(object? value)
        {
            int budget = MaxPlainNodes;
            return Walk(value, 0, ref budget);
        }

        private const int MaxPlainNodes = 200_000;
        private const int MaxPlainDepth = 16;

        private static JsonNode? Walk(object? v, int depth, ref int budget)
        {
            if (v == null) return null;
            if (--budget < 0) return JsonValue.Create("<truncated: result too large>");
            switch (v)
            {
                case JsonNode n: return n.DeepClone();
                case string s: return JsonValue.Create(s);
                case bool b: return JsonValue.Create(b);
                case char c: return JsonValue.Create(c.ToString());
                case Enum e: return JsonValue.Create(e.ToString());
                case DateTime dt: return JsonValue.Create(dt.ToString("o"));
                case DateTimeOffset dto: return JsonValue.Create(dto.ToString("o"));
                case Guid g: return JsonValue.Create(g.ToString());
                case TimeSpan ts: return JsonValue.Create(ts.ToString());
                case double d: return double.IsFinite(d) ? JsonValue.Create(d) : JsonValue.Create(d.ToString(System.Globalization.CultureInfo.InvariantCulture));
                case float f: return float.IsFinite(f) ? JsonValue.Create(f) : JsonValue.Create(f.ToString(System.Globalization.CultureInfo.InvariantCulture));
                case decimal m: return JsonValue.Create(m);
                case int i: return JsonValue.Create(i);
                case long l: return JsonValue.Create(l);
                case short or byte or sbyte or ushort: return JsonValue.Create(Convert.ToInt32(v, System.Globalization.CultureInfo.InvariantCulture));
                case uint ui: return JsonValue.Create(ui);
                case ulong ul: return JsonValue.Create(ul);
            }

            var type = v.GetType();
            if (depth >= MaxPlainDepth) return JsonValue.Create(SafeToString(v));

            // EPLAN objects: their properties can be expensive or throw, so describe, don't walk.
            if ((type.Namespace ?? "").StartsWith("Eplan.", StringComparison.Ordinal))
                return new JsonObject { ["type"] = type.FullName, ["text"] = SafeToString(v) };

            if (v is System.Collections.IDictionary dict)
            {
                var o = new JsonObject();
                foreach (System.Collections.DictionaryEntry kv in dict)
                    o[SafeToString(kv.Key)] = Walk(kv.Value, depth + 1, ref budget);
                return o;
            }
            if (v is System.Collections.IEnumerable seq)
            {
                var a = new JsonArray();
                foreach (var item in seq) a.Add(Walk(item, depth + 1, ref budget));
                return a;
            }

            var obj = new JsonObject();
            foreach (var p in type.GetProperties(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance))
            {
                if (p.GetIndexParameters().Length > 0 || !p.CanRead) continue;
                object? pv;
                try { pv = p.GetValue(v); }
                catch (Exception e) { obj[p.Name] = "<" + (e.InnerException ?? e).GetType().Name + ">"; continue; }
                obj[p.Name] = Walk(pv, depth + 1, ref budget);
            }
            foreach (var f in type.GetFields(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance))
                obj[f.Name] = Walk(f.GetValue(v), depth + 1, ref budget);
            if (obj.Count == 0) return JsonValue.Create(SafeToString(v));
            return obj;
        }

        public static string SafeToString(object value)
        {
            try { return value.ToString() ?? ""; } catch (Exception e) { return "<ToString failed: " + e.Message + ">"; }
        }

        /// <summary>Writes the result inline, or to <c>result.json</c> in the run folder when it is
        /// too big, keeping a short preview inline.</summary>
        public static (object? inline, string? file, bool truncated) Place(JsonNode? plain, string runFolder)
        {
            if (plain == null) return (null, null, false);
            var text = plain.ToJsonString(Options);
            if (text.Length <= InlineLimitBytes || string.IsNullOrEmpty(runFolder)) return (plain, null, false);
            Directory.CreateDirectory(runFolder);
            var file = Path.Combine(runFolder, "result_data.json");   // result.json is the envelope
            File.WriteAllText(file, text);
            return (new JsonObject { ["preview"] = text.Substring(0, 2000) + "...", ["bytes"] = text.Length }, file, true);
        }
    }
}
