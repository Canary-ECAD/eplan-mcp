"""Tests for the three 'the action did not run' paths in _run_generated_script.

All three used to return a bare {"success": false, "message": ...}. To a caller
that is indistinguishable from a slow action that eventually worked, so the
recorded behaviour was to retry - sometimes with different parameters, which
cannot help when the real cause is that the generated C# did not compile. That
failure mode is not hypothetical: commit 21d10d4d6 fixed a CS1061 that broke
every wrapped action at once, and the only evidence of it was a script the
cleanup then deleted.

Each path now carries errorType, executor="none", an error saying plainly
whether the action ran, and a preserved copy of the script.

Offline: the client is a stub, and no EPLAN is involved.
"""

import io
import json
import os

import pytest

import eplan_connection
from eplan_connection import LOGGED_RESULT_KEYS, EPLANConnectionManager


ALWAYS_LOGGED = {"ts", "action", "duration_s", "success"}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A manager whose ExecuteScript succeeds but writes nothing."""
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path / "logs"))
    mgr = EPLANConnectionManager()
    mgr.connected = True

    class _Client:
        SynchronousMode = True

        def ExecuteAction(self, action):
            return None

    mgr.client = _Client()
    return mgr


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "exec_action_dead.cs"
    path.write_text("public class Broken { int x = \"nope\"; }", encoding="utf-8")
    return str(path)


def _trace(manager):
    path = os.path.join(manager._log_dir(), "actions.jsonl")
    with io.open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------------------------------------------------------------------
# no result file at all
# ---------------------------------------------------------------------------

def test_no_result_file_is_named_and_not_called_a_timeout(manager, script, tmp_path, monkeypatch):
    monkeypatch.setattr(eplan_connection, "SCRIPT_RESULT_TIMEOUT_S", 0.05)

    result = manager._run_generated_script(
        "someAction /A:1", script, str(tmp_path / "never.json"), 0.0)

    assert result["success"] is False
    assert result["errorType"] == "McpScriptNoResult"
    assert result["executor"] == "none"
    assert "did NOT run" in result["error"]
    # The distinction that stops the wrong retry.
    assert "NOT a timeout on a slow action" in result["error"]
    # Legacy field kept so an existing caller matching on it still works.
    assert result["message"] == "Timeout waiting for scripted action execution result"


def test_no_result_file_preserves_the_script(manager, script, tmp_path, monkeypatch):
    monkeypatch.setattr(eplan_connection, "SCRIPT_RESULT_TIMEOUT_S", 0.05)

    result = manager._run_generated_script(
        "someAction", script, str(tmp_path / "never.json"), 0.0)

    kept = result["failedScriptPath"]
    assert os.path.exists(kept), "the only evidence of a compile failure must survive"
    assert "int x =" in io.open(kept, encoding="utf-8").read()
    # ...and the original is still cleaned up as before.
    assert not os.path.exists(script)


# ---------------------------------------------------------------------------
# a result file that never parses
# ---------------------------------------------------------------------------

def test_unparseable_result_is_distinguished_from_no_result(manager, script, tmp_path, monkeypatch):
    """
    These two must not share an errorType.

    No result file means the action certainly did not run. A result file that
    never parsed means the script reached its write, so a side effect may
    already have been applied - the opposite advice for the caller.
    """
    bad = tmp_path / "result.json"
    bad.write_text("{not json", encoding="utf-8")

    result = manager._run_generated_script("someAction", script, str(bad), 0.0)

    assert result["errorType"] == "McpScriptBadResult"
    assert "may or may not have run" in result["error"]
    assert "possibly applied" in result["error"]
    assert os.path.exists(result["failedScriptPath"])


# ---------------------------------------------------------------------------
# ExecuteScript itself refused
# ---------------------------------------------------------------------------

def test_execute_script_refusal_says_it_is_a_plumbing_fault(manager, script, tmp_path, monkeypatch):
    monkeypatch.setattr(
        manager, "execute_action",
        lambda a, quiet_mode=False, **kw: {"success": False, "message": "boom"})

    result = manager._run_generated_script(
        "someAction", script, str(tmp_path / "never.json"), 0.0)

    assert result["errorType"] == "McpScriptExecuteFailed"
    assert "do not retry with different parameters" in result["error"]
    assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# the happy path is untouched
# ---------------------------------------------------------------------------

def test_a_valid_result_is_returned_verbatim(manager, script, tmp_path):
    good = tmp_path / "result.json"
    good.write_text(json.dumps(
        {"success": True, "executor": "action", "parameters": {"A": "1"}}),
        encoding="utf-8")

    result = manager._run_generated_script("someAction", script, str(good), 0.0)

    assert result == {"success": True, "executor": "action",
                      "parameters": {"A": "1"}}
    assert "errorType" not in result
    assert "failedScriptPath" not in result


# ---------------------------------------------------------------------------
# the trace sees all of it
# ---------------------------------------------------------------------------

def test_every_field_of_a_failure_reaches_the_trace(manager, script, tmp_path, monkeypatch):
    """
    Closes the gap the LOGGED_RESULT_KEYS change-detector alone leaves.

    That guard fires when the tuple changes; it cannot notice a result field
    that was added and never listed. This asserts the other direction, for the
    one result shape this module owns: every key _script_failure emits is
    either always-logged or in LOGGED_RESULT_KEYS, so nothing it reports is
    invisible to a later audit.
    """
    monkeypatch.setattr(eplan_connection, "SCRIPT_RESULT_TIMEOUT_S", 0.05)

    result = manager._run_generated_script(
        "someAction /A:1", script, str(tmp_path / "never.json"), 0.0)

    loggable = ALWAYS_LOGGED | set(LOGGED_RESULT_KEYS)
    unlogged = set(result) - loggable
    assert not unlogged, (
        "_script_failure emits %s, which LOGGED_RESULT_KEYS does not carry, so "
        "it will not reach actions.jsonl and cannot be measured later. Add it "
        "to the tuple (and to the expected set in "
        "test_log_action_offline.py)." % sorted(unlogged)
    )

    entry = _trace(manager)[-1]
    assert entry["errorType"] == "McpScriptNoResult"
    assert entry["executor"] == "none"
    assert entry["failedScriptPath"] == result["failedScriptPath"]
