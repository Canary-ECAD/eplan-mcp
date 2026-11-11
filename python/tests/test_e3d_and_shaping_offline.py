"""
Two fixes that both turn a silent failure into a visible one.

1. e3d.py resolved its EPLAN types with Assembly.Load of the UN-suffixed
   assembly names. Measured on 2027.0.1:

       Assembly.Load("Eplan.EplApi.DataModelu")  -> BadImageFormatException
       Assembly.Load("Eplan.EplApi.HEServicesu") -> BadImageFormatException

   Those are the first two statements of both generated scripts, so every tool
   in the module was dead on arrival on a 2027 install - and because a script
   that throws writes no result file, the caller saw only a timeout.

2. _execute_script returned success:True whenever the result FILE existed,
   including when the script had caught its own exception and written
   success:false into it. The real error ended up nested one level down while
   the envelope said the call worked.
"""

import io
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(os.path.dirname(HERE), "mcp_server")
for p in (MCP, os.path.join(MCP, "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

from api.actions import e3d, scripted  # noqa: E402

E3D_SOURCE = io.open(
    os.path.join(MCP, "api", "actions", "e3d.py"), encoding="utf-8"
).read()

# The dangerous CALL, not the name in prose: the helper's comment and its error
# message both mention the forbidden assembly deliberately.
BAD_LOAD = re.compile(
    r'Assembly\.Load\(\s*"Eplan\.EplApi\.(DataModel|HEServices)u"\s*\)'
)


def _code_lines(src):
    """Source lines that are not C# comments."""
    return [l for l in src.splitlines() if "//" not in l]


# ---------------------------------------------------------------------------
# 1. e3d assembly resolution
# ---------------------------------------------------------------------------

def test_e3d_never_loads_the_mixed_mode_native_twin():
    offenders = [l.strip() for l in _code_lines(E3D_SOURCE) if BAD_LOAD.search(l)]
    assert not offenders, (
        "on 2027 these names belong to the NATIVE twin and throw "
        "BadImageFormatException: %s" % offenders
    )


def test_e3d_resolves_types_by_scanning_loaded_assemblies():
    assert "AppDomain.CurrentDomain.GetAssemblies()" in E3D_SOURCE
    assert "static Type FindType(string fullName)" in E3D_SOURCE


def test_e3d_no_longer_scopes_lookups_to_one_assembly():
    """`dm.GetType(...)` / `he.GetType(...)` only work if the load succeeded."""
    assert "dm.GetType(" not in E3D_SOURCE
    assert "he.GetType(" not in E3D_SOURCE


@pytest.mark.parametrize("type_name", [
    "Eplan.EplApi.DataModel.LockingStep",
    "Eplan.EplApi.HEServices.SelectionSet",
    "Eplan.EplApi.DataModel.E3D.InstallationSpace",
    "Eplan.EplApi.HEServices.Insert3D",
])
def test_every_e3d_type_goes_through_findtype(type_name):
    assert 'FindType("%s")' % type_name in E3D_SOURCE


def test_e3d_findtype_fallback_lists_only_the_managed_names():
    """
    The fallback Assembly.Load must never name the un-suffixed assemblies -
    that is the whole bug.
    """
    for name in ("Eplan.EplApi.DataModelNetu", "Eplan.EplApi.HEServicesNetu"):
        assert name in E3D_SOURCE
    assert not [l for l in _code_lines(E3D_SOURCE) if BAD_LOAD.search(l)]


def test_e3d_failure_to_resolve_is_an_error_not_a_null():
    """A null type would surface as a NullReferenceException with no context."""
    assert "Could not resolve type" in E3D_SOURCE


# ---------------------------------------------------------------------------
# 2. result shaping
# ---------------------------------------------------------------------------

def _fake_run(monkeypatch, payload):
    """Drive _execute_script's tail with a canned result file."""
    import json as _json

    class _Mgr:
        def execute_action(self, action, *a, **k):
            m = re.search(r'/ScriptFile:"([^"]+)"', action)
            src = io.open(m.group(1), encoding="utf-8").read()
            rp = re.search(r'File\.WriteAllText\(@?"([^"]+)"', src).group(1)
            rp = rp.replace("\\\\", "\\")
            with io.open(rp, "w", encoding="utf-8") as fh:
                fh.write(_json.dumps(payload))
            return {"success": True}

    monkeypatch.setattr(scripted, "_get_connected_manager", lambda: (_Mgr(), None))
    return scripted._execute_script(
        'public class X { void R() { File.WriteAllText(@"{{RESULT_PATH}}", ""); } }'
    )


def test_a_script_that_reported_failure_is_not_reported_as_success(monkeypatch):
    result = _fake_run(monkeypatch, {"success": False, "error": "No readable property 'Nope'."})
    assert result["success"] is False
    assert "Nope" in result["error"]
    # The nested payload is still there for callers that read it.
    assert result["results"]["error"] == "No readable property 'Nope'."


def test_a_failure_with_no_error_text_still_flips_the_envelope(monkeypatch):
    result = _fake_run(monkeypatch, {"success": False})
    assert result["success"] is False
    assert result["error"]


def test_a_successful_script_is_unchanged(monkeypatch):
    result = _fake_run(monkeypatch, {"success": True, "value": 42})
    assert result["success"] is True
    assert result["results"]["value"] == 42


def test_a_script_that_states_no_verdict_is_still_a_success(monkeypatch):
    """
    Most generated scripts just write data. Absence of a `success` key must not
    become a failure, or every one of them breaks.
    """
    result = _fake_run(monkeypatch, {"pages": ["a", "b"]})
    assert result["success"] is True
    assert result["results"]["pages"] == ["a", "b"]


def test_a_non_dict_result_is_still_a_success(monkeypatch):
    """Some scripts write a bare list; the guard must not choke on it."""
    result = _fake_run(monkeypatch, [1, 2, 3])
    assert result["success"] is True
