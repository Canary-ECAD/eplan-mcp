// @tool     layer_table
// @desc     The project's graphical layer table: name, id, description and the visible, locked, printed and custom flags.
// @schema   1
// @writes   false
// @needs    session
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var layers = Layers.Table(project);
        return new { project = project.ProjectFullName, layer_count = layers.Count, layers };
    }
}
