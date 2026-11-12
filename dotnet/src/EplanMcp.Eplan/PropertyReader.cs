using System;
using System.Collections.Generic;
using System.Text;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;

// PropertyDefinition.GetAsDisplayString is deprecated but still gives the definition's display text,
// which has no PropertyValue to call GetDisplayString on.
#pragma warning disable CS0618

namespace EplanMcp.Eplan
{
    /// <summary>
    /// Reading EPLAN properties without the usual traps.
    /// <list type="bullet">
    /// <item>A property the object does not carry throws (S063109) instead of returning empty, so
    /// every read here is guarded.</item>
    /// <item>An EMPTY value throws from <c>ToInt()</c> / <c>ToDouble()</c> and similar; check
    /// <c>IsEmpty</c> first. These helpers return null for empty.</item>
    /// <item><c>PropertyValue</c> converts to string, int and bool through implicit operators.
    /// Reflection, <c>Convert.ToString</c> and <c>dynamic</c> do not apply implicit operators, so
    /// they give the type name or an ambiguity error; always call <c>ToString()</c> on the value.</item>
    /// <item>A user-defined property is reachable only through a project-scoped id:
    /// <c>new AnyPropertyId(project, name)</c>.</item>
    /// </list>
    /// </summary>
    public static class PropertyReader
    {
        /// <summary>FUNC_SUPPLEMENTARYFIELD, indexed 1..1000. Backed by a MultiLangString.</summary>
        public const int SupplementaryField = 20901;

        /// <summary>The value's text, or null when the value is null or empty.</summary>
        public static string? Text(PropertyValue? value) => value == null || value.IsEmpty ? null : value.ToString();

        /// <summary>Property <paramref name="id"/> as text; null when empty, absent or unreadable.</summary>
        public static string? Read(StorableObject o, int id)
        {
            try { return Text(o.Properties[(AnyPropertyId)id]); }
            catch (Exception) { return null; }
        }

        /// <summary>Indexed property <paramref name="id"/>[<paramref name="index"/>] as text; null when
        /// empty, absent or unreadable.</summary>
        public static string? Read(StorableObject o, int id, int index)
        {
            try { return Text(o.Properties[(AnyPropertyId)id, index]); }
            catch (Exception) { return null; }
        }

        /// <summary>Like <see cref="Read(StorableObject,int,int)"/>, but reports why a read failed.</summary>
        public static string? TryRead(StorableObject o, AnyPropertyId id, int index, out string? error)
        {
            error = null;
            try { return Text(o.Properties[id, index]); }
            catch (Exception ex) { error = Safe.Error(ex); return null; }
        }

        /// <summary>Supplementary field <paramref name="index"/> (#20901), RAW (no decoding, no
        /// language handling), or null.</summary>
        public static string? Supplementary(StorableObject o, int index) => Read(o, SupplementaryField, index);

        /// <summary>
        /// A property id from an identifying name (user-defined properties included) or a number.
        /// Null with <paramref name="error"/> when neither resolves.
        /// </summary>
        public static AnyPropertyId? ResolveId(Project project, string? identName, int propertyId, out string? error)
        {
            error = null;
            try
            {
                if (!string.IsNullOrEmpty(identName)) return new AnyPropertyId(project, identName);
                if (propertyId != 0) return (AnyPropertyId)propertyId;
                error = "neither an identifying name nor a property id was given";
            }
            catch (Exception ex) { error = Safe.Error(ex); }
            return null;
        }

        /// <summary>
        /// Property <paramref name="id"/> read plainly, and when that throws (an indexed property),
        /// again at <paramref name="fallbackIndex"/>. Returns
        /// {kind:"id", id, index, name, found, value, display, err}.
        /// </summary>
        public static Dictionary<string, object?> ReadById(StorableObject o, int id, int fallbackIndex = 1)
        {
            var item = new Dictionary<string, object?>
            {
                ["kind"] = "id", ["id"] = id, ["index"] = null, ["name"] = null,
                ["found"] = false, ["value"] = null, ["display"] = null, ["err"] = null,
            };
            var errors = new List<string>();
            try
            {
                var pv = o.Properties[(AnyPropertyId)id];
                item["value"] = pv?.ToString();
                item["found"] = true;
            }
            catch (Exception ex)
            {
                errors.Add("plain: " + Safe.Error(ex));
                try
                {
                    var pv = o.Properties[(AnyPropertyId)id, fallbackIndex];
                    item["value"] = pv?.ToString();
                    item["index"] = fallbackIndex;
                    item["found"] = true;
                }
                catch (Exception ex2) { errors.Add("indexed[" + fallbackIndex + "]: " + Safe.Error(ex2)); }
            }
            try
            {
                var def = new PropertyDefinition((AnyPropertyId)id);
                item["name"] = def.Name;
                item["display"] = def.GetAsDisplayString();
            }
            catch (Exception ex) { errors.Add("definition: " + Safe.Error(ex)); }
            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>
        /// Property by identifying name; when the by-name indexer throws, again through the
        /// project-scoped id (user-defined properties). Returns
        /// {kind:"name", id, index, name, found, value, display, err}.
        /// </summary>
        public static Dictionary<string, object?> ReadByName(StorableObject o, Project project, string name)
        {
            var item = new Dictionary<string, object?>
            {
                ["kind"] = "name", ["id"] = null, ["index"] = null, ["name"] = name,
                ["found"] = false, ["value"] = null, ["display"] = null, ["err"] = null,
            };
            var errors = new List<string>();
            try
            {
                var pv = o.Properties[name];
                item["value"] = pv?.ToString();
                item["found"] = true;
                try
                {
                    var def = pv?.Definition;
                    if (def != null)
                    {
                        item["display"] = def.GetAsDisplayString();
                        Safe.Try(() => item["id"] = def.Id.AsInt);
                    }
                }
                catch (Exception ex) { errors.Add("definition: " + Safe.Error(ex)); }
            }
            catch (Exception ex)
            {
                errors.Add("by-name: " + Safe.Error(ex));
                try
                {
                    var anyId = new AnyPropertyId(project, name);
                    var pv = o.Properties[anyId];
                    item["value"] = pv?.ToString();
                    item["found"] = true;
                    Safe.Try(() => item["id"] = anyId.AsInt);
                }
                catch (Exception ex2) { errors.Add("AnyPropertyId(project, name): " + Safe.Error(ex2)); }
            }
            item["err"] = Safe.Join(errors);
            return item;
        }

        /// <summary>Every property the object holds a value for:
        /// [{kind:"existing", id, index, name, found, value, display, err}].</summary>
        public static List<object> Existing(StorableObject o)
        {
            var results = new List<object>();
            foreach (var existing in o.Properties.ExistingIds ?? Array.Empty<AnyPropertyId>())
            {
                var item = new Dictionary<string, object?> { ["kind"] = "existing", ["name"] = null, ["found"] = true, ["err"] = null };
                try { item["id"] = existing.AsInt; }
                catch (Exception ex) { item["id"] = null; item["err"] = "id: " + Safe.Error(ex); }
                item["index"] = Safe.Maybe(() => (int)existing.Index);
                try { item["value"] = o.Properties[existing]?.ToString(); }
                catch (Exception ex) { item["value"] = null; item["err"] = "value: " + Safe.Error(ex); }
                item["display"] = Safe.Text(() => existing.Definition?.Name);
                results.Add(item);
            }
            return results;
        }

        /// <summary>
        /// The same property read per language. A value that "contains all the languages" reads as
        /// one string through ToString() but as separate entries here; returns language -&gt; escaped
        /// text, "(not a MultiLangString)", or "ERR: ...".
        /// </summary>
        public static object? EveryLanguage(StorableObject o, int id, int index)
        {
            try
            {
                var value = o.Properties[(AnyPropertyId)id, index];
                if (value == null) return null;
                var multi = value.ToMultiLangString();
                if (multi == null) return "(not a MultiLangString)";
                var byLanguage = new Dictionary<string, object?>();
                foreach (ISOCode.Language code in Enum.GetValues(typeof(ISOCode.Language)))
                {
                    string? text;
                    try { text = multi.GetString(code); }
                    catch (Exception) { continue; }
                    if (!string.IsNullOrEmpty(text)) byLanguage[code.ToString()] = Escape(text);
                }
                return byLanguage;
            }
            catch (Exception ex) { return "ERR: " + Safe.Error(ex); }
        }

        /// <summary>Makes separators visible: CR, LF, control characters and the pilcrow become
        /// escapes, everything else is unchanged.</summary>
        public static string? Escape(string? text)
        {
            if (text == null) return null;
            var sb = new StringBuilder();
            foreach (var c in text)
            {
                if (c == '\r') sb.Append("\\r");
                else if (c == '\n') sb.Append("\\n");
                else if (c < 32 || c == '¶') sb.Append("\\u").Append(((int)c).ToString("X4"));
                else sb.Append(c);
            }
            return sb.ToString();
        }
    }
}
