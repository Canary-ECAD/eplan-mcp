// @desc  Live check: what the compiler had to work with under EPLAN's native host.
// @writes false
using System;
using System.Linq;

var tpa = AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string;
var loaded = AppDomain.CurrentDomain.GetAssemblies().Where(a => !a.IsDynamic).ToList();
return new
{
    trusted_platform_list = tpa != null,
    trusted_platform_count = tpa == null ? 0 : tpa.Split(System.IO.Path.PathSeparator).Length,
    loaded_assemblies = loaded.Count,
    loaded_without_location = loaded.Count(a => string.IsNullOrEmpty(a.Location)),
    eplan_assemblies = loaded.Where(a => (a.GetName().Name ?? "").StartsWith("Eplan.")).Select(a => a.GetName().Name).OrderBy(n => n).ToList(),
};
