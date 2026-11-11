// @desc  Live check: a write run can lock an object (scratch clone only). Changes no value.
// @writes true
using System.Linq;
using Eplan.EplApi.DataModel;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var fn = new DMObjectsFinder(project).GetFunctions(null).FirstOrDefault(f => f.IsValid);
        if (fn == null) return new { error = "The project has no functions to sample." };
        string? error = null;
        try { ctx.Lock(fn); }
        catch (System.Exception e) { error = e.GetType().Name + ": " + e.Message; }
        return new { function = fn.Name, locked = fn.IsLocked, error, write_allowed = ctx.WriteAllowed };
    }
}
