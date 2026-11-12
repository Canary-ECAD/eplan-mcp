// @tool     text_create
// @desc     Places a free text on a page at a position and height, then reads its text, position and height back. Returns the new text's handle and how to undo it. Dry run by default.
// @schema   1
// @arg      page    string  required   Page Name or IdentifyingName (exact)
// @arg      text    string  required   The text, not empty or only spaces; a "\n" in it starts a new line
// @arg      x       number  required   Page x in mm
// @arg      y       number  required   Page y in mm
// @arg      height  number  optional   Text height in mm (default 2.5, > 0)
// @arg      debug   bool    optional   Also return the character codes sent and read back (to check line breaks and special characters)
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). "text" in the result has EPLAN's
// language prefix removed; not_stuck names any value EPLAN did not keep.
using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel.Graphics;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var project = ctx.RequireProject();
        var page = Pages.Require(project, ctx.Args.Require("page"));
        string text = ctx.Args.Require("text");
        if (string.IsNullOrWhiteSpace(text)) return new { error = "text is empty or only whitespace; nothing to place." };
        double x = ctx.Args.Number("x"), y = ctx.Args.Number("y"), height = ctx.Args.Number("height", 2.5);
        if (!(height > 0)) return new { error = "height must be greater than 0 mm." };
        bool debug = ctx.Args.Bool("debug");
        var result = new Dictionary<string, object?>
        {
            ["dry_run"] = ctx.DryRun, ["page"] = page.Name,
            ["wanted"] = new Dictionary<string, object?> { ["text"] = text, ["x"] = x, ["y"] = y, ["height"] = height },
        };
        if (debug) result["sent_codes"] = text.Select(c => (int)c).ToList();
        if (ctx.DryRun) return result;

        ctx.Lock(page);
        var t = new Text();
        t.Create(page, text, height);
        t.Location = new PointD(x, y);
        string raw = t.Contents?.ToString() ?? "";
        string back = Safe.PlainText(raw);
        double? hAfter = Safe.Maybe(() => t.Height);
        double? xAfter = Safe.Maybe(() => t.Location.X), yAfter = Safe.Maybe(() => t.Location.Y);
        var notStuck = new List<string>();
        if (back != text) notStuck.Add("text");
        if (!Near(xAfter, x)) notStuck.Add("x");
        if (!Near(yAfter, y)) notStuck.Add("y");
        if (!Near(hAfter, height)) notStuck.Add("height");
        string? handle = TextPlacements.Id(t);
        result["handle"] = handle;
        result["after"] = new Dictionary<string, object?> { ["text"] = back, ["x"] = xAfter, ["y"] = yAfter, ["height"] = hAfter };
        result["not_stuck"] = notStuck;
        result["undo"] = new Dictionary<string, object?> { ["tool"] = "eplan_live_remove_placement", ["page"] = page.Name, ["handle"] = handle };
        if (debug)
        {
            result["read_back_raw"] = raw;
            result["read_back_codes"] = back.Select(c => (int)c).ToList();
        }
        return result;
    }

    private static bool Near(double? got, double wanted) => got.HasValue && Math.Abs(got.Value - wanted) < 0.0001;
}
