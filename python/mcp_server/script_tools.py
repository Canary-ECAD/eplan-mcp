"""
Library scripts as MCP tools, and the script host's MCP resources.

Every .cs file in a script library with a `// @tool name` header can become its own tool. They are
always indexed in the tool registry (so discovery mode's eplan_tools_search finds them), but only
PUBLISHED as separate tools when EPLAN_MCP_SCRIPT_TOOLS=publish: dozens of per-script tools would
otherwise crowd every request. Without publishing, run any of them with
eplan_script_run(script="<name>") after eplan_script_list.

Header -> tool:
    // @tool   name          tool name (prefixed with the library's prefix, "eplan_" for the public one)
    // @desc   ...           description
    // @arg    name type [optional|required] [default=x] description
    // @writes true|false    only an explicit `false` (and no @unsafe) makes the tool read-only

A tool that may write (no `@writes false`) defaults to dry_run=True, like the other writing tools:
the first call shows what would change and changes nothing. A published script tool has no
allow_real_project, so it writes only to scratch clones (eplan_scratch_project_create);
eplan_script_run keeps dry_run=False as its default and is the path for real-project writes.

The run parameters project, dry_run, budget_seconds and wait_seconds are reserved; a script that
declares an @arg with one of those names is skipped (with a message on stderr), as is one whose
header cannot be read or turned into a tool. One bad script never stops the server.
"""

import inspect
import os
import sys
import types

from api.actions import scripthost

RESERVED = ("project", "dry_run", "budget_seconds", "wait_seconds")

_TYPES = {"string": str, "int": int, "number": float, "bool": bool, "list": list, "enum": str}


def _parse_arg(spec: str) -> dict:
    words = spec.split()
    arg = {"name": words[0], "type": "string", "required": False, "default": None, "desc": ""}
    if len(words) > 1:
        t = words[1]
        arg["type"] = "enum" if t.lower().startswith("enum(") else t.lower()
        arg["choices"] = t[5:-1].split(",") if arg["type"] == "enum" else None
    rest = []
    for w in words[2:]:
        if w.lower() == "required":
            arg["required"] = True
        elif w.lower() == "optional":
            arg["required"] = False
        elif w.lower().startswith("default="):
            arg["default"] = w[8:]
        else:
            rest.append(w)
    arg["desc"] = " ".join(rest)
    return arg


def make_tool(path: str, header: dict):
    """A plain function whose signature mirrors the script's @arg lines."""
    args = [_parse_arg(a) for a in header.get("args", [])]
    bad = [a["name"] for a in args if not a["name"].isidentifier() or a["name"].startswith("_")]
    if bad:
        raise ValueError("@arg name(s) %s must be identifiers not starting with '_'" % ", ".join(bad))
    reserved = [a["name"] for a in args if a["name"] in RESERVED]
    if reserved:
        raise ValueError("@arg %s is reserved for the run itself (%s)"
                         % (", ".join(reserved), ", ".join(RESERVED)))
    params = []
    for a in args:
        py_type = _TYPES.get(a["type"], str)
        default = inspect.Parameter.empty if a["required"] else a["default"]
        params.append(inspect.Parameter(a["name"], inspect.Parameter.KEYWORD_ONLY,
                                        default=default, annotation=py_type if a["required"] else py_type | None))
    # Read-only only on an explicit `@writes false`: a missing header line means "may write".
    read_only = header.get("writes") is False and "unsafe" not in header
    for name, typ, default in (("project", str | None, None), ("dry_run", bool, not read_only),
                               ("budget_seconds", float, 120.0), ("wait_seconds", float, 60.0)):
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=typ))
    arg_names = [a["name"] for a in args]

    def tool(**kwargs) -> dict:
        script_args = {k: kwargs[k] for k in arg_names if kwargs.get(k) is not None}
        return scripthost.script_run(script=path, args=script_args, project=kwargs.get("project"),
                                     dry_run=kwargs.get("dry_run", not read_only),
                                     budget_seconds=kwargs.get("budget_seconds", 120.0),
                                     wait_seconds=kwargs.get("wait_seconds", 60.0))

    tool.__signature__ = inspect.Signature(params, return_annotation=dict)
    tool.__annotations__ = {p.name: p.annotation for p in params} | {"return": dict}
    lines = [header.get("desc") or f"Run the {header.get('tool')} script."]
    if args:
        lines.append("\nArgs:")
        lines += [f"    {a['name']}: {a['desc']}" + (f" One of: {', '.join(a['choices'])}." if a.get("choices") else "")
                  for a in args]
    lines.append("    project: .elk path or project name; default the target project when one is set,"
                 " else the focused or only open project.")
    if not read_only:
        lines.append("    dry_run: True (default) shows what would change and changes nothing; pass False to apply."
                     " Writes reach only scratch clones (eplan_scratch_project_create).")
    lines.append(f"\nScript: {path}")
    tool.__doc__ = "\n".join(lines)
    tool.__name__ = header.get("tool") or "script"
    # Flags for tool_annotations, from the header: a writer changes the project; one that also
    # uses unsafe calls (outside the write guard) may change anything in it.
    tool.__tool_flags__ = ("read" if read_only else
                           "project destructive" if "unsafe" in header else "project")
    return tool


def library():
    """(prefix, path, header) for every script with a @tool header, public library first."""
    out = []
    for d in scripthost._script_dirs():
        prefix = scripthost._prefix_for_dir(d)
        for f in sorted(os.listdir(d)):
            if f.endswith(".cs") and not f.startswith("_"):
                path = os.path.join(d, f)
                try:
                    header = scripthost._parse_header(scripthost._read(path))
                except Exception as e:  # noqa: BLE001 - one bad script must not stop the server
                    print("eplan-mcp: skipping script %s: %s" % (path, e), file=sys.stderr)
                    continue
                if header.get("tool"):
                    out.append((prefix, path, header))
    return out


def register(app, registry, mode, register_fn):
    """Index (and, on opt-in, publish) one tool per library script."""
    publish = os.environ.get("EPLAN_MCP_SCRIPT_TOOLS", "").lower() == "publish"
    taken = set(app._tool_manager._tools) if app is not None else set()
    if registry is not None:
        taken |= set(registry.names())     # hidden (discovery-mode) tools count too
    by_prefix = {}
    registered = []
    for prefix, path, header in library():
        name = header["tool"]
        ns = by_prefix.setdefault(prefix, types.SimpleNamespace(__all__=[]))
        if f"{prefix}{name}" in taken or name in ns.__all__:
            continue          # a real tool of that name wins; never shadow one
        try:
            tool = make_tool(path, header)
        except Exception as e:  # noqa: BLE001 - bad @arg lines: skip this script, keep the rest
            print("eplan-mcp: skipping script %s: %s" % (path, e), file=sys.stderr)
            continue
        setattr(ns, name, tool)
        ns.__all__.append(name)
        registered.append(f"{prefix}{name}")
    # Full mode has no search tool, so an unpublished tool there would be unreachable: index only
    # in discovery mode (searchable) or when publishing. script_list / script_run always work.
    if publish or mode == "discovery":
        for prefix, ns in by_prefix.items():
            register_fn(ns, prefix=prefix, app=app, registry=registry, mode=mode, publish=publish)
    return registered


def register_resources(app):
    """Script sources, run results and the scripting guide as MCP resources: large data costs no
    context until the agent asks for it."""

    @app.resource("eplan-script://library/{name}", mime_type="text/x-csharp",
                  description="Source of a library script (see eplan_script_list).")
    def library_source(name: str) -> str:
        path, source = scripthost._resolve_script(name)
        return source

    @app.resource("eplan-script://runs/{run_id}/result", mime_type="application/json",
                  description="Full result of a script run, including large results kept out of the reply.")
    def run_result(run_id: str) -> str:
        return scripthost.read_run_file(run_id, "result.json")

    @app.resource("eplan-script://runs/{run_id}/data", mime_type="application/json",
                  description="The large-result file of a run (result_file in the reply).")
    def run_data(run_id: str) -> str:
        return scripthost.read_run_file(run_id, "result_data.json")

    @app.resource("eplan-help://scripting-guide", mime_type="text/markdown",
                  description="How to write EPLAN scripts for the script host: ctx, headers, writes, helpers.")
    def scripting_guide() -> str:
        with open(os.path.join(scripthost.DOTNET_DIR, "SCRIPTING.md"), encoding="utf-8") as f:
            return f.read()

    return ["eplan-script://library/{name}", "eplan-script://runs/{run_id}/result",
            "eplan-script://runs/{run_id}/data", "eplan-help://scripting-guide"]
