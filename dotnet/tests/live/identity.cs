// @desc  Live check: scripts must bind to the one loaded copy of the EPLAN API and of the host.
// @writes false
using System;
using System.Linq;
#if !NETFRAMEWORK
using System.Runtime.Loader;
#endif
using Eplan.EplApi.DataModel;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var all = AppDomain.CurrentDomain.GetAssemblies();
        var dm = typeof(LockingStep).Assembly;
        var host = typeof(ScriptContext).Assembly;
        var dmName = dm.GetName().Name;   // DataModelNetu on 2027, DataModelu on 2026
        return new
        {
            data_model_copies = all.Count(a => a.GetName().Name == dmName),
            data_model_location = dm.Location,
            context_from_host = ctx.GetType().Assembly == host,
            host_copies = all.Count(a => a.GetName().Name == "EplanMcp.Scripting"),
            helper_copies = all.Count(a => a.GetName().Name == "EplanMcp.Eplan"),
#if NETFRAMEWORK
            // No load contexts: one copy of each host assembly per host build, kept until EPLAN closes.
            helper_from_host = typeof(EplanMcp.Eplan.Pages).Assembly == all.FirstOrDefault(a => a.GetName().Name == "EplanMcp.Eplan"),
#else
            data_model_context = AssemblyLoadContext.GetLoadContext(dm)?.Name,
            host_context = AssemblyLoadContext.GetLoadContext(host)?.Name,
            helper_from_host = typeof(EplanMcp.Eplan.Pages).Assembly == all.FirstOrDefault(a =>
                a.GetName().Name == "EplanMcp.Eplan" && !(AssemblyLoadContext.GetLoadContext(a)?.IsCollectible ?? false)),
            script_context = AssemblyLoadContext.GetLoadContext(typeof(Script).Assembly)?.Name,
#endif
            runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
        };
    }
}
