// @tool     text_set_height
// @desc     Sets the height of one text on a page, picked by its handle from text_placements, to an absolute height or a multiple of the current one, and reads it back. Dry run by default.
// @schema   1
// @arg      page          string  required   Page Name or IdentifyingName (exact) the text is on
// @arg      handle        string  required   The text's handle from text_placements
// @arg      height        number  optional   New height in mm (or -16002 for "from layer"); give height or factor
// @arg      factor        number  optional   Multiply the current height by this (> 0); give height or factor
// @arg      target        enum(height,font_size) default=height  Write the text height, or the font size property
// @arg      allow_shared  bool    optional   Kept for compatibility: a text that belongs to a symbol variant is always refused, because EPLAN write-protects its height and font size
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). The result has the values before
// and after; "sticks" is false, and not_stuck names the value, when EPLAN did not keep it. A property
// text shown from its symbol variant (shared_placements=true in text_placements) cannot take a
// height or font size: use text_set_box, or make the symbol's placements local in EPLAN.
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var page = Pages.Require(ctx.RequireProject(), ctx.Args.Require("page"));
        string handle = ctx.Args.Require("handle");
        var text = TextPlacements.Resolve(page, handle, out var owner, out var error);
        if (text == null) return new { handle, error };
        double? height = ctx.Args.Has("height") ? ctx.Args.Number("height") : (double?)null;
        double? factor = ctx.Args.Has("factor") ? ctx.Args.Number("factor") : (double?)null;
        var result = TextPlacements.SetHeight(ctx, text, owner, height, factor, ctx.Args.String("target", "height")!, ctx.Args.Bool("allow_shared"));
        result["page"] = page.Name;
        result["handle"] = handle;
        return result;
    }
}
