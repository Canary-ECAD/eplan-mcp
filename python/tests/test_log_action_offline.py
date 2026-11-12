"""Tests for the actions.jsonl trace: where it goes, and what reaches it.

Two defects motivated this module, both found by censusing the committed
trace on 2026-09-03.

1. The log directory was hardcoded off __file__, so `pytest` wrote into
   mcp_server/logs/actions.jsonl - the very file the action audit reasons
   from. 871 of its 1,463 entries turned out to be test fixtures from 59
   separate runs, spread through the file rather than sitting at the head.
   Fixed by EPLAN_MCP_LOG_DIR plus the autouse fixture in conftest.py.

2. LOGGED_RESULT_KEYS is a filter with no guard. A diagnostic field added to
   an action result but not to that tuple is silently absent from the trace,
   which means it cannot be measured in any later audit - and the trace is the
   only durable record of what the server did.

Offline: drives _log_action directly with a manager whose connection state is
never used.
"""

import io
import json
import os

import pytest

import eplan_connection
from eplan_connection import LOGGED_RESULT_KEYS, EPLANConnectionManager


def _read_entries(log_dir):
    path = os.path.join(log_dir, "actions.jsonl")
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture
def manager():
    return EPLANConnectionManager()


# ---------------------------------------------------------------------------
# where the log goes
# ---------------------------------------------------------------------------

def test_log_dir_honours_the_env_override(manager, tmp_path, monkeypatch):
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(target))
    assert manager._log_dir() == str(target)


def test_log_dir_falls_back_to_the_package_default(manager, monkeypatch):
    monkeypatch.delenv("EPLAN_MCP_LOG_DIR", raising=False)
    assert manager._log_dir().endswith("logs")
    assert "mcp_server" in manager._log_dir()


def test_log_dir_is_read_per_call_not_cached(manager, tmp_path, monkeypatch):
    """A fixture must be able to redirect the log after the manager exists."""
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path / "first"))
    first = manager._log_dir()
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path / "second"))
    assert manager._log_dir() != first


def test_log_action_writes_under_the_override(manager, tmp_path, monkeypatch):
    target = tmp_path / "trace"
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(target))

    manager._log_action("someAction /A:1", {"success": True}, 0.0)

    entries = _read_entries(str(target))
    assert len(entries) == 1
    assert entries[0]["action"] == "someAction /A:1"
    assert entries[0]["success"] is True


def test_log_action_creates_a_missing_directory(manager, tmp_path, monkeypatch):
    target = tmp_path / "deep" / "not" / "there"
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(target))

    manager._log_action("someAction", {"success": True}, 0.0)

    assert len(_read_entries(str(target))) == 1


def test_log_action_never_raises_on_an_unwritable_dir(manager, tmp_path, monkeypatch):
    """
    Logging is a side effect of every action. If it can throw, a full disk or a
    permission problem takes down actions that were otherwise fine.
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("this is a file, so makedirs must fail")
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(blocker / "logs"))

    manager._log_action("someAction", {"success": True}, 0.0)  # must not raise


def test_the_suite_does_not_write_the_package_log(manager):
    """
    Pins conftest's autouse isolation.

    Deliberately does NOT set the env var itself - it relies on the fixture. If
    the fixture is ever removed or made opt-in, this fails and names the
    pollution, rather than the suite quietly resuming writes to the real trace.
    """
    assert os.environ.get("EPLAN_MCP_LOG_DIR"), (
        "conftest's autouse _isolate_action_log fixture is not active - the "
        "suite is writing to mcp_server/logs/actions.jsonl again, which is the "
        "file the action audit measures."
    )
    manager._log_action("someAction /PROBE:1", {"success": True}, 0.0)

    package_log = os.path.join(
        os.path.dirname(os.path.abspath(eplan_connection.__file__)),
        "logs", "actions.jsonl")
    if os.path.exists(package_log):
        with io.open(package_log, encoding="utf-8") as f:
            assert "/PROBE:1" not in f.read()


# ---------------------------------------------------------------------------
# what reaches the log
# ---------------------------------------------------------------------------

def test_always_logged_fields_are_present(manager, tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    manager._log_action("someAction", {"success": False}, 0.0)
    entry = _read_entries(str(tmp_path))[0]
    for key in ("ts", "action", "duration_s", "success"):
        assert key in entry


def test_every_logged_key_round_trips(manager, tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    result = {"success": False}
    for key in LOGGED_RESULT_KEYS:
        result[key] = ["x"] if key == "eplanMessages" else "v-" + key

    manager._log_action("someAction", result, 0.0)

    entry = _read_entries(str(tmp_path))[0]
    for key in LOGGED_RESULT_KEYS:
        assert key in entry, "%s is in LOGGED_RESULT_KEYS but did not reach the trace" % key


def test_absent_keys_are_omitted_not_nulled(manager, tmp_path, monkeypatch):
    """Keeps entries small; a null would also read as "we looked and found nothing"."""
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    manager._log_action("someAction", {"success": True}, 0.0)
    entry = _read_entries(str(tmp_path))[0]
    assert "error" not in entry
    assert "eplanMessages" not in entry


def test_logged_keys_cover_the_diagnostic_result_contract():
    """
    The guard the plan calls for.

    LOGGED_RESULT_KEYS is a filter, so a diagnostic field added to the result
    contract but forgotten here is invisible to every future audit. When a new
    field is introduced, add it to BOTH the result and this tuple - then extend
    the set below in the same commit, deliberately.
    """
    expected = {"executor", "error", "errorType", "message", "failedScriptPath",
                "eplanMessages", "eplanMessagesTotal",
                "eplanMessagesTruncated", "eplanMessagesLevels",
                "eplanMessagesUnbounded", "eplanMessagesFromContextOnly",
                "errorFrom", "eplan_state", "not_responding_s",
                # calls that did not complete (EplanBlockedByDialog & co.)
                "timed_out", "in_flight_action"}
    assert set(LOGGED_RESULT_KEYS) == expected, (
        "LOGGED_RESULT_KEYS changed to %r. If a diagnostic field was added to "
        "the action result, this is the right place to notice - update the "
        "expected set here in the same commit, and check the field is actually "
        "reaching actions.jsonl. If a field was REMOVED, say why in the commit: "
        "the trace is the only durable record of what this server did."
        % (LOGGED_RESULT_KEYS,)
    )


def test_non_ascii_survives_the_round_trip(manager, tmp_path, monkeypatch):
    """
    EPLAN localises its messages, so the trace has to keep them readable.

    ensure_ascii=False is what makes the recorded Spanish and German messages
    legible in the file rather than \\uXXXX soup.
    """
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    msg = "La base de datos está protegida contra escritura"
    manager._log_action("someAction", {"success": False, "eplanMessages": [msg]}, 0.0)

    entry = _read_entries(str(tmp_path))[0]
    assert entry["eplanMessages"] == [msg]
    with io.open(os.path.join(str(tmp_path), "actions.jsonl"), encoding="utf-8") as f:
        assert "está" in f.read()


def test_entries_append_rather_than_truncate(manager, tmp_path, monkeypatch):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    manager._log_action("first", {"success": True}, 0.0)
    manager._log_action("second", {"success": True}, 0.0)
    assert [e["action"] for e in _read_entries(str(tmp_path))] == ["first", "second"]
