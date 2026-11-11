using System;
using System.Collections.Generic;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.Graphics;

namespace EplanMcp.Eplan
{
    /// <summary>The project's graphical layer table.</summary>
    public static class Layers
    {
        /// <summary>[{name, id, description, visible, locked, printed, custom, err}].</summary>
        public static List<object> Table(Project project)
        {
            var table = project.LayerTable;
            var layers = table?.Layers ?? Array.Empty<GraphicalLayer>();
            var list = new List<object>();
            foreach (var layer in layers)
            {
                if (layer == null) continue;
                var item = new Dictionary<string, object?>();
                var errors = new List<string>();
                Safe.Field(item, errors, "name", () => layer.Name);
                Safe.Field(item, errors, "id", () => (int)layer.Id);
                Safe.Field(item, errors, "description", () => layer.Description?.ToString());
                Safe.Field(item, errors, "visible", () => layer.isVisible);
                Safe.Field(item, errors, "locked", () => layer.isLocked);
                Safe.Field(item, errors, "printed", () => layer.isPrinted);
                Safe.Field(item, errors, "custom", () => layer.isCustom);
                item["err"] = Safe.Join(errors);
                list.Add(item);
            }
            return list;
        }
    }
}
