r"""
Scratch symbol-library isolation: make a symbol-writing test unable to reach production libraries.

WHY. EPLAN resolves a project's symbol libraries by NAME against $(MD_SYMBOLS):

    Project.SymbolLibraries -> ["My Library", ...] -> "<$(MD_SYMBOLS)>\My Library.slk"

so cloning the project does not isolate its libraries. Two dead ends:
`Project.SymbolLibraries` is get-only, and the project setting
`PROJECT.TrDMProject.EmbeddedMasterDataLibraries.SymbolLibs` takes a bare name only (an absolute
path makes the project report "incomplete").

What works is moving the resolution ROOT. $(MD_SYMBOLS) comes from the user setting
`USER.TrDMProject.Masterdata.Pathnames.Symbols`, which is writable and restorable:

    copy every library the project needs into a scratch directory
    -> point that user setting at the scratch directory
    -> reopen the project (Project.SymbolLibraries is cached)
    -> every bare name now resolves inside the scratch directory

SCOPE. The redirect is a USER setting: while active it affects this workstation's EPLAN globally.
scratch_symbols_create records the previous value in symbols_redirect.json under the scratch
root, scratch_symbols_restore puts it back, scratch_symbols_status reports a redirect left by a
crashed run, and a second redirect on top of an active one is refused (the original value would
be lost).

LIBRARY SOURCE. Which libraries the open project uses, with their resolved paths, needs a reader
inside EPLAN. An extension supplies it in an isolation preset
(eplan_mcp.ext.register_isolation_preset) as a callable "project_libraries" returning
(libraries, error, project) where libraries is [{"name", "path", "exists"}]. Without one,
scratch_symbols_create needs explicit `libraries` paths and assert_isolation cannot run.
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import time

SYMBOLS_PATH_SETTING = "USER.TrDMProject.Masterdata.Pathnames.Symbols"
STATE_FILE = "symbols_redirect.json"
# Scratch symbol copies live in their own folder under the scratch root, apart from scratch
# projects, so purge can never reach anything else.
SYMBOLS_SUBDIR = "symbols"
DEFAULT_PREFIX = "symbols_scratch"
SDB_EXT = ".sdb"

# name -> settings: {"project_libraries": callable, "current_project": callable,
#                    "protected_roots": [paths], "dir_prefix": str, "symbols_setting": str}
_PRESETS = {}


def register_preset(name: str, settings: dict) -> None:
    """Register (or replace) an isolation preset."""
    _PRESETS[name] = dict(settings or {})


def _preset(name):
    """(settings, None) or (None, error dict). No name: the only registered preset, else {}."""
    if name:
        if name not in _PRESETS:
            return None, {"success": False,
                          "error": "unknown isolation preset %r; known: %s"
                                   % (name, ", ".join(sorted(_PRESETS)) or "none")}
        return _PRESETS[name], None
    if len(_PRESETS) == 1:
        return next(iter(_PRESETS.values())), None
    return {}, None


def _setting(p):
    return p.get("symbols_setting") or SYMBOLS_PATH_SETTING


def _scratch_root() -> str:
    root = os.environ.get("EPLAN_MCP_SCRATCH") or os.path.join(
        tempfile.gettempdir(), "eplan_mcp_scratch")
    os.makedirs(root, exist_ok=True)
    return root


def _symbols_root() -> str:
    root = os.path.join(_scratch_root(), SYMBOLS_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def _strictly_under(path, root):
    """Inside root and not root itself."""
    return _under(path, root) and _norm(path) != _norm(root)


def _norm(p):
    return os.path.normcase(os.path.normpath(p or ""))


def _under(path, root):
    path, root = _norm(path), _norm(root)
    return bool(path) and bool(root) and (path == root or path.startswith(root.rstrip("\\/") + os.sep))


def _state_path() -> str:
    return os.path.join(_scratch_root(), STATE_FILE)


def _read_state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_state(state) -> None:
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _clear_state() -> None:
    try:
        os.remove(_state_path())
    except Exception:
        pass


def _get_symbols_path(setting=SYMBOLS_PATH_SETTING):
    """Current $(MD_SYMBOLS) root, or (None, error)."""
    from .scripted import settings_get_string
    try:
        r = settings_get_string(setting)
    except Exception as ex:
        return None, "settings_get_string threw: %r" % (ex,)
    inner = r.get("results", r) if isinstance(r, dict) else {}
    if not inner.get("success"):
        return None, "could not read %s: %s" % (setting, inner)
    return inner.get("value"), None


def _set_symbols_path(value: str, setting=SYMBOLS_PATH_SETTING):
    from .scripted import settings_set_string
    try:
        r = settings_set_string(setting, value)
    except Exception as ex:
        return "settings_set_string threw: %r" % (ex,)
    inner = r.get("results", r) if isinstance(r, dict) else {}
    if not inner.get("success"):
        return "could not write %s: %s" % (setting, inner)
    # Read back: a settings write can report success and not stick.
    got, err = _get_symbols_path(setting)
    if err:
        return err
    if _norm(got) != _norm(value):
        return ("write reported success but the value did not stick: wanted %r, read back %r"
                % (value, got))
    return None


def _rmtree_force(path: str) -> None:
    """rmtree that also removes read-only files (library .slk files carry the attribute and
    copy2 preserves it, which shows up as a fake "Access is denied" lock)."""
    def on_error(func, target, exc_info):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=on_error)
    else:
        shutil.rmtree(path, onerror=on_error)


def _slk_first_line(path: str):
    """Line 1 of an .slk, which names the library body directory. EPLAN writes UTF-16LE with a
    BOM; a hand-made copy may be UTF-8, so the BOM is honoured explicitly."""
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
    except Exception as ex:
        return None, "could not read %s: %r" % (path, ex)
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
                     (b"\xef\xbb\xbf", "utf-8-sig")):
        if raw.startswith(bom):
            text = raw.decode(enc, errors="replace")
            break
    else:
        text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    line = lines[0].strip() if lines else ""
    return line.lstrip("﻿"), None


def _copy_library(src_slk: str, dest_dir: str) -> dict:
    """Copy one library: <name>.slk plus the .sdb directory its line 1 names. Live .lck lock
    files are skipped (a copied lock would make the clone look busy)."""
    out = {"slk": src_slk, "copied_slk": None, "copied_sdb": None, "files": 0, "err": None}
    if not os.path.isfile(src_slk):
        out["err"] = "not a file: %s" % src_slk
        return out
    name = os.path.basename(src_slk)
    dest_slk = os.path.join(dest_dir, name)
    first_line, read_err = _slk_first_line(src_slk)
    if read_err:
        out["err"] = read_err
        return out
    sdb_name = first_line or (os.path.splitext(name)[0] + SDB_EXT)
    src_sdb = sdb_name if os.path.isabs(sdb_name) else \
        os.path.join(os.path.dirname(src_slk), sdb_name)
    if not os.path.isdir(src_sdb):
        out["err"] = "library body not found: %s (line 1 of the .slk was %r)" % (
            src_sdb, first_line)
        return out
    dest_sdb = os.path.join(dest_dir, os.path.basename(src_sdb))
    try:
        if os.path.isdir(dest_sdb):
            _rmtree_force(dest_sdb)
        shutil.copytree(src_sdb, dest_sdb, ignore=shutil.ignore_patterns("*.lck"))
        shutil.copy2(src_slk, dest_slk)
        os.chmod(dest_slk, os.stat(dest_slk).st_mode | stat.S_IWRITE)
    except Exception as ex:
        out["err"] = "copy failed: %r" % (ex,)
        return out
    out["copied_slk"] = dest_slk
    out["copied_sdb"] = dest_sdb
    out["files"] = sum(len(fs) for _, _, fs in os.walk(dest_sdb))
    return out


def _project_libraries(p):
    fn = p.get("project_libraries")
    if not callable(fn):
        return None, ("no project-library reader: register an isolation preset with a "
                      "'project_libraries' callable (eplan_mcp.ext.register_isolation_preset)"), None
    try:
        return fn()
    except Exception as ex:
        return None, "project_libraries threw: %r" % (ex,), None


def _current_project(p):
    fn = p.get("current_project")
    if callable(fn):
        return fn()
    from .project import get_current_project
    cur = get_current_project()
    return (cur.get("parameters") or {}).get("PROJECT") if cur.get("success") else None


def _reopen_focused_project(p):
    """Close and reopen the focused project so Project.SymbolLibraries re-resolves."""
    from .project import close_project, open_project
    project = _current_project(p)
    if not project:
        return {"success": False, "error": "no focused project to reopen"}
    elk = project if project.lower().endswith(".elk") else project + ".elk"
    closed = close_project()
    opened = open_project(elk)
    return {"success": bool(opened.get("success")), "project": elk,
            "closed": closed.get("success"), "opened": opened.get("success")}


def scratch_symbols_create(name: str = None, libraries: list = None,
                           reopen_project: bool = True, preset: str = None) -> dict:
    r"""
    Redirect $(MD_SYMBOLS) at a scratch directory holding copies of the open project's symbol
    libraries, so no symbol write can reach the real ones.

    Sequence: copy libraries -> repoint USER.TrDMProject.Masterdata.Pathnames.Symbols -> close
    and reopen the project (the library list is cached until a reopen) -> assert_isolation.

    REFUSES to run while a redirect from an earlier run is still recorded, because overwriting
    the saved original would lose the only record of it. See scratch_symbols_status /
    scratch_symbols_restore.

    Args:
        name: Directory name under the scratch root's "symbols" folder. Default
            "<prefix>_<stamp>". Must stay strictly inside that folder.
        libraries: Absolute .slk paths to copy. Default: every library the preset's reader
            reports for the open project.
        reopen_project: Close and reopen the focused project afterwards (default True).
            Without it the redirect has no visible effect.
        preset: Isolation preset registered by an extension (library reader, protected roots,
            directory prefix). Default: the only registered preset, if exactly one exists.

    Returns:
        {"success", "scratch_dir", "previous_symbols_path", "libraries", "reopened", "isolation"}
    """
    p, err = _preset(preset)
    if err:
        return err
    setting = _setting(p)
    existing = _read_state()
    if existing:
        return {"success": False,
                "error": "a symbols redirect is already active - restore it before creating "
                         "another, or its original value is lost",
                "state": existing}
    previous, err = _get_symbols_path(setting)
    if err:
        return {"success": False, "error": err}
    if not previous:
        return {"success": False,
                "error": "%s is empty; refusing to redirect a path we cannot restore" % setting}

    if libraries is None:
        project_libs, lib_err, _ = _project_libraries(p)
        if lib_err:
            return {"success": False, "error": lib_err}
        missing = [l.get("name") for l in project_libs if not l.get("exists")]
        if missing:
            return {"success": False,
                    "error": "the project reports libraries that do not exist on disk; fix "
                             "that before isolating", "missing": missing}
        libraries = [l.get("path") for l in project_libs if l.get("path") and l.get("exists")]
    if not libraries:
        return {"success": False, "error": "no libraries to copy - is a project open?"}

    root = _symbols_root()
    if name is None:
        name = "%s_%s" % (p.get("dir_prefix") or DEFAULT_PREFIX, time.strftime("%Y%m%d_%H%M%S"))
    scratch_dir = os.path.normpath(os.path.join(root, name))
    if not _strictly_under(scratch_dir, root):
        return {"success": False,
                "error": "name must be a directory strictly inside the scratch root's "
                         "symbols folder (%s): %r" % (root, name)}
    os.makedirs(scratch_dir, exist_ok=True)

    copied = [_copy_library(slk, scratch_dir) for slk in libraries]
    if any(c["err"] for c in copied):
        return {"success": False,
                "error": "one or more libraries could not be copied; nothing was redirected",
                "scratch_dir": scratch_dir, "libraries": copied}

    # Record the original BEFORE touching the setting: whatever happens next, restore can put
    # it back.
    _write_state({"previous_symbols_path": previous, "scratch_dir": scratch_dir,
                  "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "libraries": [c["copied_slk"] for c in copied]})
    set_err = _set_symbols_path(scratch_dir, setting)
    if set_err:
        current, _ = _get_symbols_path(setting)
        if current is not None and _norm(current) == _norm(previous):
            _clear_state()      # nothing changed; a stale record would block every later create
        return {"success": False, "error": set_err, "scratch_dir": scratch_dir,
                "libraries": copied,
                "hint": None if not _read_state() else
                "the setting may have changed; scratch_symbols_restore puts the recorded value back"}

    reopened = _reopen_focused_project(p) if reopen_project else None
    return {"success": True, "scratch_dir": scratch_dir, "previous_symbols_path": previous,
            "libraries": copied, "reopened": reopened,
            "isolation": assert_isolation(preset=preset),
            "note": "USER-level redirect: this workstation's EPLAN resolves ALL symbol libraries "
                    "here until scratch_symbols_restore."}


def scratch_symbols_restore(delete_scratch: bool = False, reopen_project: bool = True,
                            preset: str = None) -> dict:
    """
    Put $(MD_SYMBOLS) back to the value recorded by scratch_symbols_create.

    Safe when nothing is redirected (reports so), and after a crash - the original value lives
    in a file, not in this process.

    Args:
        delete_scratch: Also delete the scratch directory (default False, so a failed test's
            evidence survives).
        reopen_project: Close and reopen the focused project afterwards (default True).
        preset: Isolation preset (see scratch_symbols_create).
    """
    p, err = _preset(preset)
    if err:
        return err
    setting = _setting(p)
    state = _read_state()
    if not state:
        current, err = _get_symbols_path(setting)
        return {"success": True, "restored": False,
                "note": "no redirect was recorded; nothing to restore",
                "current_symbols_path": current, "error": err}

    previous = state.get("previous_symbols_path")
    set_err = _set_symbols_path(previous, setting)
    if set_err:
        return {"success": False, "error": set_err, "state": state,
                "hint": "the redirect is STILL ACTIVE - fix EPLAN settings before running "
                        "anything that writes symbols"}
    _clear_state()

    # Reopen before deleting, so nothing still resolves inside the directory being removed.
    reopened = _reopen_focused_project(p) if reopen_project else None
    deleted = None
    if delete_scratch and state.get("scratch_dir"):
        try:
            _rmtree_force(state["scratch_dir"])
            deleted = state["scratch_dir"]
        except Exception as ex:
            deleted = ("failed: %r - the libraries are probably still open in EPLAN; close the "
                       "project and delete %s by hand" % (ex, state["scratch_dir"]))
    return {"success": True, "restored": True, "symbols_path": previous,
            "deleted_scratch": deleted, "reopened": reopened, "was": state}


def scratch_symbols_purge(prefix: str = None, preset: str = None) -> dict:
    """
    Delete orphaned scratch symbol directories left by earlier runs (each is a full library
    copy). Only the scratch root's "symbols" folder is searched, so scratch projects and
    anything else under the scratch root are never touched (copies an older version left
    directly under the scratch root are not purged either; delete those by hand). The
    directory of the currently recorded redirect is never touched. Read-only files are cleared,
    so a "locked" entry means something really holds a file open.

    Args:
        prefix: Only directories whose name starts with this are considered (default: the
            preset's dir_prefix, else "symbols_scratch"). "" means every directory in the
            symbols folder, which is deliberately not the default.
        preset: Isolation preset (see scratch_symbols_create).
    """
    p, err = _preset(preset)
    if err:
        return err
    if prefix is None:
        prefix = p.get("dir_prefix") or DEFAULT_PREFIX
    root = _symbols_root()
    protected = _norm((_read_state() or {}).get("scratch_dir"))

    deleted, locked, errors, skipped = [], [], [], []
    for entry in sorted(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isdir(full) or not entry.startswith(prefix):
            continue
        if protected and _norm(full) == protected:
            skipped.append({"path": full, "why": "this is the active redirect"})
            continue
        try:
            _rmtree_force(full)
            deleted.append(full)
        except PermissionError:
            locked.append(full)
        except Exception as ex:
            errors.append({"path": full, "error": repr(ex)})
    return {"success": not errors, "root": root, "prefix": prefix, "deleted": deleted,
            "locked": locked, "skipped": skipped, "errors": errors,
            "note": ("%d directory/directories are locked - EPLAN still holds their libraries "
                     "open; purge again after a shutdown" % len(locked)) if locked else None}


def scratch_symbols_status(preset: str = None) -> dict:
    """
    Report whether a symbols redirect is recorded and active, and what EPLAN resolves today.
    Check it at the start of a session: a redirect left by a crashed run silently sends symbol
    reads to stale copies.

    Args:
        preset: Isolation preset (see scratch_symbols_create).
    """
    p, err = _preset(preset)
    if err:
        return err
    state = _read_state()
    current, err = _get_symbols_path(_setting(p))
    active = bool(state) and bool(current) and _norm(current) == _norm(
        (state or {}).get("scratch_dir"))
    return {"success": err is None, "error": err, "current_symbols_path": current,
            "redirect_recorded": bool(state), "redirect_active": active, "state": state,
            "warning": ("a redirect is recorded but $(MD_SYMBOLS) does not point at it - "
                        "someone changed the setting by hand") if state and not active else None}


def assert_isolation(require_root: str = None, protected_roots: list = None,
                     preset: str = None) -> dict:
    """
    THE GATE. Assert every symbol library the open project uses resolves inside the scratch
    directory and none resolves under a protected root. Treat isolated=False as an abort, not a
    warning. It reads the live library list (through the preset's reader), not the setting, so
    it also catches a redirect that is set but not yet visible because the project was never
    reopened.

    Args:
        require_root: Directory every library must sit under. Default: the scratch directory
            recorded by scratch_symbols_create.
        protected_roots: Directories no library may resolve under (e.g. the real library
            share). Added to the preset's protected_roots.
        preset: Isolation preset (see scratch_symbols_create).

    Returns:
        {"success", "isolated", "root", "project", "libraries": [{name, path, inside_root,
         exists}], "outside_root", "protected_hits", "unresolved", "reason"}
    """
    p, err = _preset(preset)
    if err:
        return err
    root = require_root or (_read_state() or {}).get("scratch_dir")
    if not root:
        return {"success": False, "isolated": False,
                "reason": "no scratch symbols directory is active and no require_root was "
                          "given - there is nothing to isolate against"}
    libs, err, project = _project_libraries(p)
    if err:
        return {"success": False, "isolated": False, "reason": err}

    guarded = list(p.get("protected_roots") or []) + list(protected_roots or [])
    rows, outside, unresolved, hits = [], [], [], []
    for l in libs:
        path = l.get("path") or ""
        inside = _under(path, root)
        row = {"name": l.get("name"), "path": path, "inside_root": inside,
               "exists": l.get("exists")}
        rows.append(row)
        if path and any(_under(path, g) for g in guarded):
            hits.append(row)
        if not path and l.get("exists") is False:
            # Listed but resolving to no file at all: nothing can be written through it.
            unresolved.append(row)
        elif not inside:
            outside.append(row)

    isolated = bool(rows) and not outside and not hits and len(unresolved) < len(rows)
    reason = None
    if not isolated:
        reason = ("%d library/libraries still resolve outside the scratch root, %d under a "
                  "protected root - ABORT any symbol-writing test. If the redirect was just "
                  "created, the project probably needs reopening (Project.SymbolLibraries is "
                  "cached)." % (len(outside), len(hits)))
    return {"success": True, "isolated": isolated, "root": root, "project": project,
            "library_count": len(rows), "libraries": rows, "outside_root": outside,
            "protected_hits": hits, "unresolved": unresolved, "reason": reason}


# Flags for tool_annotations: the redirect is an EPLAN setting ($(MD_SYMBOLS)).
scratch_symbols_status.__tool_flags__ = "read"
assert_isolation.__tool_flags__ = "read"
scratch_symbols_create.__tool_flags__ = "eplan"
scratch_symbols_purge.__tool_flags__ = "eplan destructive"
scratch_symbols_restore.__tool_flags__ = "eplan destructive"
