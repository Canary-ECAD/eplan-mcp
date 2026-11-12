"""
Script host - run typed C# scripts inside EPLAN.

A script is ordinary C# against the EPLAN API (`using Eplan.EplApi.DataModel;` works), either a
full class with `public static object Run(ScriptContext ctx)` or just a statement body. The host
(dotnet/ in this repo) compiles it with Roslyn, checks it and runs it, so a new script needs no
build and no EPLAN restart.

The host comes in two flavors, one per framework EPLAN runs on:

    net8   EPLAN 2027+ (.NET 8): EPLAN's own Roslyn; each script runs in a collectible load
           context and is unloaded afterwards
    netfx  EPLAN 2026 (.NET Framework 4.8.1): the host brings Roslyn; a script cannot be
           unloaded there, so each distinct script stays loaded until EPLAN closes (running the
           same one again reuses it)

The flavor follows the target EPLAN (eplan_connect's target_version, else the newest install).

Two runtimes run the SAME scripts:

    addin      the EplanMcp_RunScript action of the EplanMcp.Host.AddIn add-in, started on the
               direct Remote Client path (the quiet-mode wrapper path cannot lock: S511176)
    bootstrap  a reflection-only script run with ExecuteScript that loads the host from bytes;
               needs no registration and no restart

Both need the EPLAN API developer license (the host is unsigned). `runtime="auto"` uses the
add-in when it answers EplanMcp_Hello, else the bootstrap.

Writes (D7): ad-hoc scripts may write only when the TARGET project is a scratch clone made by
scratch_project_create (it leaves a marker file), and a writing script may touch only ctx.Project. A real project needs
EPLAN_MCP_ALLOW_REAL_PROJECT_WRITES=1 in the server's environment (set by a person), a SAVED
library script, allow_real_project=True, and confirm=<the confirm_code a compile_only run of the
same script, args and helpers returned, shown to the user>; take a backup first
(eplan_backup_project). The scratch marker is a guard against mistakes, not a security boundary:
a script is C# running in EPLAN.

Runs are jobs. script_run waits up to wait_seconds and returns the result, or a run_id to follow
with script_status (progress, heartbeat) and stop with script_cancel. A script stops only where it
calls ctx.Budget.Check(): EPLAN cannot abort a running script.
"""

import hashlib
import http.client
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

from . import target
from ._base import _get_connected_manager

PROTOCOL = 1

# The host version this server is written against (<Version> in dotnet/Directory.Build.props).
# A host reporting another version still runs; script_hello adds a warning.
HOST_VERSION = "0.3.0"

# Host flavors, by the framework of the EPLAN they load in (see the module docstring).
FLAVORS = ("net8", "netfx")

# Out-of-band human switch for real-project writes: set for the server process by a person (MCP
# config or shell), never by a tool call. Read at call time.
REAL_PROJECT_SWITCH = "EPLAN_MCP_ALLOW_REAL_PROJECT_WRITES"

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
DOTNET_DIR = os.path.join(_REPO_ROOT, "dotnet")

# A git clone has no build output: the host then comes from the GitHub release host-v<version>,
# installed per version and flavor under ~/.eplan-mcp/host/<version>/<flavor>/ (see ensure_host).
# Not under AppData: see RUNS_DIR below.
REPO_URL = "https://github.com/Canary-ECAD/eplan-mcp"
# Host releases have their own tag line, so they never collide with the server's vX.Y.Z tags (which
# trigger .github/workflows/release.yml) and the two version numbers can move independently.
HOST_TAG_PREFIX = "host-v"
INSTALL_ROOT = os.path.join(os.path.expanduser("~"), ".eplan-mcp", "host")
_OFFLINE_EXE = "EplanMcp.Host.Offline.exe"


def _target_install():
    """The EPLAN install the host will run in: eplan_connect's target version, else the newest.
    None when nothing can be detected (the check never blocks a run)."""
    try:
        from eplan_connection import get_manager, detect_installed_versions
        installs = detect_installed_versions()
        wanted = getattr(get_manager(), "target_version", None)
    except Exception:  # noqa: BLE001 - never block a run on the check itself
        return None
    chosen = next((i for i in installs if i["version"] == wanted), None) if wanted else None
    return chosen or (installs[0] if installs else None)


def _flavor() -> str:
    """The host flavor the target EPLAN loads: netfx for a .NET Framework EPLAN, else net8."""
    chosen = _target_install()
    return "netfx" if chosen and chosen.get("runtime") == "netfx" else "net8"


def _installed_dirs(version: str = HOST_VERSION, flavor: str = None):
    """(host dir, offline dir) of an installed release: the add-on zip keeps its
    EplanMcp/<version>/BIN + CFG layout under addon/, the offline zip is flat under offline/."""
    root = os.path.join(INSTALL_ROOT, version, flavor or _flavor())
    return (os.path.join(root, "addon", "EplanMcp", version, "BIN"), os.path.join(root, "offline"))


def _built_flavor(folder: str) -> str:
    """The flavor a local build wrote (eplanmcp-flavor.txt). Builds before host 0.3.0 wrote none
    and were all net8."""
    try:
        with open(os.path.join(folder, "eplanmcp-flavor.txt"), encoding="utf-8-sig") as f:
            return f.read().strip() or "net8"
    except OSError:
        return "net8"


def _pick_dir(built: str, installed: str) -> str:
    """This checkout's build when it was made for the target EPLAN's framework, else the release."""
    return built if os.path.isdir(built) and _built_flavor(built) == _flavor() else installed


def _host_dir() -> str:
    """Where the host lives (EplanMcp.Host.AddIn output: DLLs + eplanmcp-manifest.txt): the
    override, else this checkout's build of the right flavor, else the installed release."""
    return HOST_DIR or _pick_dir(os.path.join(DOTNET_DIR, "artifacts", "host"), _installed_dirs()[0])


def _offline_dir() -> str:
    return OFFLINE_DIR or _pick_dir(os.path.join(DOTNET_DIR, "artifacts", "offline"), _installed_dirs()[1])


# A person's override of the host folder, used as given whatever the target EPLAN; None picks one
# per flavor (_host_dir).
HOST_DIR = os.environ.get("EPLAN_MCP_HOST_DIR") or None

# Per-user run folders: request, result, progress, heartbeat, cancel. Never inside a checkout.
# NOT under %LOCALAPPDATA% / %APPDATA%: measured on EPLAN 2027.0.3, an ExecuteScript file path
# written in the long form C:\Users\<user>\AppData\... is silently ignored - the call "succeeds"
# and nothing runs ("The name of the script file is missing (ScriptFile)" in the system
# messages). The user profile itself, ProgramData and the 8.3-form TEMP all work.
RUNS_DIR = os.environ.get("EPLAN_MCP_RUNS_DIR") or os.path.join(os.path.expanduser("~"), ".eplan-mcp", "runs")

# Script libraries: the public one here, plus any folders an extension adds (folder -> helper
# .cs files compiled into every script from that folder), and each folder's tool-name prefix.
_extra_script_dirs = {}
_dir_prefix = {}
PUBLIC_PREFIX = "eplan_"

_jobs = {}
_jobs_lock = threading.Lock()
_addin_ok = None   # None = unknown, True/False after the first hello
_addin_checked = 0.0
_ADDIN_RECHECK_S = 600   # a "no add-in" answer is re-checked after this long


def register_script_dir(path: str, helpers: list = None, prefix: str = PUBLIC_PREFIX) -> None:
    """Add a folder of .cs scripts to the library (used by extensions through eplan_mcp.ext)."""
    path = os.path.abspath(path)
    _extra_script_dirs[path] = [os.path.abspath(h) for h in (helpers or [])]
    _dir_prefix[path] = prefix


def _prefix_for_dir(folder: str) -> str:
    """Tool-name prefix of a library folder: the extension's own, "eplan_" for the public one."""
    return _dir_prefix.get(os.path.abspath(folder), PUBLIC_PREFIX)


def read_run_file(run_id: str, name: str) -> str:
    """A file from a run's folder (result.json, result_data.json, progress.json)."""
    if not run_id or any(c in run_id for c in ("\\", "/", ":", ".")) or name not in ("result.json", "result_data.json", "progress.json"):
        raise ValueError("Bad run id or file name.")
    with _jobs_lock:
        job = _jobs.get(run_id)
    folders = [job["folder"]] if job and job.get("folder") else []
    if os.path.isdir(RUNS_DIR):
        folders += [os.path.join(RUNS_DIR, day, run_id) for day in sorted(os.listdir(RUNS_DIR), reverse=True)]
    for folder in folders:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return _read(path)
    raise FileNotFoundError(f"No {name} for run {run_id}.")


def _helpers_for(script_path: str) -> list:
    """Helper sources registered for the library folder a script lives in."""
    if not script_path:
        return []
    folder = os.path.dirname(os.path.abspath(script_path))
    return list(_extra_script_dirs.get(folder, []))


def _script_dirs():
    dirs = [os.path.join(DOTNET_DIR, "scripts")] + list(_extra_script_dirs.keys())
    for d in (os.environ.get("EPLAN_MCP_SCRIPT_DIRS") or "").split(os.pathsep):
        if d.strip():
            dirs.append(os.path.abspath(d.strip()))
    return [d for d in dirs if os.path.isdir(d)]


def _parse_header(source: str) -> dict:
    """The `// @key value` lines at the top of a script (same rules as HeaderParser.cs)."""
    header = {"args": []}
    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("//"):
            break
        body = line[2:].strip()
        if not body.startswith("@"):
            continue
        key, _, value = body[1:].partition(" ")
        key, value = key.lower(), value.strip()
        if key == "arg":
            header["args"].append(value)
        elif key == "desc":
            header["desc"] = (header.get("desc", "") + " " + value).strip()
        elif key in ("writes", "unsafe"):
            header[key] = value.split(" ")[0].lower() in ("true", "1", "yes", "")
        else:
            header[key] = value
    return header


_SCRIPT_NAME = re.compile(r"[A-Za-z0-9_.-]+")


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _in_script_dir(path: str) -> bool:
    """True when `path` (symlinks resolved) sits inside one of the library folders."""
    real = _real(path)
    for d in _script_dirs():
        root = _real(d)
        try:
            if os.path.commonpath([real, root]) == root and real != root:
                return True
        except ValueError:      # different drives
            continue
    return False


def _resolve_script(script: str):
    """A library script name, or a path to a .cs file inside a library folder. Returns
    (path, source); raises FileNotFoundError or ValueError (with a message for the caller).

    Only scripts resolved here get script_path in the request, and the host grants `// @unsafe`
    and real-project writes only to those, so a path outside the library is refused."""
    script = (script or "").strip()
    if _SCRIPT_NAME.fullmatch(script):
        name = script[:-3] if script.endswith(".cs") else script
        path = None
        for d in _script_dirs():
            candidate = os.path.join(d, name + ".cs")
            if os.path.isfile(candidate) and _in_script_dir(candidate):
                path = candidate
                break
            for f in os.listdir(d):
                if not f.endswith(".cs"):
                    continue
                try:
                    tool = _parse_header(_read(os.path.join(d, f))).get("tool")
                except ValueError:
                    continue        # an undecodable neighbour must not hide the others
                if tool == name and _in_script_dir(os.path.join(d, f)):
                    path = os.path.join(d, f)
                    break
            if path:
                break
        if not path:
            raise FileNotFoundError(f"No script named '{script}'. See script_list().")
    elif any(c in script for c in ("/", "\\", ":")):
        if not script.lower().endswith(".cs"):
            raise ValueError(f"A script path must name a .cs file: {script}")
        if not os.path.isfile(script):
            raise FileNotFoundError(f"No script file {script}.")
        if not _in_script_dir(script):
            raise ValueError(
                f"{script} is not inside a script library folder ({', '.join(_script_dirs())}). "
                "Save it there (or add the folder to EPLAN_MCP_SCRIPT_DIRS), or pass the source "
                "as code=... instead.")
        path = os.path.abspath(script)
    else:
        raise ValueError(f"Bad script name {script!r}: use letters, digits, '_', '.', '-', or a "
                         "path to a .cs file in a script library folder.")
    return path, _read(path)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} is not UTF-8 text ({e.reason} at byte {e.start}); "
                         "save it as UTF-8.") from None


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _host_version():
    try:
        with open(os.path.join(_host_dir(), "eplanmcp-version.txt"), encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return None


# --- Host install from a GitHub release -------------------------------------------------------
# Assets built by dotnet/pack/pack-release.ps1 and uploaded to the release host-v<version>.
# One set per flavor, each built on a machine with that EPLAN, with its own checksum file.
_RELEASE_ASSETS = (("EplanMcp-{v}-{f}-addon.zip", "addon"), ("EplanMcp-{v}-{f}-offline.zip", "offline"))
_RELEASE_SUMS = "SHA256SUMS-{f}.txt"
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")
_install_lock = threading.Lock()


def _release_url(version: str, name: str) -> str:
    """URL of a release asset; EPLAN_MCP_RELEASE_URL replaces the repo URL (a fork or mirror)."""
    base = (os.environ.get("EPLAN_MCP_RELEASE_URL") or REPO_URL).rstrip("/")
    return f"{base}/releases/download/{HOST_TAG_PREFIX}{version}/{name}"


def _download(url: str, dest: str, timeout: float = 120.0) -> str:
    """Stream `url` to `dest`; returns the file's SHA-256 (hex)."""
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(dest, "wb") as f:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            digest.update(chunk)
            f.write(chunk)
    return digest.hexdigest()


def _safe_extract(zip_path: str, dest: str) -> None:
    """Extract a zip, refusing it whole if any entry would land outside `dest` (zip-slip)."""
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            parts = name.split("/")
            target = os.path.realpath(os.path.join(root, *parts))
            if (name.startswith("/") or ":" in name or ".." in parts
                    or os.path.commonpath([root, target]) != root):
                raise ValueError(f"Refusing to install: zip entry {info.filename!r} in "
                                 f"{os.path.basename(zip_path)} points outside the install folder.")
        zf.extractall(root)


def _is_installed(version: str, flavor: str) -> bool:
    host, offline = _installed_dirs(version, flavor)
    return (os.path.isfile(os.path.join(host, "eplanmcp-version.txt"))
            and os.path.isfile(os.path.join(offline, _OFFLINE_EXE)))


def ensure_host(version: str = HOST_VERSION, flavor: str = None) -> dict:
    """Install the release host v<version> of `flavor` (default: the target EPLAN's) under
    INSTALL_ROOT/<version>/<flavor>, unless it is there.

    Downloads the assets and SHA256SUMS.txt, refuses on a missing or wrong checksum or an unsafe
    zip entry, extracts into a temp folder next to the target and renames it into place, so a
    failed or interrupted install leaves nothing behind. Raises OSError or ValueError."""
    if not _VERSION_RE.fullmatch(version or ""):
        raise ValueError(f"Bad host version {version!r}; expected e.g. {HOST_VERSION}.")
    flavor = flavor or _flavor()
    if flavor not in FLAVORS:
        raise ValueError(f"Bad host flavor {flavor!r}; expected one of {', '.join(FLAVORS)}.")
    host, offline = _installed_dirs(version, flavor)
    target = os.path.join(INSTALL_ROOT, version, flavor)
    sums_name = _RELEASE_SUMS.format(f=flavor)
    info = {"version": version, "flavor": flavor, "path": target, "host_dir": host, "offline_dir": offline,
            # for eplan_register_addon(install_file=...)
            "install_file": os.path.join(os.path.dirname(host), "CFG", "install.xml")}
    with _install_lock:
        if _is_installed(version, flavor):
            return dict(info, installed=False, note="Already installed.")
        if os.path.exists(target):
            raise FileExistsError(f"{target} exists but holds no complete host; delete it and retry.")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".download-", dir=INSTALL_ROOT)   # same volume: atomic rename
        try:
            sums_path = os.path.join(tmp, sums_name)
            try:
                _download(_release_url(version, sums_name), sums_path)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                raise FileNotFoundError(
                    f"No {flavor} script host is published in release {HOST_TAG_PREFIX}{version} at "
                    f"{(os.environ.get('EPLAN_MCP_RELEASE_URL') or REPO_URL).rstrip('/')}/releases "
                    f"({sums_name} is missing). Build dotnet/ on a machine with "
                    f"{'EPLAN 2026' if flavor == 'netfx' else 'EPLAN 2027'} (dotnet/pack/pack-release.ps1 "
                    "builds and prints the upload command), or set EPLAN_MCP_HOST_DIR to a built host.") from e
            sums = {}
            with open(sums_path, encoding="utf-8-sig") as f:
                for line in f.read().splitlines():
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        sums[parts[1].strip().lstrip("*")] = parts[0].lower()
            stage = os.path.join(tmp, flavor)
            for pattern, sub in _RELEASE_ASSETS:
                name = pattern.format(v=version, f=flavor)
                expected = sums.get(name)
                if not expected:
                    raise ValueError(f"Refusing to install: {sums_name} has no checksum for {name}.")
                zip_path = os.path.join(tmp, name)
                actual = _download(_release_url(version, name), zip_path)
                if actual != expected:
                    raise ValueError(f"Refusing to install: SHA-256 of {name} is {actual}, "
                                     f"{sums_name} says {expected}.")
                _safe_extract(zip_path, os.path.join(stage, sub))
            os.rename(stage, target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not _is_installed(version, flavor):
            raise FileNotFoundError(f"The release {HOST_TAG_PREFIX}{version} installed to {target} but holds no "
                                    "complete host (eplanmcp-version.txt, " + _OFFLINE_EXE + ").")
    return dict(info, installed=True)


def _auto_install(path: str) -> None:
    """Install the release when `path` is a default installed-release folder (no override, no
    local build). Any failure becomes a FileNotFoundError with the reason."""
    flavor = _flavor()
    if os.path.normcase(os.path.abspath(path)) not in {os.path.normcase(d) for d in _installed_dirs(HOST_VERSION, flavor)}:
        return
    try:
        ensure_host(HOST_VERSION, flavor)
    except (OSError, ValueError, zipfile.BadZipFile, http.client.HTTPException) as e:
        raise FileNotFoundError(f"Script host not built here and the release {HOST_TAG_PREFIX}{HOST_VERSION} "
                                f"could not be installed: {e}") from e


def script_host_install(version: str = None, flavor: str = None) -> dict:
    """
    Download and install the script host release (add-in, bootstrap and offline host) from the
    project's GitHub release host-v<version> into ~/.eplan-mcp/host/<version>/<flavor>/. Checks
    every file's SHA-256 against the release's SHA256SUMS-<flavor>.txt and refuses on a mismatch.
    A no-op when that version is already installed. Needed only for a git clone without a local
    dotnet build; script tools also run it on first use. To use the add-in runtime, register the
    returned install_file with eplan_register_addon and restart EPLAN.

    Args:
        version: Host version to install; default the version this server expects.
        flavor: "net8" (EPLAN 2027+) or "netfx" (EPLAN 2026); default the target EPLAN's.
    """
    try:
        return dict(ensure_host(version or HOST_VERSION, flavor), success=True)
    except (OSError, ValueError, zipfile.BadZipFile, http.client.HTTPException) as e:
        return {"success": False, "error": str(e)}


def _bootstrap_script(run_folder: str, mode: str, request_path: str, result_path: str) -> str:
    """Fill the bootstrap template and write it into the run folder."""
    host_dir = _host_dir()
    template = os.path.join(host_dir, "Bootstrap", "bootstrap.cs.template")
    if not os.path.isfile(template):
        _auto_install(host_dir)
    if not os.path.isfile(template):
        raise FileNotFoundError(
            f"Script host not built: {template} is missing. Run eplan_script_host_install, build "
            "dotnet/EplanMcp.sln (Release) or set EPLAN_MCP_HOST_DIR.")
    text = _read(template)
    # Verbatim C# strings (@"..."): only a double quote needs escaping.
    for key, value in (("HOST_DIR", host_dir), ("REQUEST_PATH", request_path),
                       ("RESULT_PATH", result_path), ("MODE", mode),
                       ("CORE_VERSION", _host_version() or "0.0.0")):
        text = text.replace("{{" + key + "}}", value.replace('"', '""'))
    path = os.path.join(run_folder, "bootstrap.cs")
    # With a BOM, so EPLAN's script engine reads non-ASCII paths (a user name, say) as UTF-8.
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path


# The offline host (dotnet/src/EplanMcp.Host.Offline): EPLAN's offline API in its own long-lived
# process, fed through a queue folder. No interactive EPLAN connection is needed for it.
OFFLINE_DIR = os.environ.get("EPLAN_MCP_OFFLINE_DIR") or None   # override; None: per flavor
OFFLINE_QUEUE = os.environ.get("EPLAN_MCP_OFFLINE_QUEUE") or os.path.join(
    os.path.expanduser("~"), ".eplan-mcp", "offline-queue")
_OFFLINE_STATUS_FRESH_S = 15
_OFFLINE_STOP_WAIT_S = 60.0
_offline_lock = threading.Lock()
_offline_last_pid = None    # last host pid seen: it outlives its status.json while it shuts down


def _pid_alive(pid: int) -> bool:
    """True when `pid` is a running offline host (the image name guards against pid reuse)."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x1000, False, int(pid))    # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5     # access denied: it exists, so do not start another
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return False
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower() == _OFFLINE_EXE.lower()
        return True     # alive, name unreadable: assume it is ours rather than start a second host
    finally:
        k32.CloseHandle(handle)


def _offline_host():
    """(status dict, pid alive?) of the offline host; (None, False) when none is running.

    The host's pid in status.json decides: a long run must never look like a dead host. A status
    without a pid (older host) falls back to the heartbeat's age."""
    path = os.path.join(OFFLINE_QUEUE, "status.json")
    status = None
    for _ in range(5):      # the host may be replacing the file right now (sharing violation)
        if not os.path.isfile(path):
            break
        status = _read_json(path)
        if isinstance(status, dict):
            break
        time.sleep(0.1)
    if not isinstance(status, dict):
        return None, False
    global _offline_last_pid
    pid = status.get("process_id")
    if pid:
        _offline_last_pid = pid
        return (status, True) if _pid_alive(pid) else (None, False)
    try:
        fresh = time.time() - os.path.getmtime(path) < _OFFLINE_STATUS_FRESH_S
    except OSError:
        fresh = False
    return (status, True) if fresh else (None, False)


def _offline_status():
    """The running host's status, or None. A host told to stop counts as not running."""
    status, _ = _offline_host()
    if status and os.path.exists(os.path.join(OFFLINE_QUEUE, "stop")):
        return None
    return status


def _offline_ensure(start_timeout: float = 180.0) -> dict:
    """The running offline host's status, starting it when needed. Never starts a second host
    while one is alive: a host still finishing after a stop request is waited for first."""
    with _offline_lock:
        stop = os.path.join(OFFLINE_QUEUE, "stop")
        status, alive = _offline_host()
        if alive and not os.path.exists(stop):
            return status
        if alive:
            deadline = time.time() + _OFFLINE_STOP_WAIT_S
            while alive and time.time() < deadline:
                time.sleep(1)
                _, alive = _offline_host()
            if alive:
                raise TimeoutError("The offline host is stopping (a stop was requested) and is still "
                                   "finishing a run; try again when it has exited.")
        # A host that is shutting down (stop or idle exit) deletes status.json before its process
        # ends: wait for the last pid seen too.
        deadline = time.time() + _OFFLINE_STOP_WAIT_S
        while _offline_last_pid and _pid_alive(_offline_last_pid) and time.time() < deadline:
            time.sleep(1)
        if _offline_last_pid and _pid_alive(_offline_last_pid):
            raise TimeoutError("The previous offline host (pid %s) is still shutting down; try again "
                               "when it has exited." % _offline_last_pid)
        offline_dir = _offline_dir()
        exe = os.path.join(offline_dir, _OFFLINE_EXE)
        if not os.path.isfile(exe):
            _auto_install(offline_dir)
        if not os.path.isfile(exe):
            raise FileNotFoundError(f"Offline host not built: {exe}. Run eplan_script_host_install or "
                                    "build dotnet/src/EplanMcp.Host.Offline (Release).")
        os.makedirs(OFFLINE_QUEUE, exist_ok=True)
        for leftover in (stop, os.path.join(OFFLINE_QUEUE, "status.json")):
            try:
                os.remove(leftover)
            except FileNotFoundError:
                pass
        import subprocess
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([exe, "--queue", OFFLINE_QUEUE], cwd=offline_dir, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + start_timeout
        while time.time() < deadline:
            status = _offline_status()
            if status:
                return status
            time.sleep(1)
        raise TimeoutError("The offline host did not start within %d s (EPLAN license? check the EPLAN logs)."
                           % start_timeout)


def _invoke_offline(run_id: str, request_path: str, result_path: str, timeout: float) -> dict:
    _offline_ensure()
    queue_file = os.path.join(OFFLINE_QUEUE, run_id + ".json")
    answered = False
    try:
        _write_json(queue_file, {"request": request_path, "result": result_path})
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.isfile(result_path):
                answered = True
                return {"success": True}
            time.sleep(0.25)
        return {"success": False, "message": "The offline host did not answer in time."}
    finally:
        if not answered:
            # A run that timed out or failed must not start later, unseen, when the host gets to it.
            try:
                os.remove(queue_file)
            except OSError:
                pass


def script_offline_stop() -> dict:
    """
    Stop the offline script host (it otherwise exits after 30 idle minutes). It closes EPLAN's
    offline API cleanly on its own main thread.
    """
    if not _offline_status():
        return {"success": True, "note": "The offline host is not running."}
    with open(os.path.join(OFFLINE_QUEUE, "stop"), "w", encoding="utf-8") as f:
        f.write("stop")
    return {"success": True, "note": "Stop requested; the host exits after its current run."}


def _invoke(runtime: str, mode: str, run_folder: str, request_path: str, result_path: str,
            timeout: float) -> dict:
    """Start one host call. Blocks until EPLAN returns from the action."""
    if runtime == "offline":
        return _invoke_offline(os.path.basename(run_folder), request_path, result_path, timeout)
    manager, error = _get_connected_manager()
    if error:
        return error
    if runtime == "addin":
        if mode == "hello":
            action = f'EplanMcp_Hello /result:"{result_path}"'
        else:
            action = f'EplanMcp_RunScript /request:"{request_path}" /result:"{result_path}"'
        # Direct path: an add-in action started inside the quiet-mode wrapper cannot lock.
        return manager.execute_action(action, quiet_mode=False, timeout=timeout, label="script_host")
    script = _bootstrap_script(run_folder, mode, request_path, result_path)
    return manager.execute_action(f'ExecuteScript /ScriptFile:"{script}"', timeout=timeout,
                                  label="script_host")


def _new_run_folder(run_id: str) -> str:
    folder = os.path.join(RUNS_DIR, time.strftime("%Y%m%d"), run_id)
    os.makedirs(folder, exist_ok=True)
    return folder


def _hello(runtime: str, timeout: float = 30.0) -> dict:
    run_id = "hello-" + uuid.uuid4().hex[:8]
    folder = _new_run_folder(run_id)
    result_path = os.path.join(folder, "result.json")
    try:
        call = _invoke(runtime, "hello", folder, "", result_path, timeout)
    except FileNotFoundError as e:
        return {"success": False, "runtime": runtime, "error": str(e)}
    data = _read_json(result_path)
    if data is None:
        return {"success": False, "runtime": runtime, "action_result": call,
                "error": ("No answer from the host. For runtime 'addin': is EplanMcp.Host.AddIn "
                          "registered (EplApiModuleActionNet) and EPLAN restarted? EPLAN can also "
                          "report success for a script it never ran; check eplan_get_system_messages.")}
    data["success"] = not data.get("error") or bool(data.get("core_version"))
    return data


def _pick_runtime(runtime: str) -> str:
    global _addin_ok, _addin_checked
    if runtime in ("addin", "bootstrap", "offline"):
        return runtime
    if _addin_ok is None or (not _addin_ok and time.time() - _addin_checked > _ADDIN_RECHECK_S):
        hello = _hello("addin", timeout=20.0)
        _addin_ok = bool(hello.get("success")) and hello.get("protocol") == PROTOCOL
        _addin_checked = time.time()
    return "addin" if _addin_ok else "bootstrap"


def _version_warning(data: dict) -> dict:
    """Add a warning when the host reports a core version other than HOST_VERSION."""
    reported = data.get("core_version")
    if reported and reported != HOST_VERSION:
        data["warning"] = (f"Host version {reported} differs from the version this server expects "
                           f"({HOST_VERSION}). Update the host: rebuild dotnet/ or run "
                           "eplan_script_host_install, and restart EPLAN for the add-in.")
    return data


def _unsupported_eplan() -> dict:
    """An error dict when the target EPLAN can load neither host flavor, else None.

    net8 is built against EPLAN 2027 and netfx against EPLAN 2026. EPLAN 2025 and older run on
    .NET Framework too, but their API differs from 2026's and is not tested: refused up front, with
    a reason, instead of a run that fails in some later bind.
    """
    chosen = _target_install()
    if not chosen or chosen.get("runtime") != "netfx":
        return None
    try:
        major = int(str(chosen["version"]).split(".")[0])
    except (KeyError, ValueError):
        return None
    if major >= 2026:
        return None
    return {"success": False,
            "eplan_version": chosen.get("full_version") or chosen["version"],
            "eplan_runtime": "netfx",
            "error": (f"The script host supports EPLAN 2026 (.NET Framework) and 2027 or newer "
                      f"(.NET 8). EPLAN {chosen.get('full_version') or chosen['version']} is older."),
            "next_step": ("On this EPLAN use eplan_execute_custom_script (EPLAN's own script "
                          "engine, C# 5) or the eplan_live_* tools instead.")}


def script_hello(runtime: str = "auto") -> dict:
    """
    Handshake with the script host: core version, protocol, features, EPLAN version, license and
    open projects. Call this first in a session; it also decides which runtime "auto" uses.

    Changes nothing in a project, but it is not inert: it runs a tiny hello script inside EPLAN
    (an add-in action or an ExecuteScript bootstrap), and runtime="offline" may start the offline
    host process.

    Args:
        runtime: "auto" (add-in if it answers, else bootstrap), "addin", "bootstrap" or
            "offline".
    """
    unsupported = _unsupported_eplan()
    if unsupported:
        return dict(unsupported, runtime=runtime)
    if target.get():
        # The project a run without `project` will act on.
        return dict(_hello_runtime(runtime), target_project=target.get())
    return _hello_runtime(runtime)


def _hello_runtime(runtime: str) -> dict:
    global _addin_ok
    if runtime == "offline":
        try:
            status = dict(_offline_ensure())
        except OSError as e:     # not built, did not start, queue files locked
            return {"success": False, "runtime": "offline", "error": str(e)}
        status["success"] = status.get("protocol") == PROTOCOL
        return _version_warning(status)
    if runtime == "auto":
        hello = _hello("addin", timeout=20.0)
        _addin_ok = bool(hello.get("success")) and hello.get("protocol") == PROTOCOL
        if _addin_ok:
            return _version_warning(hello)
        boot = _hello("bootstrap")
        boot["addin"] = {"available": False, "detail": hello.get("error")}
        return _version_warning(boot)
    hello = _hello(runtime)
    if runtime == "addin":
        _addin_ok = bool(hello.get("success"))
    if hello.get("success") and hello.get("protocol") != PROTOCOL:
        hello["success"] = False
        hello["error"] = (f"Host protocol {hello.get('protocol')} does not match server protocol "
                          f"{PROTOCOL}. Update the host (rebuild, restart EPLAN for the add-in).")
    return _version_warning(hello)


def script_run(code: str = None, script: str = None, args: dict = None, project: str = None,
               runtime: str = "auto", compile_only: bool = False, dry_run: bool = False,
               budget_seconds: float = 120.0, wait_seconds: float = 60.0,
               allow_real_project: bool = False, confirm: str = None,
               helpers: list = None) -> dict:
    """
    Compile and run a C# script inside EPLAN. Returns a result envelope, or a run_id to follow.

    Write a statement body, e.g. `var p = ctx.RequireProject(); return p.ProjectName;`, or a full
    class with `public static object Run(ScriptContext ctx)`. Usual usings are added for snippets.
    `ctx` gives Project, Args (String/Int/Bool/List), Budget.Check(), Progress(), Log(), Lock(obj),
    DryRun, WriteAllowed. Return plain data. The run already holds a LockingStep.

    Headers at the top (`// @writes true`, `// @arg name type ...`, `// @requires core>=0.1`)
    declare intent. A script that writes must say `// @writes true`; read-only runs reject EPLAN
    writes at compile time. Compile errors come back with your own line numbers and hints.

    Real-project writes (not a scratch clone) need all of: the environment variable
    EPLAN_MCP_ALLOW_REAL_PROJECT_WRITES=1 set for the server by a person (you cannot set it), a
    saved library script, allow_real_project=True, and confirm=<confirm_code>. Show the
    confirm_code and what the script will change to the user and get their approval before
    passing it. The scratch-clone marker is a guard against mistakes, not a security boundary.

    Args:
        code: Script source (ad-hoc). Give either code or script.
        script: A library script name (see script_list) or the path of a .cs file inside a
            script library folder.
        args: Arguments for the script (ctx.Args).
        project: .elk path or project name to act on. Default: the target project
            (live_set_target_project / EPLAN_MCP_PROJECT) when one is set, else the focused or
            only open project.
        runtime: "auto", "addin", "bootstrap", or "offline" (EPLAN's offline API in a separate
            process: no window and no interactive session needed; project must be a closed
            .elk path; scripts must declare '@needs offline' or '@needs either').
        compile_only: Compile and check only. Also returns confirm_code for real-project writes.
        dry_run: Sets ctx.DryRun; the script should report changes instead of making them.
        budget_seconds: Time limit enforced at each ctx.Budget.Check().
        wait_seconds: How long to wait before returning a run_id instead of the result.
        allow_real_project: Allow writes to a non-scratch project (needs the server switch above,
            a saved script and confirm).
        confirm: The confirm_code from a compile_only run of the same saved script, shown to
            and approved by the user.
        helpers: Extra .cs files compiled with the script.
    """
    if bool(code) == bool(script):
        return {"success": False, "error": "Give exactly one of code or script."}
    unsupported = _unsupported_eplan()
    if unsupported:
        return unsupported
    # The pinned target project, so the user clicking another project cannot redirect a run.
    project = project or target.get() or None
    try:
        script_path, source = (None, code) if code else _resolve_script(script)
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    if script_path:
        # A library script's run carries its privileges to every helper, so helpers must be
        # library files too.
        outside = [h for h in (helpers or []) if not (str(h).lower().endswith(".cs")
                                                     and os.path.isfile(h) and _in_script_dir(h))]
        if outside:
            return {"success": False,
                    "error": "helpers for a library script must be .cs files inside a script "
                             "library folder: " + ", ".join(map(str, outside))}

    if allow_real_project and not compile_only:
        if os.environ.get(REAL_PROJECT_SWITCH) != "1":
            return {"success": False,
                    "error": f"Real-project writes are switched off. A person must set the "
                             f"environment variable {REAL_PROJECT_SWITCH}=1 for the MCP server "
                             "process and restart it; the model cannot turn this on. Until then, "
                             "write to a scratch clone (eplan_scratch_project_create)."}
        if not script_path:
            return {"success": False, "error": "Real-project writes need a saved script, not ad-hoc code."}
        # The host checks confirm against its own hash of source + helpers + these exact args.
        if not confirm or len(confirm) < 12:
            return {"success": False,
                    "error": "Real-project writes need confirm=<confirm_code> from a compile_only "
                             "run of this exact script with these exact args and helpers, shown to "
                             "and approved by the user. Take a backup first (eplan_backup_project)."}

    run_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        # Check and claim in one step, so two calls can never start two scripts at once.
        busy = [j for j in _jobs.values() if _is_busy(j)]
        if busy:
            return {"success": False, "error": f"Run {busy[0]['run_id']} is still running; EPLAN runs one "
                                               "script at a time. Use script_status or script_cancel."}
        claim = {"run_id": run_id, "claimed": True, "thread": None, "started": time.time(),
                 "deadline": time.time() + budget_seconds + 180}
        _jobs[run_id] = claim

    started = False
    try:
        try:
            chosen = _pick_runtime(runtime)
        except Exception as e:  # noqa: BLE001 - surface any connection failure plainly
            return {"success": False, "error": f"Could not reach EPLAN: {e}"}
        job = _start_job(run_id, claim, chosen, runtime, source, script_path, args, project,
                         compile_only, dry_run, allow_real_project, confirm, budget_seconds, helpers)
        started = True
    finally:
        if not started:     # release the claim, or one failure blocks every later run
            with _jobs_lock:
                _jobs.pop(run_id, None)
    job["thread"].join(timeout=max(0.0, wait_seconds))
    out = script_status(run_id)
    if compile_only and out.get("ok") and out.get("approval_hash"):
        out["confirm_code"] = out["approval_hash"][:16]
    return out


def _start_job(run_id, claim, chosen, runtime, source, script_path, args, project, compile_only,
               dry_run, allow_real_project, confirm, budget_seconds, helpers) -> dict:
    """Write the request and start the run's thread. Returns the job."""
    folder = _new_run_folder(run_id)
    request_path = os.path.join(folder, "request.json")
    result_path = os.path.join(folder, "result.json")
    _write_json(request_path, {
        "protocol": PROTOCOL,
        "run_id": run_id,
        "source": source,
        "script_path": script_path,
        "source_name": os.path.basename(script_path) if script_path else "snippet.cs",
        "args": args or {},
        # The host runs with exactly this text and hashes it into the confirm code.
        "args_canonical": json.dumps(args or {}, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False),
        "project": project,
        "compile_only": compile_only,
        "dry_run": dry_run,
        "allow_real_project": allow_real_project,
        "confirm": confirm,
        "budget_seconds": budget_seconds,
        "helper_sources": _helpers_for(script_path) + [os.path.abspath(h) for h in (helpers or [])],
        "references": [],
        "run_folder": folder,
    })

    job = {"run_id": run_id, "runtime": chosen, "folder": folder, "result_path": result_path,
           "started": time.time(), "call": None, "deadline": claim["deadline"]}

    def work():
        global _addin_ok
        try:
            job["call"] = _invoke(chosen, "run", folder, request_path, result_path,
                                  timeout=budget_seconds + 120)
        except Exception as e:  # noqa: BLE001
            job["call"] = {"success": False, "message": str(e)}
        if runtime == "auto" and chosen == "addin" and not os.path.isfile(result_path):
            # The add-in wrote nothing (unloaded, EPLAN restarted without it): ask again next
            # run, which falls back to bootstrap. This run is not retried - it may have half-run.
            _addin_ok = None

    job["thread"] = threading.Thread(target=work, name=f"script-{run_id}", daemon=True)
    job["thread"].start()
    with _jobs_lock:
        _jobs[run_id] = job
    return job


def _is_busy(job: dict) -> bool:
    """A job blocks new runs while its call is in flight, up to its deadline. Past the deadline
    the call is treated as lost (EPLAN hung or crashed) so the server is not stuck forever."""
    if time.time() > job.get("deadline", 0):
        return False
    thread = job.get("thread")
    return job.get("claimed") and thread is None or (thread is not None and thread.is_alive())


def script_status(run_id: str) -> dict:
    """
    State of a script run: "running" with progress and heartbeat age, or the final result envelope.

    Args:
        run_id: The run_id script_run returned.
    """
    with _jobs_lock:
        job = _jobs.get(run_id)
    if not job:
        return {"success": False, "error": f"Unknown run_id {run_id} (runs are kept per server process)."}
    if job["thread"] is not None and job["thread"].is_alive() and time.time() > job["deadline"]:
        return {"success": False, "state": "lost", "run_id": run_id,
                "error": ("The run passed its deadline and EPLAN has not returned. EPLAN may be hung "
                          "on this script or a dialog; check eplan_list_dialogs. New runs are allowed "
                          "again, but EPLAN executes one call at a time.")}
    if job["thread"] is not None and job["thread"].is_alive():
        heartbeat = os.path.join(job["folder"], "heartbeat")
        age = time.time() - os.path.getmtime(heartbeat) if os.path.exists(heartbeat) else None
        return {"success": True, "state": "running", "run_id": run_id, "runtime": job["runtime"],
                "elapsed_s": round(time.time() - job["started"], 1),
                "progress": _read_json(os.path.join(job["folder"], "progress.json")),
                "heartbeat_age_s": None if age is None else round(age, 1),
                "note": ("No heartbeat yet: the script has not called ctx.Budget.Check() or "
                         "ctx.Progress(), or EPLAN is busy." if age is None else None)}
    result = _read_json(job["result_path"])
    call = job["call"] if isinstance(job["call"], dict) else {}
    if result is None and call.get("errorType"):
        # A typed failure (EplanNotRunning, EplanBlockedByDialog ...) says more than "no result".
        return {"success": False, "state": "failed", "run_id": run_id, "runtime": job["runtime"],
                "action_result": call, "errorType": call["errorType"],
                "error": call.get("error") or call.get("message"), "next_step": call.get("next_step")}
    if result is None:
        return {"success": False, "state": "failed", "run_id": run_id, "runtime": job["runtime"],
                "action_result": job["call"],
                "error": ("The host wrote no result. EPLAN may have reported success for a script it "
                          "never ran, the add-in may be missing, or EPLAN crashed. Check "
                          "eplan_get_system_messages and the audit log under %LOCALAPPDATA%\\EplanMcp\\audit.")}
    # A script that refuses (over limit, stale handle, wrong snapshot) returns {"error": ...} and
    # writes nothing: the run worked, but the call did not do what was asked, so it is no success.
    value = result.get("result")
    refused = value.get("error") if isinstance(value, dict) else None
    result["success"] = bool(result.get("ok")) and not refused
    if refused and not result.get("error"):
        result["error"] = refused
    result["state"] = "done"
    return result


def script_cancel(run_id: str) -> dict:
    """
    Ask a running script to stop. It stops at its next ctx.Budget.Check(); a script that never
    calls it cannot be stopped short of closing EPLAN.

    Args:
        run_id: The run_id script_run returned.
    """
    with _jobs_lock:
        job = _jobs.get(run_id)
    if not job:
        return {"success": False, "error": f"Unknown run_id {run_id}."}
    with open(os.path.join(job["folder"], "cancel"), "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S"))
    return {"success": True, "run_id": run_id, "note": "Cancel requested; poll script_status."}


def script_list() -> dict:
    """
    The script library: every .cs script with its tool name, description, args and whether it
    writes. Run one with script_run(script=<tool name>).
    """
    scripts = []
    for d in _script_dirs():
        for f in sorted(os.listdir(d)):
            if not f.endswith(".cs") or f.startswith("_"):
                continue
            path = os.path.join(d, f)
            try:
                h = _parse_header(_read(path))
            except ValueError as e:
                scripts.append({"tool": f[:-3], "path": path, "error": str(e)})
                continue
            scripts.append({"tool": h.get("tool") or f[:-3], "desc": h.get("desc"),
                            "args": h.get("args"), "writes": bool(h.get("writes")),
                            "needs": h.get("needs", "session"), "path": path})
    return {"success": True, "count": len(scripts), "scripts": scripts,
            "template": os.path.join(DOTNET_DIR, "scripts", "_template.cs")}
