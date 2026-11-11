"""Scratch symbol isolation (api/actions/symbol_isolation.py). Offline: the settings reads/writes,
project reopen and library reader are fakes over a tmp scratch root."""
import json
import os

import pytest

from api.actions import symbol_isolation as iso
from api.actions import scripted, project
from eplan_mcp import ext


@pytest.fixture
def env(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("EPLAN_MCP_SCRATCH", str(scratch))
    monkeypatch.setattr(iso, "_PRESETS", {})
    prod = tmp_path / "prod"
    (prod / "Lib.sdb").mkdir(parents=True)
    (prod / "Lib.sdb" / "sym.xml").write_text("x", encoding="utf-8")
    (prod / "Lib.sdb" / "busy.lck").write_text("x", encoding="utf-8")
    # EPLAN writes .slk files as UTF-16LE with a BOM, line 1 naming the body directory.
    (prod / "Lib.slk").write_bytes("Lib.sdb\r\nrest".encode("utf-16"))
    setting = {"value": str(prod)}
    monkeypatch.setattr(scripted, "settings_get_string",
                        lambda path: {"success": True, "value": setting["value"]})
    monkeypatch.setattr(scripted, "settings_set_string",
                        lambda path, v: setting.update(value=v) or {"success": True})
    monkeypatch.setattr(project, "close_project", lambda: {"success": True})
    monkeypatch.setattr(project, "open_project", lambda p: {"success": True})
    monkeypatch.setattr(project, "get_current_project",
                        lambda: {"success": True, "parameters": {"PROJECT": "C:/p/x"}})
    libs = {"path": str(prod / "Lib.slk")}

    def reader():
        # Mirrors EPLAN: a library resolves under the CURRENT symbols root.
        return [{"name": "Lib", "path": os.path.join(setting["value"], "Lib.slk"),
                 "exists": True}], None, "C:/p/x.elk"
    ext.register_isolation_preset("t", {"project_libraries": reader,
                                        "protected_roots": [str(prod)]})
    return {"prod": prod, "setting": setting, "scratch": scratch, "libs": libs}


def test_create_copies_redirects_and_passes_the_gate(env):
    r = iso.scratch_symbols_create(name="symbols_scratch_a")
    assert r["success"], r
    d = env["scratch"] / "symbols" / "symbols_scratch_a"
    assert (d / "Lib.slk").exists() and (d / "Lib.sdb" / "sym.xml").exists()
    assert not (d / "Lib.sdb" / "busy.lck").exists()
    assert env["setting"]["value"] == str(d)
    assert r["isolation"]["isolated"] and r["reopened"]["project"] == "C:/p/x.elk"
    state = json.loads((env["scratch"] / "symbols_redirect.json").read_text(encoding="utf-8"))
    assert state["previous_symbols_path"] == str(env["prod"])


def test_second_create_is_refused_and_restore_puts_the_value_back(env):
    assert iso.scratch_symbols_create(name="symbols_scratch_a")["success"]
    again = iso.scratch_symbols_create(name="symbols_scratch_b")
    assert not again["success"] and "already active" in again["error"]
    st = iso.scratch_symbols_status()
    assert st["redirect_active"] and st["redirect_recorded"]
    r = iso.scratch_symbols_restore(delete_scratch=True)
    assert r["restored"] and env["setting"]["value"] == str(env["prod"])
    assert not (env["scratch"] / "symbols" / "symbols_scratch_a").exists()
    assert iso.scratch_symbols_restore()["restored"] is False


def test_gate_fails_when_a_library_is_outside_or_protected(env):
    r = iso.assert_isolation(require_root=str(env["scratch"]))
    assert r["success"] and not r["isolated"]
    assert r["outside_root"] and r["protected_hits"]


def test_gate_without_a_reader_refuses(env, monkeypatch):
    monkeypatch.setattr(iso, "_PRESETS", {})
    r = iso.assert_isolation(require_root=str(env["scratch"]))
    assert not r["isolated"] and "project_libraries" in r["reason"]


def test_create_without_a_reader_needs_explicit_libraries(env, monkeypatch):
    monkeypatch.setattr(iso, "_PRESETS", {})
    assert not iso.scratch_symbols_create(reopen_project=False)["success"]
    r = iso.scratch_symbols_create(name="symbols_scratch_x", libraries=[env["libs"]["path"]],
                                   reopen_project=False)
    assert r["success"] and r["libraries"][0]["files"] == 1


def test_name_cannot_escape_the_scratch_root(env):
    for name in ("..\\..\\evil", ".", "", "..", "x\\.."):
        r = iso.scratch_symbols_create(name=name)
        assert not r["success"] and "scratch root" in r["error"], name
    assert env["setting"]["value"] == str(env["prod"]) and iso._read_state() is None


def test_purge_spares_the_active_redirect(env):
    assert iso.scratch_symbols_create(name="symbols_scratch_live")["success"]
    (env["scratch"] / "symbols" / "symbols_scratch_old").mkdir()
    (env["scratch"] / "symbols" / "other").mkdir()
    (env["scratch"] / "symbols_scratch_project").mkdir()   # beside scratch projects: not ours
    r = iso.scratch_symbols_purge()
    assert [os.path.basename(p) for p in r["deleted"]] == ["symbols_scratch_old"]
    assert r["skipped"] and (env["scratch"] / "symbols" / "other").exists()
    iso.scratch_symbols_purge(prefix="")
    assert (env["scratch"] / "symbols_scratch_project").exists()


def test_state_is_written_before_the_setting_changes(env, monkeypatch):
    seen = []
    real_set = scripted.settings_set_string

    def spy(path, v):
        seen.append(iso._read_state())
        return real_set(path, v)
    monkeypatch.setattr(scripted, "settings_set_string", spy)
    assert iso.scratch_symbols_create(name="symbols_scratch_s")["success"]
    assert seen[0]["previous_symbols_path"] == str(env["prod"])


def test_failed_redirect_that_changed_nothing_leaves_no_record(env, monkeypatch):
    monkeypatch.setattr(scripted, "settings_set_string", lambda path, v: {"success": False})
    r = iso.scratch_symbols_create(name="symbols_scratch_f")
    assert not r["success"] and iso._read_state() is None


def test_unknown_preset_is_refused(env):
    assert "unknown isolation preset" in iso.scratch_symbols_status(preset="zz")["error"]


def test_hints():
    from tool_annotations import annotate
    assert annotate("eplan_scratch_symbols_status", iso.scratch_symbols_status)[0].readOnlyHint
    assert annotate("eplan_assert_isolation", iso.assert_isolation)[0].readOnlyHint
    assert annotate("eplan_scratch_symbols_purge", iso.scratch_symbols_purge)[0].destructiveHint
    assert annotate("eplan_scratch_symbols_create", iso.scratch_symbols_create)[0].readOnlyHint is False
