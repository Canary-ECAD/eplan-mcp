"""
Discovery actions - enumerate EPLAN catalogs instead of guessing.

Audit/TODO.md item 3: scheme names, setting paths, report templates, layers
and enum values live inside EPLAN's configuration and could not be listed by
any tool, so the LLM had to guess or ask the user. Every function here
returns a real catalog read from the EPLAN API (the pattern established by
parts_db_list_product_groups in scripted.py).

API surfaces used (verified against the P8 docs RAG):
- Eplan.EplApi.Base.SettingNode(path) with GetListOfNodes/GetListOfSettings
  (ref StringCollection, bAbsolutPath)
- Eplan.EplApi.Base.PathMap.SubstitutePath
- Eplan.EplApi.DataModel.Project.LayerTable.Layers (GraphicalLayer[])
- Enum.GetNames over EPLAN enums via reflection
"""

import uuid

from .scripted import _execute_script
from .live import _script as _reflection_script
from ._base import cs_escape


def settings_list_children(setting_path: str) -> dict:
    """
    List child nodes and settings under a settings-tree path.

    The master key for discovering EPLAN catalogs: export/import schemes,
    filter/sort schemes, and most named configurations are stored as nodes
    in the settings tree. Walk the tree with this tool instead of guessing
    setting paths; read values with settings_get_string/bool/int.

    Args:
        setting_path: Settings-tree path, e.g. "USER.TrDMPrj" or
            "STATION.AF.Services". Sections are separated by '.'.

    Returns:
        dict with "nodes" (child node names) and "settings" (leaf setting
        names) relative to the given path.
    """
    escaped = cs_escape(setting_path)
    script = f'''using System;
using System.IO;
using System.Collections.Generic;
using System.Collections.Specialized;
using Eplan.EplApi.Base;
using Eplan.EplApi.Scripting;

public class SettingsListChildren_{uuid.uuid4().hex[:6]}
{{
    [Start]
    public void Run()
    {{
        var results = new Dictionary<string, object>();

        try
        {{
            var node = new SettingNode("{escaped}");

            var nodeNames = new StringCollection();
            node.GetListOfNodes(ref nodeNames, false);
            var nodes = new List<string>();
            foreach (string n in nodeNames) nodes.Add(n);

            var settingNames = new StringCollection();
            node.GetListOfSettings(ref settingNames, false);
            var settings = new List<string>();
            foreach (string s in settingNames) settings.Add(s);

            results["success"] = true;
            results["path"] = "{escaped}";
            results["nodes"] = nodes;
            results["settings"] = settings;
        }}
        catch (Exception ex)
        {{
            results["success"] = false;
            results["error"] = ex.Message;
        }}

        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented);
        File.WriteAllText(@"{{{{RESULT_PATH}}}}", json);
    }}
}}
'''
    return _execute_script(script)


def list_schemes(name_filter: str = None) -> dict:
    """
    List scheme files in the master data schemes folder ($(MD_SCHEMES)).

    EPLAN stores named schemes (export, import, labeling, filters, ...) as
    XML files in the schemes master data folder; the file name (without
    extension) is the scheme name used by CONFIGSCHEME/FILTERSCHEME/
    export_scheme parameters. Schemes stored only in the settings tree can
    be found with settings_list_children instead.

    Args:
        name_filter: Optional case-insensitive substring to filter scheme
            names (e.g. "pdf", "label", "dxf").

    Returns:
        dict with scheme names grouped by file extension.
    """
    escaped_filter = cs_escape(name_filter or "")
    script = f'''using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Eplan.EplApi.Base;
using Eplan.EplApi.Scripting;

public class ListSchemes_{uuid.uuid4().hex[:6]}
{{
    [Start]
    public void Run()
    {{
        var results = new Dictionary<string, object>();

        try
        {{
            string dir = PathMap.SubstitutePath("$(MD_SCHEMES)");
            results["folder"] = dir;
            string filter = "{escaped_filter}";

            var byExtension = new Dictionary<string, List<string>>();
            int total = 0;
            if (Directory.Exists(dir))
            {{
                foreach (var file in Directory.GetFiles(dir))
                {{
                    string name = Path.GetFileNameWithoutExtension(file);
                    if (filter.Length > 0 && name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0)
                    {{
                        continue;
                    }}
                    string ext = Path.GetExtension(file).ToLowerInvariant();
                    if (!byExtension.ContainsKey(ext)) byExtension[ext] = new List<string>();
                    byExtension[ext].Add(name);
                    total++;
                }}
                results["success"] = true;
                results["count"] = total;
                results["schemes"] = byExtension;
            }}
            else
            {{
                results["success"] = false;
                results["error"] = "Schemes folder not found: " + dir;
            }}
        }}
        catch (Exception ex)
        {{
            results["success"] = false;
            results["error"] = ex.Message;
        }}

        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented);
        File.WriteAllText(@"{{{{RESULT_PATH}}}}", json);
    }}
}}
'''
    return _execute_script(script)


def list_report_templates() -> dict:
    """
    List report forms/templates from the master data folders.

    Enumerates the forms folder ($(MD_FORMS)) and, when present, the
    templates folder ($(MD_TEMPLATES)) so report generation can use real
    form names instead of guessed ones.

    Returns:
        dict with file names grouped by folder and extension.
    """
    script = f'''using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Eplan.EplApi.Base;
using Eplan.EplApi.Scripting;

public class ListReportTemplates_{uuid.uuid4().hex[:6]}
{{
    [Start]
    public void Run()
    {{
        var results = new Dictionary<string, object>();
        var folders = new Dictionary<string, object>();

        try
        {{
            string[] variables = new string[] {{ "$(MD_FORMS)", "$(MD_TEMPLATES)" }};
            foreach (var variable in variables)
            {{
                try
                {{
                    string dir = PathMap.SubstitutePath(variable);
                    if (!Directory.Exists(dir)) continue;
                    var byExtension = new Dictionary<string, List<string>>();
                    foreach (var file in Directory.GetFiles(dir))
                    {{
                        string ext = Path.GetExtension(file).ToLowerInvariant();
                        if (!byExtension.ContainsKey(ext)) byExtension[ext] = new List<string>();
                        byExtension[ext].Add(Path.GetFileNameWithoutExtension(file));
                    }}
                    folders[variable + " -> " + dir] = byExtension;
                }}
                catch {{}}
            }}

            results["success"] = true;
            results["folders"] = folders;
        }}
        catch (Exception ex)
        {{
            results["success"] = false;
            results["error"] = ex.Message;
        }}

        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented);
        File.WriteAllText(@"{{{{RESULT_PATH}}}}", json);
    }}
}}
'''
    return _execute_script(script)


def list_layers() -> dict:
    """
    List all graphical layers of the currently open project.

    Returns the real layer names (and descriptions where available) from
    Project.LayerTable, for use with layer-related actions instead of
    guessed layer names.

    Returns:
        dict with the project name and its layers.
    """
    # Reached by runtime reflection, NOT `using Eplan.EplApi.DataModel;`: that
    # using does not compile in EPLAN's script engine (CS0234, the fixed
    # assembly set), so the script never ran, never wrote its result file, and
    # this tool could only ever time out. See live.py for the technique.
    body = '''            PropertyInfo ltProp = GetPropInfo(project.GetType(), "LayerTable");
            if (ltProp == null)
                throw new Exception("Project has no LayerTable member.");
            object layerTable = ltProp.GetValue(project, null);
            if (layerTable == null)
                throw new Exception("Project.LayerTable is null.");

            PropertyInfo layersProp = GetPropInfo(layerTable.GetType(), "Layers");
            if (layersProp == null)
                throw new Exception("LayerTable has no Layers member.");
            IEnumerable layers = (IEnumerable)layersProp.GetValue(layerTable, null);

            List<Dictionary<string, object>> list = new List<Dictionary<string, object>>();
            foreach (object lay in layers)
            {
                if (lay == null) continue;
                Dictionary<string, object> d = new Dictionary<string, object>();
                string nm = PropText(lay, "Name");
                d["name"] = nm == null ? "" : nm;
                string ds = PropText(lay, "Description");
                if (ds != null) d["description"] = ds;
                list.Add(d);
            }

            results["success"] = true;
            results["count"] = list.Count;
            results["layers"] = list;
'''
    return _execute_script(
        _reflection_script("ListLayers_" + uuid.uuid4().hex[:6], body),
        timeout=60.0,
    )


def list_enums(enum_type_name: str) -> dict:
    """
    List the values of an EPLAN (or .NET) enum type by full type name.

    Generalizes the parts_db_list_product_groups pattern: resolves the type
    via reflection over the loaded assemblies and returns Enum.GetNames, so
    parameter values can be taken from the real API instead of guessed.

    Args:
        enum_type_name: Full type name, e.g.
            "Eplan.EplApi.MasterData.MDPartsDatabaseItem+Enums+ProductGroup"
            (nested types use '+').

    Returns:
        dict with the enum's value names.
    """
    escaped = cs_escape(enum_type_name)
    script = f'''using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Eplan.EplApi.Scripting;

public class ListEnums_{uuid.uuid4().hex[:6]}
{{
    [Start]
    public void Run()
    {{
        var results = new Dictionary<string, object>();

        try
        {{
            string typeName = "{escaped}";
            Type enumType = Type.GetType(typeName);
            if (enumType == null)
            {{
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {{
                    try {{ enumType = assembly.GetType(typeName); }} catch {{}}
                    if (enumType != null) break;
                }}
            }}

            if (enumType == null)
            {{
                results["success"] = false;
                results["error"] = "Type not found: " + typeName + " (nested types use '+', e.g. Outer+Nested)";
            }}
            else if (!enumType.IsEnum)
            {{
                results["success"] = false;
                results["error"] = "Type is not an enum: " + typeName;
            }}
            else
            {{
                results["success"] = true;
                results["type"] = enumType.FullName;
                results["values"] = Enum.GetNames(enumType).ToList();
            }}
        }}
        catch (Exception ex)
        {{
            results["success"] = false;
            results["error"] = ex.Message;
        }}

        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results, Newtonsoft.Json.Formatting.Indented);
        File.WriteAllText(@"{{{{RESULT_PATH}}}}", json);
    }}
}}
'''
    return _execute_script(script)
