"""Add-in dev loop (api/actions/addin_dev.py): manifests, build, deploy, list, update. Offline:
subprocess and the EPLAN lifecycle calls are mocked."""
import json
import types

import pytest

from api.actions import addin_dev
from eplan_mcp import ext


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "src" / "A").mkdir(parents=True)
    (tmp_path / "src" / "A" / "A.csproj").write_text("<Project/>", encoding="utf-8")
    (tmp_path / "src" / "A" / "Act.cs").write_text(
        'var a = "Acme_Run"; var b = "Acme_Other_Do"; var c = "Nope_X";', encoding="utf-8")
    (tmp_path / "src" / "A" / "bin").mkdir()
    (tmp_path / "src" / "A" / "bin" / "Old.cs").write_text('"Acme_Stale"', encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.bat").write_text("@echo off", encoding="utf-8")
    (tmp_path / "presets").mkdir()
    manifest = {"root": "..", "projects": {"A": "src/A/A.csproj"},
                "deploy": {"command": ["cmd", "/c", "{root}/scripts/deploy.bat"],
                           "cwd": "scripts", "summary_regex": r"^\[OK\]"},
                "actions_prefix": "Acme_", "source_dirs": ["src"]}
    path = tmp_path / "presets" / "addins.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(addin_dev, "_MANIFESTS", {})
    ext.register_addin_manifest("acme", str(path))
    return tmp_path, "acme"


def _fake_run(calls, returncode=0, stdout=""):
    def run(cmd, **kw):
        calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    return run


def test_unknown_manifest_names_the_registered_ones(repo):
    ext.register_addin_manifest("mine", str(repo[0] / "presets" / "addins.json"))
    r = addin_dev.addin_build("nope")
    assert not r["success"] and "mine" in r["error"]


def test_build_resolves_paths_against_the_manifest_root(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(addin_dev.subprocess, "run",
                        _fake_run(calls, stdout="Build succeeded.\nnoise\n"))
    ext.register_addin_manifest("mine", str(repo[0] / "presets" / "addins.json"))
    r = addin_dev.addin_build("mine")
    assert r["success"] and r["configuration"] == "Release"
    assert r["projects"]["A"]["output"] == ["Build succeeded."]
    cmd = calls[0][0]
    assert cmd[:2] == ["dotnet", "build"] and cmd[2].endswith("A.csproj") and "Release" in cmd


def test_build_refuses_an_unknown_project(repo):
    r = addin_dev.addin_build(repo[1], projects=["Z"])
    assert not r["success"] and "'Z'" in r["error"] and "A" in r["error"]


def test_deploy_runs_the_command_in_its_cwd_and_filters_the_summary(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(addin_dev.subprocess, "run",
                        _fake_run(calls, stdout="[OK] a.dll\nchatter\n"))
    r = addin_dev.addin_deploy(repo[1])
    assert r == {"success": True, "exit_code": 0, "summary": ["[OK] a.dll"]}
    cmd, kw = calls[0]
    assert cmd[0] == "cmd" and cmd[2].endswith("deploy.bat") and "{root}" not in cmd[2]
    assert kw["cwd"].endswith("scripts") and kw["stdin"] is addin_dev.subprocess.DEVNULL


def test_deploy_refuses_a_missing_script(repo, monkeypatch):
    (repo[0] / "scripts" / "deploy.bat").unlink()
    monkeypatch.setattr(addin_dev.subprocess, "run", lambda *a, **k: pytest.fail("ran"))
    r = addin_dev.addin_deploy(repo[1])
    assert not r["success"] and "not found" in r["error"]


def test_list_actions_scans_source_and_skips_bin(repo):
    r = addin_dev.list_addin_actions(manifest=repo[1])
    assert r["success"] and r["actions"] == ["Acme_Other_Do", "Acme_Run"]
    r = addin_dev.list_addin_actions(prefix="Nope_", source_dirs=[str(repo[0] / "src")])
    assert r["actions"] == ["Nope_X"]
    assert not addin_dev.list_addin_actions(prefix="a.b", source_dirs=["x"])["success"]


def _lifecycle(monkeypatch, shutdown_ok=True):
    from api.actions import lifecycle, project, addons
    seen = []
    monkeypatch.setattr(project, "get_current_project",
                        lambda: {"success": True, "parameters": {"PROJECT": "C:/p/x.elk"}})
    monkeypatch.setattr(project, "open_project", lambda p: seen.append(("open", p)) or {"success": True})
    monkeypatch.setattr(lifecycle, "app_shutdown",
                        lambda: seen.append("shutdown") or {"success": shutdown_ok})
    monkeypatch.setattr(lifecycle, "app_launch", lambda **kw: seen.append("launch") or {"success": True})
    monkeypatch.setattr(addons, "verify_actions",
                        lambda names: seen.append(("verify", list(names))) or {"success": True})
    monkeypatch.setattr(addin_dev, "addin_deploy",
                        lambda m: seen.append("deploy") or {"success": True})
    return seen


def test_update_shuts_down_before_deploying_and_verifies_the_manifest_list(repo, monkeypatch):
    seen = _lifecycle(monkeypatch)
    m = json.loads(open(repo[0] / "presets" / "addins.json", encoding="utf-8").read())
    m["root"] = str(repo[0])
    m["verify_actions"] = ["Acme_Run"]
    r = addin_dev.addin_update(m, do_build=False, restart=True, do_deploy=True)
    assert r["success"], r
    assert seen == ["shutdown", "deploy", "launch", ("verify", ["Acme_Run"])]


def test_update_does_not_deploy_when_shutdown_fails(repo, monkeypatch):
    seen = _lifecycle(monkeypatch, shutdown_ok=False)
    r = addin_dev.addin_update(repo[1], do_build=False, restart=True, do_deploy=True)
    assert not r["success"] and "deploy" not in seen


def test_update_falls_back_to_the_scanned_names(repo, monkeypatch):
    seen = _lifecycle(monkeypatch)
    r = addin_dev.addin_update(repo[1], do_build=False, restart=False, do_deploy=False)
    assert r["success"] and seen == [("verify", ["Acme_Other_Do", "Acme_Run"])]


def test_deploying_tools_carry_a_destructive_hint():
    from tool_annotations import annotate
    for f in (addin_dev.addin_deploy, addin_dev.addin_update):
        assert annotate("eplan_" + f.__name__, f)[0].destructiveHint is True
    assert annotate("eplan_list_addin_actions", addin_dev.list_addin_actions)[0].readOnlyHint is True


def test_published_tools_refuse_a_manifest_path(repo, monkeypatch):
    monkeypatch.setattr(addin_dev.subprocess, "run", lambda *a, **k: pytest.fail("ran"))
    path = str(repo[0] / "presets" / "addins.json")
    for r in (addin_dev.addin_build(path), addin_dev.addin_deploy(path),
              addin_dev.addin_update(path), addin_dev.list_addin_actions(manifest=path)):
        assert not r["success"] and "registered manifest name" in r["error"]
    m, err = addin_dev.load_manifest_file(path)     # still open to extension code
    assert err is None and m["projects"] == {"A": "src/A/A.csproj"}


def test_update_neither_deploys_nor_restarts_by_default(repo, monkeypatch):
    seen = _lifecycle(monkeypatch)
    r = addin_dev.addin_update(repo[1], do_build=False)
    assert r["success"] and "deploy" not in seen and "shutdown" not in seen and "launch" not in seen
    import inspect
    sig = inspect.signature(addin_dev.addin_update)
    assert sig.parameters["do_deploy"].default is False and sig.parameters["restart"].default is False
    assert "CAN DEPLOY AND RESTART EPLAN" in addin_dev.addin_update.__doc__


def test_build_is_not_read_only():
    from tool_annotations import annotate
    annotations, meta = annotate("eplan_addin_build", addin_dev.addin_build)
    assert annotations.readOnlyHint is False and next(iter(meta.values()))["runsCode"] is True
