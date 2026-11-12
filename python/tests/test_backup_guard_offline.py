"""Tests for restore_masterdata's destination guard.

restore_masterdata's docstring has stated since 2026-07-13 that
destination_path "must be different from the archive_name's own folder", and
recorded what happened when it was not: the restore overwrote the folder,
removed unrelated sibling files (other archives, _BAKINFO.XML, _COMMENT.TXT,
catalog files), and reported {"success": false} anyway - so the flag did not
even signal that something had been touched.

The body never enforced it. These tests pin the enforcement.

No EPLAN needed: the guard runs before the connection is acquired, which is
deliberate - refusing a call with recorded data loss should not depend on
whether a connection happens to be up.
"""

import os

import pytest

from api.actions import backup
from api.actions.backup import _same_directory, restore_masterdata


@pytest.fixture
def manager_spy(monkeypatch):
    """Records whether the action ever reached a manager."""
    calls = []

    class _Manager:
        def execute_action(self, action):
            calls.append(action)
            return {"success": True, "action": action}

    monkeypatch.setattr(backup, "_get_connected_manager",
                        lambda: (_Manager(), None))
    return calls


# ---------------------------------------------------------------------------
# the guard refuses
# ---------------------------------------------------------------------------

def test_refuses_when_destination_is_the_archives_own_folder(tmp_path, manager_spy):
    archive = tmp_path / "macros.zw5"
    archive.write_bytes(b"x")

    result = restore_masterdata(str(archive), str(tmp_path))

    assert result["success"] is False
    assert "Refused" in result["error"]
    assert manager_spy == [], "EPLAN must not be called at all on a refusal"
    # The refusal echoes both paths back, so the model can show the user what
    # it declined to do rather than just reporting a failure.
    assert result["destination_path"] == str(tmp_path)
    assert result["archive_name"] == str(archive)


def test_refuses_regardless_of_case_and_separators(tmp_path, manager_spy):
    """EPLAN is Windows-only, so the guard must fold case and normalise slashes."""
    archive = tmp_path / "sub" / "macros.zw5"
    archive.parent.mkdir()
    archive.write_bytes(b"x")

    awkward = str(archive.parent).replace(os.sep, "/") + "/./"
    result = restore_masterdata(str(archive), awkward)

    assert result["success"] is False
    assert manager_spy == []


def test_refuses_when_destination_is_written_relatively(tmp_path, manager_spy, monkeypatch):
    """A relative destination that resolves to the archive folder is the same bug."""
    archive = tmp_path / "macros.zw5"
    archive.write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    result = restore_masterdata(str(archive), ".")

    assert result["success"] is False
    assert manager_spy == []


# ---------------------------------------------------------------------------
# the guard stays out of the way otherwise
# ---------------------------------------------------------------------------

def test_allows_a_separate_destination(tmp_path, manager_spy):
    archive = tmp_path / "archives" / "macros.zw5"
    archive.parent.mkdir()
    archive.write_bytes(b"x")
    dest = tmp_path / "restore-target"

    result = restore_masterdata(str(archive), str(dest))

    assert result["success"] is True
    assert len(manager_spy) == 1
    action = manager_spy[0]
    assert "/TYPE:MASTERDATA" in action
    assert str(dest) in action


def test_allows_a_destination_that_does_not_exist_yet(tmp_path, manager_spy):
    """
    The guard must not require the destination to exist.

    EPLAN creates the target directory, so comparing with os.path.samefile
    would raise here - which is why the comparison is normcase+abspath.
    """
    archive = tmp_path / "archives" / "macros.zw5"
    archive.parent.mkdir()
    archive.write_bytes(b"x")
    dest = tmp_path / "does" / "not" / "exist"
    assert not dest.exists()

    result = restore_masterdata(str(archive), str(dest))

    assert result["success"] is True
    assert len(manager_spy) == 1


def test_allows_a_sibling_folder_with_a_similar_name(tmp_path, manager_spy):
    """Prefix similarity is not sameness - "md" must not match "md-restore"."""
    archive = tmp_path / "md" / "macros.zw5"
    archive.parent.mkdir()
    archive.write_bytes(b"x")
    dest = tmp_path / "md-restore"

    result = restore_masterdata(str(archive), str(dest))

    assert result["success"] is True
    assert len(manager_spy) == 1


# ---------------------------------------------------------------------------
# _same_directory
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("C:\\md", "C:\\md"),
    ("C:\\md", "c:\\MD"),
    ("C:\\md\\", "C:\\md"),
    ("C:\\md\\sub\\..", "C:\\md"),
])
def test_same_directory_true_cases(a, b):
    assert _same_directory(a, b) is True


@pytest.mark.parametrize("a,b", [
    ("C:\\md", "C:\\md2"),
    ("C:\\md", "C:\\md\\sub"),
    ("C:\\md-restore", "C:\\md"),
])
def test_same_directory_false_cases(a, b):
    assert _same_directory(a, b) is False


@pytest.mark.parametrize("a,b", [(None, "C:\\md"), ("C:\\md", None), (None, None)])
def test_same_directory_never_raises_on_bad_input(a, b):
    """A guard that throws is worse than the hazard it guards against."""
    assert _same_directory(a, b) is False


def test_guard_refuses_even_with_no_connection(tmp_path, monkeypatch):
    """
    The refusal must not depend on EPLAN being reachable.

    This is a deliberate behaviour change: the guard sits before
    _get_connected_manager, so a dangerous call is refused on its own terms
    rather than masked by a connection error the user would then try to fix.
    """
    monkeypatch.setattr(
        backup, "_get_connected_manager",
        lambda: (None, {"success": False, "message": "Not connected"}))
    archive = tmp_path / "macros.zw5"
    archive.write_bytes(b"x")

    result = restore_masterdata(str(archive), str(tmp_path))

    assert result["success"] is False
    assert "Refused" in result["error"]
    assert "Not connected" not in str(result)
