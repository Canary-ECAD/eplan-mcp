using System;
using System.Collections.Generic;
using System.Linq;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.Graphics;

namespace EplanMcp.Eplan
{
    /// <summary>The lines and arcs drawn on a page, and their pens (line style, width, colour).</summary>
    public static class Lines
    {
        /// <summary>Every line and arc on the page whose bounding box lies wholly inside the area
        /// (x0, y0)-(x1, y1), in page millimetres.</summary>
        public static List<GraphicalPlacement> InArea(Page page, double x0, double y0, double x1, double y1) =>
            Pages.Placements(page).OfType<GraphicalPlacement>()
                .Where(g => g is Line || g is Arc)
                .Where(g =>
                {
                    try
                    {
                        var bb = g.GetBoundingBox();
                        return bb[0].X >= x0 && bb[0].Y >= y0 && bb[1].X <= x1 && bb[1].Y <= y1;
                    }
                    catch (Exception) { return false; }
                })
                .ToList();

        /// <summary>{handle, type, layer, box, style, factor, width, colour, pattern}.</summary>
        public static Dictionary<string, object?> Describe(GraphicalPlacement g)
        {
            var row = new Dictionary<string, object?>
            {
                ["handle"] = Safe.Text(() => g.ToStringIdentifier()),
                ["type"] = g.GetType().Name,
                ["layer"] = Safe.Text(() => g.Layer?.Name),
            };
            try
            {
                var bb = g.GetBoundingBox();
                row["box"] = new Dictionary<string, object?> { ["x1"] = bb[0].X, ["y1"] = bb[0].Y, ["x2"] = bb[1].X, ["y2"] = bb[1].Y };
            }
            catch (Exception ex) { row["box_error"] = Safe.Error(ex); }
            try
            {
                var p = g.Pen;
                row["style"] = (int)p.StyleId;
                row["factor"] = p.StyleFactor;
                row["width"] = p.Width;
                row["colour"] = (int)p.ColorId;
                row["pattern"] = p.PatternLength;
            }
            catch (Exception ex) { row["pen_error"] = Safe.Error(ex); }
            return row;
        }
    }
}
