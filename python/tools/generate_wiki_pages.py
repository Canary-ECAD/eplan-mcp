"""Generate the tool-reference pages from the actual __all__ / docstrings in
api/actions, grouped into reader-friendly categories.

covaga.dev runs this on every build (scripts/sync-docs.mjs in that repo) and
publishes the output at https://covaga.dev/docs/tools/, so the reference always
matches the code. Keep it dependency-free and keep the WIKI_OUT_DIR variable:
the site build points it at a temporary folder."""
import ast
import os

ACTIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "api", "actions")
OUT_DIR = os.environ.get("WIKI_OUT_DIR", r"V:\Workbench\MCP_eplan\eplan-rag-mcp-wiki")

CATEGORIES = [
    ("Project-and-Workspace-Management",
     "Opening, closing, backing up, restoring, upgrading and organizing EPLAN projects and workspaces.",
     ["project", "workspace", "backup", "scripts", "translate"]),
    ("Pages-Navigation-and-Editing",
     "Working the graphical editor: opening pages, jumping to devices, layers, and reading/writing properties.",
     ["navigation", "layers", "properties"]),
    ("Devices-Numbering-and-Cabinet",
     "Renumbering devices/pages/cables/terminals/connections, device lists, and cabinet/segment calculations.",
     ["renumber", "devicelist", "cabinet", "generate"]),
    ("Search-Tools",
     "Full-text and property search across a project.",
     ["search"]),
    ("Import-Export-and-Data-Exchange",
     "Every format in and out of a project: PDF/DXF/DWG/graphics/PXF exports, DC/XML data exchange, PLC, parts management, macros, ribbon, production data, labels.",
     ["export_", "import_", "data_exchange", "plc", "partsmanagement", "parts", "macros", "ribbon", "production", "labels", "settings"]),
    ("Reports-Verification-and-Printing",
     "Updating reports/evaluations, model views, project/page verification, and printing.",
     ["reports", "verify", "print_"]),
    ("3D-and-Installation-Spaces",
     "Headless 3D installation space creation and macro insertion.",
     ["e3d"]),
    ("Live-DataModel-Tools",
     "Read/edit the open project's live object model via runtime reflection, working around a script-engine limitation on static `using` directives.",
     ["live"]),
    ("Discovery-Tools",
     "Enumerate real EPLAN catalogs (schemes, report templates, layers, settings tree, .NET enums) instead of guessing values.",
     ["discovery"]),
    ("Low-Level-Scripted-Tools",
     "Parts-database CRUD, the settings tree (get/set string/bool/int/double), PathMap variable substitution, arbitrary custom C# script execution, and the system message tree.",
     ["scripted"]),
    ("Addons-and-Raw-Actions",
     "Loading API add-in modules, registering/unregistering add-ons, and executing a raw EPLAN action string directly.",
     ["addons"]),
]

MODULE_TO_CATEGORY_ORDER = {}
for cat, _, mods in CATEGORIES:
    for m in mods:
        MODULE_TO_CATEGORY_ORDER[m] = cat


def first_doc_line(node):
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()


def full_doc(node):
    return ast.get_docstring(node) or ""


def signature(node):
    args = []
    a = node.args
    defaults = [None] * (len(a.args) - len(a.defaults)) + list(a.defaults)
    for arg, default in zip(a.args, defaults):
        ann = ""
        if arg.annotation is not None:
            try:
                ann = ": " + ast.unparse(arg.annotation)
            except Exception:
                ann = ""
        if default is not None:
            try:
                dv = ast.unparse(default)
            except Exception:
                dv = "..."
            args.append(f"{arg.arg}{ann}={dv}")
        else:
            args.append(f"{arg.arg}{ann}")
    return ", ".join(args)


def load_all_names_and_modules():
    init_path = os.path.join(ACTIONS_DIR, "__init__.py")
    init_src = open(init_path, encoding="utf-8").read()
    init_tree = ast.parse(init_src)

    all_names = []
    for node in ast.walk(init_tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in node.targets):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant):
                    all_names.append(elt.value)

    name_to_module = {}
    for node in ast.walk(init_tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 1:
            for alias in node.names:
                imported_name = alias.asname or alias.name
                name_to_module[imported_name] = node.module
    return all_names, name_to_module


def load_module_funcs():
    module_funcs = {}
    for fname in os.listdir(ACTIONS_DIR):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        mod = fname[:-3]
        path = os.path.join(ACTIONS_DIR, fname)
        tree = ast.parse(open(path, encoding="utf-8").read())
        funcs = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                funcs[node.name] = node
        module_funcs[mod] = funcs
    return module_funcs


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_names, name_to_module = load_all_names_and_modules()
    module_funcs = load_module_funcs()

    by_category = {cat: [] for cat, _, _ in CATEGORIES}
    for name in all_names:
        mod = name_to_module.get(name)
        cat = MODULE_TO_CATEGORY_ORDER.get(mod)
        if cat is None:
            continue
        node = module_funcs.get(mod, {}).get(name)
        if node is None:
            continue
        by_category[cat].append((name, node))

    total_written = 0
    for cat, blurb, mods in CATEGORIES:
        entries = by_category[cat]
        path = os.path.join(OUT_DIR, f"{cat}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {cat.replace('-', ' ')}\n\n")
            f.write(f"{blurb}\n\n")
            f.write(f"**{len(entries)} tools** (all prefixed `eplan_` when registered as MCP tools).\n\n")
            f.write("[< Back to Home](Home)\n\n---\n\n")
            for name, node in entries:
                sig = signature(node)
                doc = full_doc(node).strip()
                f.write(f"## `eplan_{name}`\n\n")
                f.write(f"```python\neplan_{name}({sig})\n```\n\n")
                if doc:
                    f.write(doc + "\n\n")
                f.write("---\n\n")
        total_written += len(entries)
        print(f"wrote {path} ({len(entries)} tools)")

    print(f"\nTotal tools written across category pages: {total_written} / {len(all_names)} in __all__")


if __name__ == "__main__":
    main()
