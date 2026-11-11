// @tool     read_selection
// @desc     The current editor selection (direct and recursive), the page-navigator page selection and the object being edited.
// @schema   1
// @writes   false
// @needs    gui
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx) => Selection.Read();
}
