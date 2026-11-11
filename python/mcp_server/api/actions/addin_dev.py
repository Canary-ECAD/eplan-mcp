"""
Add-in development loop: build, deploy, restart EPLAN, verify the actions loaded.

The repo being developed is described by a MANIFEST, so nothing here knows any particular add-in.
The published tools take only a manifest NAME that an extension registered with
eplan_mcp.ext.register_addin_manifest (a dict or a JSON file): a manifest names the commands that
build and deploy, so the model must not be able to point one at an arbitrary file. Extension code
may also pass a manifest dict, or load a file with load_manifest_file(). Format:

    {
      "root": "..",                                   # optional; relative to the manifest file
      "projects": {"MyAddin": "src/MyAddin/MyAddin.csproj"},
      "deploy": {"command": ["cmd", "/c", "{root}/scripts/Deploy.bat"],
                 "cwd": "{root}/scripts",
                 "summary_regex": "RESULT:|FAILED",   # optional; default: output tail
                 "timeout_s": 600},                    # optional
      "actions_prefix": "MyCo_",
      "source_dirs": ["src"],
      "verify_actions": ["MyCo_Run"]                   # optional; see addin_update
    }

Relative paths resolve against "root" (default: the manifest file's folder); "{root}" is
substituted in the deploy command and cwd.

Nothing deploys unless asked: addin_build only compiles (which can still run build code from the
project's MSBuild targets), addin_deploy runs exactly the manifest's deploy command, and
addin_update deploys only with do_deploy=True and restarts EPLAN only with restart=True.
"""

import json
import os
import re
import subprocess

# name -> manifest dict (with "root" already absolute) or path to a manifest file.
_MANIFESTS = {}

_IDENT = re.compile(r"[A-Za-z0-9_]+")


def register_manifest(name: str, manifest) -> None:
    """Make `manifest` (a dict or a path to a JSON file) callable by `name`. Re-registering a
    name replaces it."""
    if isinstance(manifest, dict):
        manifest = dict(manifest)
        manifest["root"] = os.path.abspath(manifest.get("root") or os.getcwd())
    else:
        manifest = os.path.abspath(str(manifest))
    _MANIFESTS[name] = manifest


def _load_manifest(manifest):
    """(manifest dict with absolute root, None) or (None, error dict). Accepts a registered name
    or a dict (Python callers only: MCP types the parameter as a string). Never a file path."""
    if isinstance(manifest, dict):
        m = dict(manifest)
        m["root"] = os.path.abspath(m.get("root") or os.getcwd())
        return m, None
    known = ", ".join(sorted(_MANIFESTS)) or "none registered"
    if not manifest or not isinstance(manifest, str) or manifest not in _MANIFESTS:
        return None, {"success": False,
                      "error": "manifest must be a registered manifest name (%s). A manifest file "
                               "is registered by an extension (eplan_mcp.ext."
                               "register_addin_manifest), not passed by path." % known}
    source = _MANIFESTS[manifest]
    if isinstance(source, dict):
        return dict(source), None
    return load_manifest_file(source)


def load_manifest_file(source: str):
    """(manifest dict with absolute root, None) or (None, error dict) from a JSON file. For
    extension code; the published tools take registered names only."""
    if not os.path.isfile(source):
        return None, {"success": False, "error": "Manifest file not found: %s" % source}
    try:
        with open(source, encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:
        return None, {"success": False, "error": "Unreadable manifest %s: %s" % (source, e)}
    if not isinstance(m, dict):
        return None, {"success": False, "error": "Manifest %s is not a JSON object." % source}
    m["root"] = os.path.abspath(os.path.join(os.path.dirname(source), m.get("root") or "."))
    return m, None


def _path(m: dict, p: str) -> str:
    p = str(p).replace("{root}", m["root"])
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(m["root"], p))


def addin_build(manifest: str, projects: list = None, configuration: str = "Release") -> dict:
    """
    dotnet build the add-in project(s) a manifest lists. Nothing is deployed, but a build runs
    the projects' MSBuild targets, which can execute build code - so this is not read-only.

    Args:
        manifest: The name an extension registered the manifest under.
        projects: Project names from the manifest's "projects" to build. Default: all of them.
        configuration: "Release" (default) or "Debug". Deploy scripts usually ship Release, so a
            Debug build followed by a deploy can ship a stale Release DLL.

    Returns:
        {"success", "configuration", "projects": {name: {"success", "exit_code", "output"}}}
        where "output" keeps only warning/error/summary lines.
    """
    m, err = _load_manifest(manifest)
    if err:
        return err
    known = m.get("projects") or {}
    if isinstance(projects, str):
        projects = [projects]
    unknown = [p for p in (projects or []) if p not in known]
    if unknown or not known:
        return {"success": False,
                "error": "Unknown project(s) %s. Choose from: %s"
                         % (", ".join(map(repr, unknown)) or "(manifest lists none)",
                            ", ".join(known) or "-")}
    targets = {n: known[n] for n in (projects or known)}

    results = {}
    for name, rel in targets.items():
        csproj = _path(m, rel)
        if not os.path.exists(csproj):
            results[name] = {"success": False, "error": "csproj not found: %s" % csproj}
            continue
        try:
            proc = subprocess.run(
                ["dotnet", "build", csproj, "-c", configuration, "--nologo", "-v", "minimal"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                stdin=subprocess.DEVNULL, timeout=600)
            out = (proc.stdout or "") + (proc.stderr or "")
            interesting = [l for l in out.splitlines()
                           if re.search(r"error|warning|Build succeeded|Build FAILED|\d+ Error",
                                        l, re.I)]
            results[name] = {"success": proc.returncode == 0, "exit_code": proc.returncode,
                             "output": interesting[-40:]}
        except Exception as e:
            results[name] = {"success": False, "error": str(e)}

    return {"success": all(r.get("success") for r in results.values()),
            "configuration": configuration, "projects": results}


def addin_deploy(manifest: str) -> dict:
    """
    Run the manifest's deploy command (e.g. a script that copies the built DLLs to the path
    EPLAN loads add-ins from).

    Deploying can replace files other EPLAN users load, so run this only when the user asked for
    a deploy, and only for a build that compiles cleanly. A deployed DLL takes effect in an EPLAN
    instance at its next start (re-registering does not reload it); addin_update also recycles
    the local instance.

    Args:
        manifest: The name an extension registered the manifest under.

    Returns:
        {"success", "exit_code", "summary": [lines]} - summary is the lines matching the
        manifest's deploy.summary_regex, or the last 40 output lines when it has none.
    """
    m, err = _load_manifest(manifest)
    if err:
        return err
    spec = m.get("deploy") or {}
    command = spec.get("command")
    if not command or not isinstance(command, list):
        return {"success": False, "error": "The manifest has no deploy.command list."}
    # A "{root}" argument is a path: normalise it, since cmd.exe mis-parses mixed slashes.
    command = [_path(m, c) if "{root}" in str(c) else str(c) for c in command]
    for arg in command[1:]:
        if os.path.splitext(arg)[1].lower() in (".bat", ".cmd", ".ps1", ".py", ".exe") \
                and not os.path.exists(_path(m, arg)):
            return {"success": False, "error": "Deploy script not found: %s" % _path(m, arg)}
    cwd = _path(m, spec["cwd"]) if spec.get("cwd") else m["root"]
    if not os.path.isdir(cwd):
        return {"success": False, "error": "Deploy cwd not found: %s" % cwd}
    try:
        # stdin=DEVNULL makes a trailing pause/countdown in the script exit instead of blocking.
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=float(spec.get("timeout_s", 600)),
                              stdin=subprocess.DEVNULL, cwd=cwd)
    except Exception as e:
        return {"success": False, "error": str(e)}
    lines = [l.rstrip() for l in ((proc.stdout or "") + (proc.stderr or "")).splitlines()]
    rx = spec.get("summary_regex")
    summary = [l for l in lines if re.search(rx, l)] if rx else lines[-40:]
    return {"success": proc.returncode == 0, "exit_code": proc.returncode, "summary": summary}


def list_addin_actions(prefix: str = None, source_dirs: list = None,
                       manifest: str = None) -> dict:
    """
    List the action names an add-in's C# source declares: every quoted "<prefix>..." string in
    *.cs under source_dirs (bin/obj skipped). Purely static, no EPLAN needed.

    The list is a superset - names that appear only in log or doc strings are included - so
    compare it with eplan_verify_actions to spot add-ins that failed to load or stale DLLs.

    Args:
        prefix: Action-name prefix, e.g. "MyCo_". Default: the manifest's actions_prefix.
        source_dirs: Folders to scan. Default: the manifest's source_dirs.
        manifest: Optional registered manifest name supplying the defaults above.

    Returns:
        {"success", "prefix", "actions": [names]}
    """
    root = None
    if manifest:
        m, err = _load_manifest(manifest)
        if err:
            return err
        prefix = prefix or m.get("actions_prefix")
        source_dirs = source_dirs or [_path(m, d) for d in (m.get("source_dirs") or [])]
        root = m["root"]
    if not prefix or not _IDENT.fullmatch(prefix):
        return {"success": False, "error": "prefix is required (letters, digits, underscore)."}
    if not source_dirs:
        return {"success": False, "error": "source_dirs is required."}
    if isinstance(source_dirs, str):
        source_dirs = [source_dirs]

    pattern = re.compile(r'"(%s[A-Za-z0-9_]*)"' % re.escape(prefix))
    names, missing = set(), []
    for src in source_dirs:
        src = src if os.path.isabs(src) or not root else os.path.join(root, src)
        if not os.path.isdir(src):
            missing.append(src)
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in ("bin", "obj", ".vs")]
            for fn in filenames:
                if fn.endswith(".cs"):
                    try:
                        with open(os.path.join(dirpath, fn), encoding="utf-8",
                                  errors="ignore") as f:
                            names.update(pattern.findall(f.read()))
                    except OSError:
                        pass
    names.discard(prefix)
    out = {"success": not missing, "prefix": prefix, "actions": sorted(names)}
    if missing:
        out["error"] = "source dir(s) not found: %s" % ", ".join(missing)
    return out


def addin_update(manifest: str, restart: bool = False, do_build: bool = True,
                 configuration: str = "Release", do_deploy: bool = False,
                 reopen_project: bool = True, verify: bool = True) -> dict:
    """
    One-shot develop-deploy-test cycle: build -> shut EPLAN down -> deploy -> relaunch EPLAN ->
    reopen the focused project -> verify the add-in's actions are registered.

    THIS CAN DEPLOY AND RESTART EPLAN. Both are opt-in: do_deploy=True runs the manifest's deploy
    command (which can replace files other EPLAN users load), restart=True exits and relaunches
    the local EPLAN. Pass them only when the user asked for a deploy / restart. With the defaults
    it builds and verifies only.

    EPLAN holds loaded add-in DLLs and only loads new code at its next start, so the local
    instance is stopped BEFORE the deploy and started after it. If the shutdown fails nothing is
    deployed.

    IMPORTANT: restart=True exits and relaunches the local EPLAN - only run it when nobody is
    mid-edit in EPLAN. A NEW action name may also need the add-in re-registered after the restart.

    Args:
        manifest: The name an extension registered the manifest under.
        restart: Recycle EPLAN around the deploy (default False).
        do_build: Build every manifest project first (default True).
        configuration: Build configuration (default "Release").
        do_deploy: Run the manifest's deploy command (default False).
        reopen_project: Reopen the previously focused project after the restart (default True).
        verify: Run eplan_verify_actions afterwards (default True) on the manifest's
            "verify_actions" list, or on list_addin_actions' names when it has none.
    """
    from .lifecycle import app_launch, app_shutdown
    from .project import get_current_project, open_project
    from .addons import verify_actions

    m, err = _load_manifest(manifest)
    if err:
        return err
    steps = {}

    if do_build:
        steps["build"] = addin_build(m, configuration=configuration)
        if not steps["build"]["success"]:
            return {"success": False, "steps": steps, "error": "Build failed - stopping."}

    previous_project = None
    if restart:
        if reopen_project:
            cur = get_current_project()
            previous_project = ((cur.get("parameters") or {}).get("PROJECT")
                                if cur.get("success") else None)
            steps["previous_project"] = previous_project
        steps["shutdown"] = app_shutdown()
        if not steps["shutdown"].get("success"):
            return {"success": False, "steps": steps,
                    "error": "EPLAN shutdown failed - not deploying against a running instance "
                             "(DLL locks)."}

    if do_deploy:
        steps["deploy"] = addin_deploy(m)

    if restart:
        steps["launch"] = app_launch()
        if not steps["launch"].get("success"):
            return {"success": False, "steps": steps,
                    "error": "EPLAN relaunch failed - see steps.launch."}
        if reopen_project and previous_project:
            cur = get_current_project()
            focused = (cur.get("parameters") or {}).get("PROJECT", "")
            if os.path.normcase(focused) != os.path.normcase(previous_project):
                steps["reopen"] = open_project(previous_project)

    if verify:
        names = m.get("verify_actions")
        if not names:
            names = list_addin_actions(manifest=m).get("actions") or []
        steps["verify"] = (verify_actions(names) if names else
                           {"success": False, "error": "No action names to verify."})

    ok = all(s.get("success", True) for s in steps.values() if isinstance(s, dict))
    return {"success": ok, "steps": steps}


# Flags for tool_annotations. A build runs MSBuild targets from the project: it may run build
# code, so it is not read-only. Deploying overwrites the add-in EPLAN loads.
addin_build.__tool_flags__ = "code"
addin_deploy.__tool_flags__ = "code eplan destructive"
addin_update.__tool_flags__ = "code eplan destructive"
list_addin_actions.__tool_flags__ = "read"
