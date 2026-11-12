"""The script host is .NET 8: on a .NET Framework EPLAN (2026 and older) it must refuse up front
with a clear reason instead of "no answer from the host"."""

from types import SimpleNamespace

import pytest

import eplan_connection
from api.actions import scripthost

NETFX = {"version": "2026", "full_version": "2026.0.3", "bin": "C:/E/2026.0.3/Bin", "runtime": "netfx"}
CORECLR = {"version": "2027", "full_version": "2027.0.3", "bin": "C:/E/2027.0.3/Bin", "runtime": "coreclr"}


def _env(monkeypatch, installs, target=None):
    monkeypatch.setattr(eplan_connection, "detect_installed_versions", lambda: installs)
    monkeypatch.setattr(eplan_connection, "get_manager", lambda: SimpleNamespace(target_version=target))


def test_netfx_eplan_is_refused_by_hello_and_run(monkeypatch):
    _env(monkeypatch, [NETFX])
    hello = scripthost.script_hello()
    assert hello["success"] is False and hello["eplan_runtime"] == "netfx"
    assert "2027" in hello["error"] and "eplan_execute_custom_script" in hello["next_step"]
    jobs_before = set(scripthost._jobs)
    run = scripthost.script_run(code="return 1;")
    assert run["success"] is False and run["eplan_version"] == "2026.0.3"
    assert set(scripthost._jobs) == jobs_before     # refused before any job was claimed


def test_coreclr_eplan_passes(monkeypatch):
    _env(monkeypatch, [CORECLR, NETFX])
    assert scripthost._unsupported_eplan() is None


@pytest.mark.parametrize("target,refused", [("2026", True), ("2027", False)])
def test_the_connected_target_decides_not_the_newest_install(monkeypatch, target, refused):
    _env(monkeypatch, [CORECLR, NETFX], target=target)
    assert (scripthost._unsupported_eplan() is not None) is refused


def test_check_failure_never_blocks(monkeypatch):
    def boom():
        raise OSError("no platform folder")
    monkeypatch.setattr(eplan_connection, "detect_installed_versions", boom)
    assert scripthost._unsupported_eplan() is None
