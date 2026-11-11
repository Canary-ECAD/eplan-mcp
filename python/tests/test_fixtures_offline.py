"""Offline tests for api/actions/fixtures.py: scratch project clone/discard
safety. No EPLAN needed - open/close paths are exercised without a connection
(the module treats "not connected" as a soft condition where possible), and
the deletion guard is the main thing under test: discard must refuse to
delete anything outside the scratch root."""

import os

import pytest

from api.actions import fixtures


@pytest.fixture
def scratch_root(tmp_path, monkeypatch):
    root = tmp_path / "scratch"
    monkeypatch.setattr(fixtures, "SCRATCH_ROOT", str(root))
    return root


def _make_template(base_dir, name="Template"):
    elk = base_dir / f"{name}.elk"
    edb = base_dir / f"{name}.edb"
    elk.write_text("link")
    edb.mkdir()
    (edb / "data.bin").write_bytes(b"\x00\x01")
    (edb / "sub").mkdir()
    (edb / "sub" / "more.bin").write_bytes(b"\x02")
    return elk


# ---------------------------------------------------------------------------
# scratch_project_create
# ---------------------------------------------------------------------------

def test_create_copies_elk_and_edb(scratch_root, tmp_path):
    elk = _make_template(tmp_path)
    result = fixtures.scratch_project_create(str(elk), open_after=False)
    assert result["success"] is True
    clone_elk = result["project"]
    assert os.path.exists(clone_elk)
    clone_edb = os.path.splitext(clone_elk)[0] + ".edb"
    assert os.path.isfile(os.path.join(clone_edb, "data.bin"))
    assert os.path.isfile(os.path.join(clone_edb, "sub", "more.bin"))
    assert fixtures._inside_scratch(clone_elk)


def test_create_missing_template_fails(scratch_root, tmp_path):
    result = fixtures.scratch_project_create(str(tmp_path / "nope.elk"), open_after=False)
    assert result["success"] is False
    assert ".elk not found" in result["error"]


def test_create_missing_edb_fails(scratch_root, tmp_path):
    elk = tmp_path / "Lonely.elk"
    elk.write_text("link")
    result = fixtures.scratch_project_create(str(elk), open_after=False)
    assert result["success"] is False
    assert ".edb" in result["error"]


def test_create_uniquifies_name_collisions(scratch_root, tmp_path):
    elk = _make_template(tmp_path)
    first = fixtures.scratch_project_create(str(elk), name="fixed", open_after=False)
    second = fixtures.scratch_project_create(str(elk), name="fixed", open_after=False)
    assert first["success"] and second["success"]
    assert first["project"] != second["project"]
    assert os.path.exists(first["project"]) and os.path.exists(second["project"])


# ---------------------------------------------------------------------------
# scratch_project_discard - the deletion guard
# ---------------------------------------------------------------------------

def test_discard_refuses_outside_scratch_root(scratch_root, tmp_path):
    elk = _make_template(tmp_path, "RealProject")
    result = fixtures.scratch_project_discard(str(elk), close_first=False)
    assert result["success"] is False
    assert "Refusing" in result["error"]
    assert elk.exists(), "real project must not be touched"


def test_discard_deletes_scratch_clone(scratch_root, tmp_path):
    elk = _make_template(tmp_path)
    created = fixtures.scratch_project_create(str(elk), open_after=False)
    clone = created["project"]
    result = fixtures.scratch_project_discard(clone, close_first=False)
    assert result["success"] is True
    assert not os.path.exists(clone)
    assert not os.path.exists(os.path.splitext(clone)[0] + ".edb")


def test_discard_relative_path_cannot_escape(scratch_root, tmp_path):
    elk = _make_template(tmp_path, "Escape")
    sneaky = str(scratch_root / ".." / "Escape.elk")
    result = fixtures.scratch_project_discard(sneaky, close_first=False)
    assert result["success"] is False
    assert elk.exists()


# ---------------------------------------------------------------------------
# scratch_project_list
# ---------------------------------------------------------------------------

def test_list_empty_when_root_absent(scratch_root):
    result = fixtures.scratch_project_list()
    assert result["success"] is True
    assert result["projects"] == []


def test_list_shows_clones(scratch_root, tmp_path):
    elk = _make_template(tmp_path)
    created = fixtures.scratch_project_create(str(elk), open_after=False)
    result = fixtures.scratch_project_list()
    assert [p["project"] for p in result["projects"]] == [created["project"]]
