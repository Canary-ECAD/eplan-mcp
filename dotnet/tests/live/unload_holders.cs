// @desc  Live diagnostic: who subscribes to assembly-load events (a subscriber that keeps the
//        Assembly objects it is handed stops collectible script contexts from unloading).
// @writes false
// @unsafe
using System;
using System.Linq;
using System.Reflection;
using System.Runtime.Loader;

string Describe(Delegate? d) => d == null ? "none" : string.Join("; ", d.GetInvocationList().Select(x =>
    (x.Method.DeclaringType?.FullName ?? "?") + "." + x.Method.Name + " [" + (x.Method.DeclaringType?.Assembly.GetName().Name ?? "?") + "]"));

Delegate? Field(Type t, object? target, params string[] names)
{
    foreach (var n in names)
    {
        var f = t.GetField(n, BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance);
        if (f != null) return f.GetValue(target) as Delegate;
    }
    return null;
}

var alcType = typeof(AssemblyLoadContext);
return new
{
    alc_assembly_load = Describe(Field(alcType, null, "AssemblyLoad")),
    appdomain_assembly_load = Describe(Field(typeof(AppDomain), AppDomain.CurrentDomain, "AssemblyLoad", "_AssemblyLoad")),
    alc_fields = alcType.GetFields(BindingFlags.NonPublic | BindingFlags.Static).Where(f => typeof(Delegate).IsAssignableFrom(f.FieldType)).Select(f => f.Name + "=" + Describe(f.GetValue(null) as Delegate)).ToList(),
    collectible_contexts_alive = AssemblyLoadContext.All.Count(c => c.IsCollectible && (c.Name ?? "").StartsWith("EplanMcpScript_")),
};
