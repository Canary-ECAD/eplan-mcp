// @tool     line_styles
// @desc     Lists the lines and arcs on one page, or inside an area of it, with their line style, style factor, width, colour, pattern length and layer.
// @schema   1
// @arg      page   string  required   Page Name or IdentifyingName (exact)
// @arg      x0     number  optional   Area left in mm; give all four of x0, y0, x1, y1, or none for the whole page
// @arg      y0     number  optional   Area bottom in mm
// @arg      x1     number  optional   Area right in mm
// @arg      y1     number  optional   Area top in mm
// @arg      limit  int     optional   Max lines listed (default 200); "matched" is the true count
// @writes   false
// @needs    session
//
// A line counts as inside the area when its whole bounding box is. Only some of x0..y1 is refused,
// never read as the whole page. The handles are those
// line_styles_set reports and eplan_live_remove_placement accepts.
using System.Linq;
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx)
    {
        var page = Pages.Require(ctx.RequireProject(), ctx.Args.Require("page"));
        var given = new[] { "x0", "y0", "x1", "y1" }.Where(ctx.Args.Has).ToList();
        if (given.Count is > 0 and < 4)
            return new { error = $"give all four of x0, y0, x1, y1 for an area, or none for the whole page (got only {string.Join(", ", given)})." };
        var lines = Lines.InArea(page, ctx.Args.Number("x0", -1e9), ctx.Args.Number("y0", -1e9),
                                 ctx.Args.Number("x1", 1e9), ctx.Args.Number("y1", 1e9));
        int limit = (int)ctx.Args.Int("limit", 200);
        var rows = lines.Take(limit).Select(Lines.Describe).ToList();
        return new { page = page.Name, matched = lines.Count, returned = rows.Count, truncated = lines.Count > rows.Count, lines = rows };
    }
}
