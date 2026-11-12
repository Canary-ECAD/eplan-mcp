"""
Scratch project fixtures - disposable copies of a template project for
unattended test runs.

Pattern: an agent testing an add-in or automation never mutates a real
project. Instead it clones a designated template project into a scratch
area, opens the clone, runs actions against it, verifies the outcome, and
discards the clone. Deletion is restricted to the scratch root so these
tools can never remove a real project.

An EPLAN project on disk is `<name>.elk` (link file) plus a sibling
`<name>.edb\\` directory holding the actual data; both are copied. The
template must not be open in EPLAN during cloning (EPLAN locks files inside
the .edb directory).
"""

import json
import os
import secrets
import shutil
import tempfile
import time

from ._base import _get_connected_manager

# The script host lets ad-hoc scripts write only when the target project carries this
# marker (dotnet/src/EplanMcp.Scripting/ScratchMarker.cs reads it). A marker names its own
# link file, so one copied next to a real project does not count.
SCRATCH_MARKER_SUFFIX = ".eplanmcp-scratch"
SCRATCH_MARKER_KIND = "eplan-mcp-scratch"


def _write_scratch_marker(elk_path: str, template: str) -> str:
    marker = elk_path + SCRATCH_MARKER_SUFFIX
    with open(marker, "w", encoding="utf-8") as f:
        json.dump({
            "kind": SCRATCH_MARKER_KIND,
            "version": 1,
            "nonce": secrets.token_hex(16),
            "project_link": os.path.abspath(elk_path),
            "template": template,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, f)
    return marker


def _rmtree_writable(path):
    """shutil.rmtree that also removes READ-ONLY files.

    Projects carry read-only files (e.g. external documents under DOC\\), and
    on Windows os.remove refuses those with WinError 5 even though nothing
    holds them. Clear the flag and retry; a file EPLAN really holds still
    raises, so the caller's retry/report path stays the same.
    """
    import stat

    def clear_and_retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    import sys
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear_and_retry)   # onerror is deprecated there
    else:
        shutil.rmtree(path, onerror=clear_and_retry)

# Scratch root: everything created here is fair game for deletion.
SCRATCH_ROOT = os.environ.get(
    "EPLAN_MCP_SCRATCH",
    os.path.join(tempfile.gettempdir(), "eplan_mcp_scratch"),
)


def _resolve_project_parts(elk_path: str):
    """Return (elk_path, edb_path, base_name) for a project .elk file."""
    elk_path = os.path.abspath(elk_path)
    base, ext = os.path.splitext(elk_path)
    return elk_path, base + ".edb", os.path.basename(base)


def _reject_unsafe_name(name: str):
    """
    Validate a caller-supplied clone name that will be used as a FILENAME.

    Returns None when the name is safe, otherwise a ready-to-return error dict.

    Rejected, with the reason each one matters:
      - empty / whitespace       would build ".elk" in the scratch root
      - a path separator         "a/b" escapes into a subdirectory
      - ".." as a segment        classic traversal
      - a drive letter ("C:")    os.path.join DISCARDS the base for these
      - a leading "\\\\"           UNC path, writes to another machine
      - "." or ".."              resolve to the directory itself
      - a reserved device name   CON/PRN/AUX/NUL/COM1.. are not files on Windows
    """
    if not name or not name.strip():
        return {"success": False,
                "error": "name must not be empty."}
    if name != name.strip():
        return {"success": False,
                "error": f"name must not have leading/trailing whitespace: {name!r}"}
    for sep in (os.sep, os.altsep, "/", "\\"):
        if sep and sep in name:
            return {"success": False,
                    "error": (f"name must be a bare project name, not a path: "
                              f"{name!r} contains {sep!r}.")}
    if name in (".", ".."):
        return {"success": False,
                "error": f"name must not be {name!r}."}
    # A colon means a drive letter or an NTFS alternate data stream; either way
    # it is not a bare name.
    if ":" in name:
        return {"success": False,
                "error": f"name must not contain ':': {name!r}"}
    if os.path.isabs(name):
        return {"success": False,
                "error": f"name must be relative, not an absolute path: {name!r}"}
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved |= {f"COM{i}" for i in range(1, 10)}
    reserved |= {f"LPT{i}" for i in range(1, 10)}
    if name.split(".")[0].upper() in reserved:
        return {"success": False,
                "error": f"name is a reserved Windows device name: {name!r}"}
    return None


def _inside_scratch(path: str) -> bool:
    # realpath, not abspath: %TEMP% is often an 8.3 short path and EPLAN
    # reports long ones, so both sides must be expanded the same way.
    root = os.path.realpath(SCRATCH_ROOT)
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:  # different drives
        return False


def scratch_project_create(template_project: str, name: str = None,
                           open_after: bool = True) -> dict:
    """
    Clone a template project into the scratch area for a disposable test run.

    Copies the template's .elk file and .edb directory to the scratch root
    (EPLAN_MCP_SCRATCH env var, default %TEMP%/eplan_mcp_scratch) under a
    unique name, then optionally opens the clone in EPLAN.

    The template must be CLOSED in EPLAN while cloning - EPLAN locks files
    inside an open project's .edb directory and the copy would fail or be
    inconsistent.

    Args:
        template_project: Full path to the template project's .elk file.
        name: Base name for the clone. Default: "<template>_scratch_<timestamp>".
        open_after: Open the clone in EPLAN after copying (default True;
            requires an active EPLAN connection).
    """
    src_elk, src_edb, src_base = _resolve_project_parts(template_project)
    if not os.path.exists(src_elk):
        return {"success": False, "error": f"Template .elk not found: {src_elk}"}
    if not os.path.isdir(src_edb):
        return {"success": False,
                "error": f"Template .edb directory not found next to the .elk: {src_edb}"}

    clone_base = name or f"{src_base}_scratch_{time.strftime('%Y%m%d_%H%M%S')}"

    # `name` becomes a filename, so it must be a bare name and nothing else.
    # os.path.join happily absorbs "../.." and DISCARDS the base entirely for an
    # absolute path or a drive letter, so an unchecked name lands the clone
    # wherever the user can write - including a real project tree, where
    # scratch_project_discard then refuses to clean it up because it sits
    # outside the scratch root. That one-sided guard is the bug: discard checked
    # containment, create did not.
    name_error = _reject_unsafe_name(clone_base)
    if name_error:
        return name_error

    # Uniquify if the name is taken.
    dst_dir = SCRATCH_ROOT
    os.makedirs(dst_dir, exist_ok=True)
    candidate = clone_base
    counter = 1
    while os.path.exists(os.path.join(dst_dir, candidate + ".elk")):
        candidate = f"{clone_base}_{counter}"
        counter += 1
    dst_elk = os.path.join(dst_dir, candidate + ".elk")
    dst_edb = os.path.join(dst_dir, candidate + ".edb")

    # Belt and braces: even with a validated name, assert the built paths really
    # are inside the scratch root before anything is written.
    for built in (dst_elk, dst_edb):
        if not _inside_scratch(built):
            return {
                "success": False,
                "error": (
                    f"Refusing to create outside the scratch root: {built} is "
                    f"not under {SCRATCH_ROOT}."
                ),
            }

    try:
        shutil.copy2(src_elk, dst_elk)
        shutil.copytree(src_edb, dst_edb)
        _write_scratch_marker(dst_elk, src_elk)
    except Exception as e:
        # Clean up a half-copied clone.
        for p in (dst_elk, dst_elk + SCRATCH_MARKER_SUFFIX):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if os.path.isdir(dst_edb):
            shutil.rmtree(dst_edb, ignore_errors=True)
        return {"success": False,
                "error": f"Copy failed (is the template open in EPLAN?): {e}"}

    result = {
        "success": True,
        "project": dst_elk,
        "template": src_elk,
        "note": "Disposable clone - discard with scratch_project_discard when done.",
    }
    if open_after:
        from .project import open_project
        result["open"] = open_project(dst_elk)
        result["success"] = result["open"].get("success", False)
    return result


# Close ONE project object, found by its path among EPLAN's open projects. Not
# XPrjActionProjectClose: that closes whatever the GUI has selected, and with a navigator
# multi-selection it closed a real project together with the clone (seen live on EPLAN 2026).
_CLOSE_BY_PATH_BODY = '''
            Type pmTypeC = FindType("Eplan.EplApi.DataModel.ProjectManager");
            object pmC = Activator.CreateInstance(pmTypeC);
            PropertyInfo openPi = RequireReadable(pmTypeC, "OpenProjects");
            List<string> before = new List<string>();
            foreach (object p in (IEnumerable)openPi.GetValue(pmC, null))
                if (p != null) before.Add(PropText(p, "ProjectLinkFilePath") ?? PropText(p, "ProjectName") ?? "");
            results["closing"] = PropText(project, "ProjectLinkFilePath") ?? PropText(project, "ProjectName");
            results["before"] = before;
            MethodInfo closeMi = MethodByShape(project.GetType(), "Close", new string[] { }, false);
            if (closeMi == null)
                throw new Exception("Project.Close() not found. " + MemberList(project.GetType(), true));
            closeMi.Invoke(project, null);
            List<string> after = new List<string>();
            foreach (object p in (IEnumerable)openPi.GetValue(pmC, null))
                if (p != null) after.Add(PropText(p, "ProjectLinkFilePath") ?? PropText(p, "ProjectName") ?? "");
            results["after"] = after;
            results["success"] = true;
'''


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path or "")) if path else ""


def _close_scratch_in_eplan(elk: str) -> dict:
    """Close exactly the clone `elk` in EPLAN. {"success", "was_open", "before", "after"}.

    Fails (and nothing may be deleted) when another project went missing too."""
    from . import live, target
    previous = target.get()
    target.set_target(elk)      # the live header then resolves the clone by path
    try:
        script = live._script("ScratchClose_" + secrets.token_hex(4), _CLOSE_BY_PATH_BODY)
    finally:
        target.set_target(previous)
    out = live._execute_script(script, timeout=120)
    res = out.get("results") if isinstance(out.get("results"), dict) else out
    if not res.get("success"):
        error = str(res.get("error") or out.get("error") or "")
        if "is not open in EPLAN" in error:
            return {"success": True, "was_open": False}
        return {"success": False, "errorType": "CloseFailed", "error": error or "close failed",
                "next_step": "Close the clone in EPLAN by hand, then retry with close_first=False."}
    before = {_norm(p) for p in res.get("before") or []}
    after = {_norm(p) for p in res.get("after") or []}
    lost = sorted(before - after - {_norm(elk)})
    result = {"success": _norm(elk) not in after and not lost, "was_open": True,
              "before": res.get("before"), "after": res.get("after")}
    if lost:
        result.update(errorType="ClosedOtherProjects",
                      error="Closing the clone also closed: " + ", ".join(lost),
                      next_step="Reopen those projects; nothing was deleted.")
    elif _norm(elk) in after:
        result.update(errorType="StillOpen", error="EPLAN still lists the clone as open.")
    return result


def scratch_project_discard(project_path: str, close_first: bool = True) -> dict:
    """
    Delete a scratch project created by scratch_project_create.

    Refuses to touch anything outside the scratch root, so this can never
    delete a real project. Closes the clone in EPLAN first - that one project
    object, by path, whatever has GUI focus, and checks that every other open
    project is still open; if the close fails, nothing is deleted. Pass
    close_first=False only for a clone you know is not open in EPLAN.

    Args:
        project_path: Path to the scratch project's .elk file.
        close_first: Close the project in EPLAN before deleting (default True).
    """
    elk, edb, _ = _resolve_project_parts(project_path)
    # Both paths that get deleted: for elk == the root itself, edb would be
    # the root's sibling "<root>.edb", outside the scratch area.
    if not (_inside_scratch(elk) and _inside_scratch(edb)):
        return {"success": False,
                "error": f"Refusing to delete outside the scratch root "
                         f"({SCRATCH_ROOT}): {elk}"}

    closed = None
    if close_first:
        manager, error = _get_connected_manager()
        if not error:
            closed = _close_scratch_in_eplan(elk)
            if not closed.get("success"):
                return {**closed, "deleted": None}

    # .edb first: if EPLAN still holds it, the .elk link survives and the
    # clone can be closed and discarded again. Handles can lag a close, so
    # retry briefly on PermissionError.
    errors = []
    for path, remover in ((edb, _rmtree_writable), (elk, os.remove),
                          (elk + SCRATCH_MARKER_SUFFIX, os.remove)):
        if not os.path.exists(path):
            continue
        for attempt in range(5):
            try:
                remover(path)
                break
            except PermissionError as e:
                if attempt == 4:
                    errors.append(f"{path}: {e}")
                else:
                    time.sleep(0.5)
            except Exception as e:
                errors.append(f"{path}: {e}")
                break
        if errors:
            break

    result = {"success": not errors, "deleted": elk, "closed_in_eplan": closed}
    if errors:
        result["error"] = ("Delete failed (project still open/locked in EPLAN?): "
                           + "; ".join(errors))
        result["next_step"] = ("Close the clone in EPLAN (eplan_close_project), wait a few "
                               "seconds, then retry the discard.")
    return result


def scratch_project_list() -> dict:
    """
    List scratch projects currently in the scratch area.

    Useful for cleaning up leftovers from crashed or interrupted test runs
    (discard them with scratch_project_discard).
    """
    if not os.path.isdir(SCRATCH_ROOT):
        return {"success": True, "scratch_root": SCRATCH_ROOT, "projects": []}
    projects = []
    for entry in sorted(os.listdir(SCRATCH_ROOT)):
        if entry.lower().endswith(".elk"):
            full = os.path.join(SCRATCH_ROOT, entry)
            projects.append({
                "project": full,
                "modified": time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(os.path.getmtime(full))),
            })
    return {"success": True, "scratch_root": SCRATCH_ROOT, "projects": projects}
