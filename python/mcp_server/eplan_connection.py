"""
EPLAN Connection Manager
Connection to EPLAN via Remoting API (pythonnet/CLR)

Requirements:
- EPLAN installed
- pip install pythonnet

Compatibility shim. The code lives in the connection package, one module per
concern (see connection/__init__.py). Every name this module ever exported is
re-exported here, and the singleton stays here, so existing imports keep
working. A write to a name here (a test's monkeypatch) is forwarded to every
connection module that holds the same object, so the patch reaches the code
that reads it.
"""

import sys
import types
from typing import Optional

from connection import (
    action_scaffold,
    clr_bootstrap,
    dialogs,
    logs,
    manager,
    processes,
    runner,
    shaping,
    versions,
)
from connection.action_scaffold import SCRIPT_RESULT_TIMEOUT_S, cs_escape
from connection.clr_bootstrap import _select_dotnet_runtime
from connection.dialogs import (
    _KNOWN_SAFE_BUTTON,
    _SAFEST_BUTTONS,
    DIALOG_LOG,
    NEW_WINDOW_GRACE_S,
    WINDOW_HINTS,
    _history_cache,
    _history_lock,
    _new_window_grace,
    dialog_history,
    record_dialog,
)
from connection.logs import logger
from connection.manager import EPLANConnectionManager
from connection.processes import (
    _STATE_WORDS,
    EPLAN_EXE_NAME,
    _blocking_dialogs,
    _eplan_hwnds,
    _eplan_windows,
    _list_windows,
    _responding,
    _top_hwnds,
    eplan_listening_ports,
    eplan_pids,
    eplan_state,
    pid_alive,
)
from connection.runner import (
    ACTION_TIMEOUT_S,
    DIALOG_CHECK_S,
    TYPED_FAILURES,
    _dialog_failfast,
    _env_seconds,
    action_timeout_s,
    call_with_timeout,
)
from connection.shaping import (
    _NOT_LOGGED,
    INTERNAL_RESULT_FIELDS,
    LOGGED_RESULT_KEYS,
    MESSAGE_CAP,
    MESSAGE_LEVEL_RANK,
    MESSAGE_SCAN_CAP,
    RESULT_FIELD_NAMES,
    RESULT_FIELDS,
    carry_hang_note,
)
from connection.versions import PLATFORM_ROOT, _version_key, detect_installed_versions

_SUBMODULES = (action_scaffold, clr_bootstrap, dialogs, logs, manager,
               processes, runner, shaping, versions)
_MISSING = object()


class _Shim(types.ModuleType):
    def __setattr__(self, name, value):
        old = self.__dict__.get(name, _MISSING)
        super().__setattr__(name, value)
        if old is _MISSING:
            return
        # Every module bound to the old object gets the new one, as a
        # monkeypatch on the single original module would have reached it.
        for module in _SUBMODULES:
            if module.__dict__.get(name, _MISSING) is old:
                setattr(module, name, value)


sys.modules[__name__].__class__ = _Shim


# Singleton
_manager: Optional[EPLANConnectionManager] = None


def get_manager(target_version: str = None) -> EPLANConnectionManager:
    """Return the singleton connection manager.

    target_version: EPLAN major version like "2026". None = auto (newest
    installed). Once the DLLs of one version are loaded into this process,
    switching versions requires restarting the MCP server; a mismatching
    request keeps the loaded version and logs a warning.
    """
    global _manager
    if _manager is None:
        _manager = EPLANConnectionManager(target_version)
    elif target_version and str(target_version) != _manager.target_version:
        if _manager._clr_initialized:
            logger.warning(
                f"EPLAN {_manager.target_version} DLLs already loaded; "
                f"restart the MCP server to target {target_version}"
            )
        else:
            _manager = EPLANConnectionManager(target_version)
    return _manager
