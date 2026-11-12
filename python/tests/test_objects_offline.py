"""Offline tests for api/actions/objects.py: argument guards, injection safety
and the dry-run default. _execute_script is stubbed, so no EPLAN is needed."""

import pytest

from api.actions import objects

INJECTION = '"; System.Environment.Exit(0); string y = "'


@pytest.fixture
def capture(monkeypatch):
    captured = {}

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        return {"success": True}

    monkeypatch.setattr(objects, "_execute_script", fake_execute)
    return captured


def _balanced(cs):
    stripped = cs.replace("\\\\", "").replace('\\"', "")
    return all(line.count('"') % 2 == 0 for line in stripped.splitlines())


def test_every_interpolated_value_stays_inside_its_literal(capture):
    objects.live_objects_edit(
        "connection",
        where=[{"prop": INJECTION, "op": "eq", "value": INJECTION}],
        set={INJECTION: INJECTION}, read=[INJECTION])
    assert _balanced(capture["script"])
    for line in capture["script"].splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line


def test_edit_is_a_dry_run_unless_asked(capture):
    objects.live_objects_edit("function", set={"31002": "6"})
    assert "bool dryRun = true;" in capture["script"]
    objects.live_objects_edit("function", set={"31002": "6"}, dry_run=False)
    assert "bool dryRun = false;" in capture["script"]


def test_read_never_writes(capture):
    objects.live_objects_read("page", read=["name"])
    assert "string[] setSpecs = new string[] {  };" in capture["script"]
    assert "bool updateFromPart = false;" in capture["script"]


@pytest.mark.parametrize("kwargs", [
    {"kind": "wire"},
    {"kind": "function", "where": [{"prop": "name", "op": "like", "value": "x"}]},
    {"kind": "function", "where": "name=x"},
    {"kind": "function", "read": "name"},
    {"kind": "function", "limit": "5; Exit()"},
])
def test_read_rejects_bad_arguments(capture, kwargs):
    assert objects.live_objects_read(**kwargs)["success"] is False
    assert "script" not in capture


@pytest.mark.parametrize("kwargs", [
    {"kind": "function"},                         # nothing to do
    {"kind": "function", "set": {"name": "x"}},   # pseudo prop
    {"kind": "function", "set": ["31002", "6"]},
])
def test_edit_rejects_bad_arguments(capture, kwargs):
    assert objects.live_objects_edit(**kwargs)["success"] is False
    assert "script" not in capture
