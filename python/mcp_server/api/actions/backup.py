"""
Backup and restore actions.
"""

import os

from ._base import _get_connected_manager, _build_action


def _same_directory(path_a: str, path_b: str) -> bool:
    """
    True if two paths name the same directory on this filesystem.

    Compared with normcase+abspath rather than samefile, deliberately: the
    caller may pass a destination that does not exist yet, and samefile
    raises on a missing path. Case folding matters because EPLAN runs on
    Windows, where "C:\\MD" and "c:\\md" are the same folder.

    Returns False rather than raising if either path cannot be resolved -
    a guard that itself blows up is worse than the thing it guards against.
    """
    try:
        norm = lambda p: os.path.normcase(os.path.abspath(p))
        return norm(path_a) == norm(path_b)
    except (TypeError, ValueError, OSError):
        return False


def backup_project(
    destination_path: str,
    archive_name: str,
    project_name: str = None,
    comment: str = None,
    auto_copy_ref_data: bool = False,
    include_ext_docs: bool = False,
    include_images: bool = False,
    backup_method: str = "BACKUP"
) -> dict:
    """
    Backup a project to disk.
    Action: backup

    project_name is NOT truly optional here: EPLAN only falls back to the
    GUI-selected project when the action is invoked from the GUI (e.g. a
    script or ribbon bar). This MCP calls the action like the Windows
    command line does, so omitting project_name risks an exception or
    acting on the wrong project. The LLM must always ask the user which
    project to back up and pass its full path explicitly.

    The LLM must also always ask the user for destination_path and
    archive_name explicitly — never invent or reuse values from earlier
    in the conversation. archive_name conventions:
      - Include the file extension (official examples use e.g. "*.zw1"),
        unlike some other actions (e.g. project_management's
        CREATESNAPSHOTCOPY) that silently ignore/append their own extension.
      - Names of the form "<name>.nnn" (n = digit 0-9) are forbidden — that
        pattern is reserved by EPLAN for auto-generated split-archive parts.

    backup_method — ask the user which one they want, don't default silently:
      - "BACKUP": plain backup copy. Safe, does not alter the source project.
      - "ARCHIVE": project is archived (behavior on the source not yet verified).
      - "SOURCEOUT": CONFIRMED DESTRUCTIVE on the source project. Verified
        2026-07-13: after running with this method, the source project's
        stub file was renamed from "<name>.elk" (normal, writable) to
        "<name>.els" (write-protected) — its .edb data folder was also
        touched/rewritten. This is EPLAN's "file off"/archive operation: it
        converts the project from its normal writable .elk state to a
        write-protected .els state, not just an extra copy. The LLM must
        always warn the user explicitly before using SOURCEOUT that the
        source project will become write-protected (.els) and get their
        confirmation first — never use it silently or as a default.

    Args:
        destination_path: Target directory
        archive_name: Archive filename (without path), with extension
        project_name: Full path of the project to back up. Always ask the
                      user explicitly — do not omit even though the schema
                      marks it optional.
        comment: Backup comment
        auto_copy_ref_data: Copy referenced external files (0/1)
        include_ext_docs: Include external documents (0/1)
        include_images: Include images (0/1)
        backup_method: "BACKUP" (safe default), "SOURCEOUT" (files off the
                       project — confirm with user first, unconfirmed side
                       effects on original), or "ARCHIVE"
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "backup",
        TYPE="PROJECT",
        PROJECTNAME=project_name,
        DESTINATIONPATH=destination_path,
        ARCHIVENAME=archive_name,
        COMMENT=comment,
        AUTOCOPYREFDATA=auto_copy_ref_data,
        INCLEXTDOCS=include_ext_docs,
        INCLIMAGES=include_images,
        BACKUPMETHOD=backup_method
    )
    return manager.execute_action(action)


def backup_masterdata(
    destination_path: str,
    archive_name: str,
    source_path: str,
    md_type: str,
    filename: str = "*.*",
    comment: str = None
) -> dict:
    """
    Backup master data (forms, symbols, etc.) to disk.
    Action: backup

    source_path must point directly to a folder that actually contains the
    master data files matching md_type — it does not recurse into
    subfolders. Verified 2026-07-13: pointing source_path at a shallow
    root folder (e.g. "V:\\Macros") that had no macro files directly in it
    produced a near-empty ~500 byte archive, while pointing it at the
    actual macro folder (e.g. "V:\\Macros\\ProductoSTD\\ELEC\\1XDM_v.1.xx.xx")
    produced a full ~129 KB archive. The LLM must ask the user for the
    specific folder that directly holds the files, not a parent/category
    folder, and should treat a suspiciously small resulting archive as a
    sign source_path was too shallow.

    If archive_name is given without an extension, EPLAN appends its own
    (observed: ".zw5") — unlike backup_project, which respects whatever
    extension is passed.

    The backup also drops loose files directly into destination_path
    alongside the named archive: "_BAKINFO.XML", "_COMMENT.TXT", and (for
    MACROS at least) copies of catalog files like "Macros.mlk" with their
    original source timestamps preserved. These are normal output of this
    action, not user data left behind by mistake.

    Args:
        destination_path: Target directory
        archive_name: Archive filename
        source_path: Source directory that directly contains the master
                     data files (does not recurse into subfolders) — ask
                     the user for the specific folder, not a parent one.
        md_type: Master data type - "SYMBOLS", "MACROS", "FORMS", "ARTICLES",
                 "LANGUAGES", "STANDARDSHEET", "STATIONDATA"
        filename: File pattern (e.g., "*.fn1", "*.*")
        comment: Backup comment
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "backup",
        TYPE="MASTERDATA",
        DESTINATIONPATH=destination_path,
        ARCHIVENAME=archive_name,
        SOURCEPATH=source_path,
        MDTYPE=md_type,
        FILENAME=filename,
        COMMENT=comment
    )
    return manager.execute_action(action)


def restore_project(
    archive_name: str,
    project_name: str,
    unpack_project: bool = False,
    restore_project_info: bool = True
) -> dict:
    """
    Restore a project from backup.
    Action: restore

    DESTRUCTIVE: overwrites project_name's target path with the restored
    data, with no built-in warning. The restored project is automatically
    upgraded to the currently installed EPLAN version. The LLM must always
    ask the user for the exact archive_name (full path to the .zw1/backup
    file) and project_name (full target .elk path) — never guess or reuse
    a path from earlier in the conversation — and confirm before running.

    unpack_project is NOT about extracting the archive itself: per the
    official docs, set it to 1 only when restoring a project that was
    previously packed/filed-off (e.g. via backup_project's SOURCEOUT or
    ARCHIVE method) and needs unpacking back to a normal working state.
    Default/normal restores of a plain BACKUP-method archive should leave
    this at 0 (False) — ask the user rather than assuming either way.

    restore_project_info controls the MODE parameter: True (default) means
    ProjectInfo.xml IS restored; set to False only if the user explicitly
    wants to skip restoring that file.

    Args:
        archive_name: Path to archive file
        project_name: Target project path
        unpack_project: Unpack a previously packed/filed-off project (0/1).
                        Ask the user; default False is correct for a plain
                        BACKUP-method archive.
        restore_project_info: Restore ProjectInfo.xml (0/1)
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "restore",
        TYPE="PROJECT",
        ARCHIVENAME=archive_name,
        PROJECTNAME=project_name,
        UNPACKPROJECT=unpack_project,
        MODE="1" if restore_project_info else "0"
    )
    return manager.execute_action(action)


def restore_masterdata(archive_name: str, destination_path: str) -> dict:
    """
    Restore master data from backup.
    Action: restore

    DESTRUCTIVE: this overwrites destination_path with the restored data.
    Confirmed 2026-07-13 with destination_path set to the same folder that
    contained archive_name: unrelated sibling files already sitting in that
    folder (other backup archives, _BAKINFO.XML, _COMMENT.TXT, catalog
    files) were removed as part of the overwrite. The reported result was
    {"success": false} with no message even though the overwrite clearly
    happened — so the success flag alone cannot be trusted to mean "nothing
    was touched."

    The LLM must always warn the user, before running this, that
    destination_path will be overwritten by the restore (existing files
    there may be replaced/removed) and get explicit confirmation of the
    exact destination_path — never guess or reuse a path from earlier in
    the conversation, and make sure the user understands the target folder
    is not a safe place to keep unrelated files.

    That constraint is now enforced rather than only documented: if
    destination_path resolves to the archive's own folder, this refuses
    before calling EPLAN. It is the one case with recorded data loss, and
    the one the success flag would not have told you about.

    Args:
        archive_name: Path to archive file
        destination_path: Target directory. Must be different from the
                          archive_name's own folder — see warning above.
                          Refused if it is not.
    """
    if _same_directory(os.path.dirname(archive_name), destination_path):
        return {
            "success": False,
            "error": (
                "Refused: destination_path is the folder that contains "
                "archive_name, and restore overwrites destination_path. "
                "Recorded 2026-07-13, this removed unrelated sibling files "
                "in that folder (other archives, _BAKINFO.XML, "
                "_COMMENT.TXT, catalog files) and still reported "
                '{"success": false}, so the flag would not have warned you. '
                "Pass a separate directory - ideally an empty one - and "
                "confirm the exact path with the user first."
            ),
            "archive_name": archive_name,
            "destination_path": destination_path,
        }

    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "restore",
        TYPE="MASTERDATA",
        ARCHIVENAME=archive_name,
        DESTINATIONPATH=destination_path
    )
    return manager.execute_action(action)
