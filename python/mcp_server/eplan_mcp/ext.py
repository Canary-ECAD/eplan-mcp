"""
The extension API: the only contract between this server and an extension pack.

An extension is a folder of *.py files named in EPLAN_MCP_EXTENSIONS. Each file declares

    TOOL_PREFIX = "acme_"           # its tools become acme_<name>
    EXT_API = (1, 1)                # the range of EXT_API_VERSION it was written for
    __all__ = ["my_tool", ...]      # plain functions; docstring + type hints become the tool

and uses only what is below. The server refuses an extension whose EXT_API range does not
include EXT_API_VERSION, with a plain message, instead of loading it half-working. Anything not
in this module is internal and may change in any release.

Bump EXT_API_VERSION when a function here changes incompatibly; add functions freely.
"""

import os

EXT_API_VERSION = 1


def compatible(declared) -> bool:
    """True when an extension's EXT_API (min, max) - or a single int - includes this version.
    An extension that declares nothing is assumed to be written for version 1."""
    if declared is None:
        declared = (1, 1)
    if isinstance(declared, int):
        declared = (declared, declared)
    lo, hi = declared
    return lo <= EXT_API_VERSION <= hi


def manager():
    """The connected EPLAN connection manager, or raise RuntimeError with a plain message."""
    from api.actions._base import _get_connected_manager
    m, error = _get_connected_manager()
    if error:
        raise RuntimeError(error.get("message") or "Not connected to EPLAN.")
    return m


def run_action(action: str, direct: bool = False, timeout: float = None) -> dict:
    """Run one EPLAN action string. direct=True skips the quiet-mode script wrapper (needed for
    .NET 8 add-in actions that lock objects, S511176)."""
    m = manager()
    kwargs = {"timeout": timeout} if timeout else {}
    return m.execute_action(action, quiet_mode=not direct, **kwargs)


def run_script(code: str = None, script: str = None, args: dict = None, project: str = None,
               **options) -> dict:
    """Compile and run a C# script in EPLAN through the script host (see scripthost.script_run
    for every option). Returns the result envelope."""
    from api.actions import scripthost
    return scripthost.script_run(code=code, script=script, args=args, project=project, **options)


def register_script_dir(path: str, helpers: list = None, prefix: str = "eplan_") -> None:
    """Add a folder of .cs scripts to the script library. `helpers` are .cs files compiled into
    every script from that folder (an extension's own helper library); `prefix` names the
    script tools from that folder (use the extension's TOOL_PREFIX)."""
    from api.actions import scripthost
    scripthost.register_script_dir(path, helpers=helpers, prefix=prefix)


def scratch_root() -> str:
    """Where scratch clones live (EPLAN_MCP_SCRATCH)."""
    from api.actions import fixtures
    return fixtures.SCRATCH_ROOT


def config_dir(extension_file: str) -> str:
    """The folder of an extension module, for its own presets and manifests."""
    return os.path.dirname(os.path.abspath(extension_file))


def register_addin_manifest(name: str, manifest) -> None:
    """Make an add-in manifest callable by name in eplan_addin_build / _deploy / _update /
    eplan_list_addin_actions. `manifest` is a dict or a path to a JSON file; relative paths in it
    resolve against its "root" (a dict's root defaults to the current directory, a file's to the
    file's folder). Format: api/actions/addin_dev.py. Re-registering a name replaces it."""
    from api.actions import addin_dev
    addin_dev.register_manifest(name, manifest)


def register_dialog_preset(name: str, rules: list) -> None:
    """Register a named rule set for eplan_ui_dismiss_watch_start(preset=name): a list of
    {"title_regex", "button_name"} dicts (both regexes), each pairing a dialog caption with its
    safest button. Raises ValueError on a malformed rule. Re-registering a name replaces it."""
    from api.actions import ui_automation
    ui_automation.register_preset(name, rules)


def register_isolation_preset(name: str, settings: dict) -> None:
    """Register settings for the eplan_scratch_symbols_* / eplan_assert_isolation tools, picked
    with preset=name (or used by default when it is the only one). Keys, all optional:
    "project_libraries" - callable returning (libraries, error, project), libraries being
        [{"name", "path", "exists"}] read live from the open project (required for
        assert_isolation and for scratch_symbols_create without explicit libraries);
    "current_project" - callable returning the focused project path (default:
        eplan_get_current_project);
    "protected_roots" - folders no library may resolve under while isolated;
    "dir_prefix" - scratch directory name prefix (default "symbols_scratch");
    "symbols_setting" - the user setting holding $(MD_SYMBOLS) (default
        USER.TrDMProject.Masterdata.Pathnames.Symbols).
    Re-registering a name replaces it."""
    from api.actions import symbol_isolation
    symbol_isolation.register_preset(name, settings)
