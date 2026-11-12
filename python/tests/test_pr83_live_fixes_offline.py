"""Regressions found live on EPLAN 2026 while testing PR 83."""

import re

from api.actions import graphics, objects


def _capture(monkeypatch, module):
    seen = {}

    def fake(script, timeout=None, **kw):
        seen["script"] = script
        return {"success": True}

    monkeypatch.setattr(module, "_execute_script", fake)
    return seen


def test_objects_edit_write_runs_the_scratch_guard(monkeypatch):
    seen = _capture(monkeypatch, objects)
    objects.live_objects_edit("page", where=[{"prop": "name", "op": "eq", "value": "+A/1"}],
                              set={"11011": "x"}, dry_run=False)
    script = seen["script"]
    assert "static void GuardScratch(" in script
    call = script.index("GuardScratch(project, false,")
    assert script.index("PickProject(project,") < call     # guards the project it writes to


def test_objects_edit_real_project_needs_the_flag(monkeypatch):
    seen = _capture(monkeypatch, objects)
    objects.live_objects_edit("page", set={"11011": "x"}, dry_run=False, allow_real_project=True)
    assert "GuardScratch(project, true," in seen["script"]


def test_objects_edit_dry_run_has_no_guard(monkeypatch):
    seen = _capture(monkeypatch, objects)
    objects.live_objects_edit("page", set={"11011": "x"})
    assert "GuardScratch" not in seen["script"]


def test_graphics_bodies_declare_their_selection_set():
    # The shared live header stopped declaring `ss` when the target project came in; both
    # bodies used it and failed with CS0103 on every EPLAN version.
    for body in (graphics._BODY, graphics._BODY_LAYER):
        first_use = body.index("ss.") if "ss." in body else body.index("(ss,")
        decl = re.search(r"object ss = Activator\.CreateInstance\(", body)
        assert decl and decl.start() < first_use
