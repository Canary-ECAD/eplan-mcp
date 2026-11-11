// @tool     project_info
// @desc     Summary of the target project: name, link file, page and function counts, read-only flag.
// @schema   1
// @writes   false
// @needs    either
using Eplan.EplApi.DataModel;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var finder = new DMObjectsFinder(project);
        return new
        {
            name = project.ProjectName,
            link_file = project.ProjectLinkFilePath,
            read_only = project.IsReadOnly,
            pages = finder.GetPages(null).Length,
            functions = finder.GetFunctions(null).Length,
        };
    }
}
