"""Which host flavor the target EPLAN gets: net8 for EPLAN 2027+ (.NET 8), netfx for EPLAN 2026
(.NET Framework). Older EPLANs (also .NET Framework, an untested API) are refused up front with a
clear reason instead of "no answer from the host"."""

from types import SimpleNamespace

import pytest

import eplan_connection
from api.actions import scripthost

NETFX = {"version": "2026", "full_version": "2026.0.3", "bin": "C:/E/2026.0.3/Bin", "runtime": "netfx"}
OLD = {"version": "2025", "full_version": "2025.0.3", "bin": "C:/E/2025.0.3/Bin", "runtime": "netfx"}
CORECLR = {"version": "2027", "full_version": "2027.0.3", "bin": "C:/E/2027.0.3/Bin", "runtime": "coreclr"}


def _env(monkeypatch, installs, target=None):
    monkeypatch.setattr(eplan_connection, "detect_installed_versions", lambda: installs)
    monkeypatch.setattr(eplan_connection, "get_manager", lambda: SimpleNamespace(target_version=target))


def test_eplan_2026_gets_the_netfx_flavor(monkeypatch):
    _env(monkeypatch, [NETFX])
    assert scripthost._unsupported_eplan() is None
    assert scripthost._flavor() == "netfx"


def test_eplan_2027_gets_net8(monkeypatch):
    _env(monkeypatch, [CORECLR, NETFX])
    assert scripthost._unsupported_eplan() is None
    assert scripthost._flavor() == "net8"


def test_older_eplan_is_refused_by_hello_and_run(monkeypatch):
    _env(monkeypatch, [OLD])
    hello = scripthost.script_hello()
    assert hello["success"] is False and hello["eplan_runtime"] == "netfx"
    assert "2026" in hello["error"] and "eplan_execute_custom_script" in hello["next_step"]
    jobs_before = set(scripthost._jobs)
    run = scripthost.script_run(code="return 1;")
    assert run["success"] is False and run["eplan_version"] == "2025.0.3"
    assert set(scripthost._jobs) == jobs_before     # refused before any job was claimed


@pytest.mark.parametrize("target,flavor", [("2026", "netfx"), ("2027", "net8")])
def test_the_connected_target_decides_not_the_newest_install(monkeypatch, target, flavor):
    _env(monkeypatch, [CORECLR, NETFX], target=target)
    assert scripthost._flavor() == flavor


def test_check_failure_never_blocks(monkeypatch):
    def boom():
        raise OSError("no platform folder")
    monkeypatch.setattr(eplan_connection, "detect_installed_versions", boom)
    assert scripthost._unsupported_eplan() is None
    assert scripthost._flavor() == "net8"


def test_a_local_build_is_used_only_for_its_own_flavor(tmp_path, monkeypatch):
    built = tmp_path / "artifacts" / "host"
    built.mkdir(parents=True)
    (built / "eplanmcp-flavor.txt").write_text("netfx")
    monkeypatch.setattr(scripthost, "HOST_DIR", None)
    monkeypatch.setattr(scripthost, "DOTNET_DIR", str(tmp_path))
    monkeypatch.setattr(scripthost, "INSTALL_ROOT", str(tmp_path / "installed"))
    monkeypatch.setattr(scripthost, "_flavor", lambda: "netfx")
    assert scripthost._host_dir() == str(built)
    monkeypatch.setattr(scripthost, "_flavor", lambda: "net8")
    assert scripthost._host_dir() == scripthost._installed_dirs(scripthost.HOST_VERSION, "net8")[0]
    (built / "eplanmcp-flavor.txt").unlink()        # a build from before 0.3.0: net8
    assert scripthost._host_dir() == str(built)
