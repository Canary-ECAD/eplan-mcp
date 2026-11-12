// @desc  Live diagnostic: who subscribes to assembly-load events (a subscriber that keeps the
//        Assembly objects it is handed stops collectible script contexts from unloading).
//        .NET 8 only: on .NET Framework (EPLAN 2026) scripts never unload, so it reports that.
// @writes false
// @unsafe
using System;
using System.Linq;
using System.Reflection;

#if NETFRAMEWORK
return new { applies = false, runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription };
#else
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

var alcType = typeof(System.Runtime.Loader.AssemblyLoadContext);
return new
{
    alc_assembly_load = Describe(Field(alcType, null, "AssemblyLoad")),
    appdomain_assembly_load = Describe(Field(typeof(AppDomain), AppDomain.CurrentDomain, "AssemblyLoad", "_AssemblyLoad")),
    alc_fields = alcType.GetFields(BindingFlags.NonPublic | BindingFlags.Static).Where(f => typeof(Delegate).IsAssignableFrom(f.FieldType)).Select(f => f.Name + "=" + Describe(f.GetValue(null) as Delegate)).ToList(),
    collectible_contexts_alive = System.Runtime.Loader.AssemblyLoadContext.All.Count(c => c.IsCollectible && (c.Name ?? "").StartsWith("EplanMcpScript_")),
};
#endif
