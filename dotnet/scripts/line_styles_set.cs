// @tool     line_styles_set
// @desc     Sets the line style, style factor and/or width of every line and arc inside an area of one page, and reads each back. Refuses when nothing or more than limit lines match. Dry run by default.
// @schema   1
// @arg      page    string  required   Page Name or IdentifyingName (exact)
// @arg      x0      number  required   Area left in mm
// @arg      y0      number  required   Area bottom in mm
// @arg      x1      number  required   Area right in mm
// @arg      y1      number  required   Area top in mm
// @arg      limit   int     required   Max lines that may be changed; more matches means nothing is written
// @arg      style   int     optional   Line style id to set
// @arg      factor  number  optional   Line style factor to set (> 0)
// @arg      width   number  optional   Line width in mm to set (>= 0)
// @writes   true
// @needs    session
//
// Writes only to a scratch clone (eplan_scratch_project_create). Run line_styles over the same area
// first to see what matches. A line counts as inside when its whole bounding box is. Every line is
// read back; not_stuck counts the lines where a value did not stick, and the first 60 lines are
// listed with before and after.
using System;
using System.Collections.Generic;
using System.Linq;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var page = Pages.Require(ctx.RequireProject(), ctx.Args.Require("page"));
        bool setStyle = ctx.Args.Has("style"), setFactor = ctx.Args.Has("factor"), setWidth = ctx.Args.Has("width");
        if (!setStyle && !setFactor && !setWidth) return new { error = "nothing to set: pass style, factor and/or width." };
        double factor = ctx.Args.Number("factor"), width = ctx.Args.Number("width");
        if (setFactor && !(factor > 0)) return new { error = "factor must be greater than 0." };
        if (setWidth && !(width >= 0)) return new { error = "width must be 0 or more." };
        short style = (short)ctx.Args.Int("style");
        double x0 = ctx.Args.Number("x0"), y0 = ctx.Args.Number("y0"), x1 = ctx.Args.Number("x1"), y1 = ctx.Args.Number("y1");
        if (x1 <= x0 || y1 <= y0) return new { error = "the area is empty: x1 must be greater than x0 and y1 greater than y0." };

        var lines = Lines.InArea(page, x0, y0, x1, y1);
        var refusal = Guards.OverLimit(lines.Count, ctx.Args.Int("limit"), "lines and arcs");
        if (refusal != null) return new { page = page.Name, matched = lines.Count, error = refusal };

        const int reportLimit = 60;
        var rows = new List<object>();
        int notStuck = 0, failed = 0;
        foreach (var g in lines)
        {
            ctx.Budget.Check();
            var row = new Dictionary<string, object?> { ["before"] = Lines.Describe(g) };
            if (!ctx.DryRun)
            {
                try
                {
                    ctx.Lock(g);
                    g.LockObject();
                    var pen = g.Pen;   // the pen is a copy: change it, then assign it back
                    if (setStyle) pen.StyleId = style;
                    if (setFactor) pen.StyleFactor = factor;
                    if (setWidth) pen.Width = width;
                    g.Pen = pen;
                    var after = g.Pen;
                    bool sticks = (!setStyle || after.StyleId == style)
                               && (!setFactor || Math.Abs(after.StyleFactor - factor) < 0.0001)
                               && (!setWidth || Math.Abs(after.Width - width) < 0.0001);
                    row["after"] = Lines.Describe(g);
                    row["sticks"] = sticks;
                    if (!sticks) notStuck++;
                }
                catch (Exception ex) { row["error"] = Safe.Error(ex); failed++; }
            }
            if (rows.Count < reportLimit) rows.Add(row);
        }
        return new
        {
            page = page.Name, dry_run = ctx.DryRun, matched = lines.Count,
            changed = ctx.DryRun ? 0 : lines.Count - notStuck - failed, not_stuck = notStuck, failed,
            reported = rows.Count, lines = rows,
        };
    }
}
