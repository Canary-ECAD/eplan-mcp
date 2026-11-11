// @tool     text_set_box
// @desc     Sets the alignment-box settings of one text on a page, picked by its handle from text_placements; only the settings passed are written, each is read back. Dry run by default.
// @schema   1
// @arg      page               string  required   Page Name or IdentifyingName (exact) the text is on
// @arg      handle             string  required   The text's handle from text_placements
// @arg      has_box            bool    optional   Text has an alignment box
// @arg      box_fixed_width    bool    optional   Box width is fixed
// @arg      box_fixed_height   bool    optional   Box height is fixed
// @arg      fitting_permitted  bool    optional   EPLAN may shrink the text to fit the box
// @arg      never_hyphenate    bool    optional   Never hyphenate words
// @arg      remove_breaks      bool    optional   Remove line breaks
// @arg      box_width          number  optional   Box width in mm (> 0)
// @arg      box_height         number  optional   Box height in mm (> 0)
// @arg      allow_shared       bool    optional   Allow writing a text that belongs to a symbol variant (changes every instance of it)
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). Each setting is reported with
// before, requested and after; not_stuck lists the settings EPLAN did not keep.
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
        var result = TextPlacements.SetBox(ctx, text, owner, ctx.Args, ctx.Args.Bool("allow_shared"));
        result["page"] = page.Name;
        result["handle"] = handle;
        return result;
    }
}
