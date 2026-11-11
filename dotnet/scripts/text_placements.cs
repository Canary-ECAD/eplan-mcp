// @tool     text_placements
// @desc     Lists the texts on one page - the property texts of every symbol and, by default, the free texts - with height, font size, alignment-box settings, position and bounds. Each text has a handle that text_set_height and text_set_box accept.
// @schema   1
// @arg      page                string  required   Page Name or IdentifyingName (exact)
// @arg      symbol_prefix       string  optional   Only symbols whose symbol name starts with this
// @arg      include_free_texts  bool    optional   Also list the free texts (default true)
// @writes   false
// @needs    session
//
// height and font_size are listed side by side because EPLAN stores them separately; a text can
// show one and keep the other. shared_placements = true on a symbol means its texts belong to the
// symbol variant, so a write to one changes every instance of that variant. box_fit_ready means
// EPLAN can shrink the text into its alignment box.
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var page = Pages.Require(ctx.RequireProject(), ctx.Args.Require("page"));
        return TextPlacements.List(ctx, page, ctx.Args.String("symbol_prefix"), ctx.Args.Bool("include_free_texts", true));
    }
}
