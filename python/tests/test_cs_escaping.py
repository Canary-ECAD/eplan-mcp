"""Tests for C# string-literal escaping in generated scripts (injection defense).

Uses a fake EPLAN client that captures the generated .cs so we can assert the
untrusted input never breaks out of its string literal. No EPLAN needed.
"""

import os
import re
import sys

import pytest

MCP = os.path.join(os.path.dirname(__file__), "..", "mcp_server")
sys.path.insert(0, MCP)

import eplan_connection  # noqa: E402
from api.actions import scripted  # noqa: E402


def test_cs_escape_neutralizes_quotes_backslashes_newlines():
    out = eplan_connection.cs_escape('a"b\\c\nd\te')
    assert '"' not in out.replace('\\"', "")   # every quote is escaped
    assert "\n" not in out and "\r" not in out  # no raw newline
    assert out == 'a\\"b\\\\c\\nd\\te'


def test_cs_escape_control_chars():
    assert eplan_connection.cs_escape("\x00\x1f") == "\\u0000\\u001f"


class _FakeClient:
    SynchronousMode = False

    def __init__(self):
        self.captured_cs = None

    def ExecuteAction(self, action):
        m = re.search(r'/ScriptFile:"([^"]+)"', action)
        if action.startswith("ExecuteScript") and m:
            with open(m.group(1), encoding="utf-8") as f:
                content = f.read()
            self.captured_cs = content
            rm = re.search(r'File\.WriteAllText\("([^"]+)"', content)
            result_path = rm.group(1).replace("\\\\", "\\")
            with open(result_path, "w", encoding="utf-8") as f:
                f.write('{"success": true, "parameters": {}}')


def _run(action):
    mgr = eplan_connection.EPLANConnectionManager()
    mgr.connected = True
    fake = _FakeClient()
    mgr.client = fake
    mgr.execute_action(action, quiet_mode=True)
    return fake.captured_cs


def _string_literal_balanced(cs: str) -> bool:
    """No unescaped double-quote leaves a dangling literal, and no raw newline
    sits inside one. Heuristic: strip escaped quotes, then every remaining
    quote must pair up, and no line may end inside an open literal."""
    stripped = cs.replace('\\"', "").replace("\\\\", "")
    # Even number of quotes per line = no literal spans a newline unescaped.
    for line in stripped.splitlines():
        if line.count('"') % 2 != 0:
            return False
    return True


@pytest.mark.parametrize("payload", [
    'X"); System.Environment.Exit(0); ("',   # injection attempt as action name
    'Val"; evil(); "',
    "line1\nline2",
    "back\\slash",
    'quote"inside',
])
def test_action_name_and_params_cannot_break_out(payload):
    # payload as an action parameter value
    cs = _run(f'someAction /PARAM:"{payload}"')
    assert cs is not None
    assert _string_literal_balanced(cs)
    # The literal injection statement must not appear unescaped as code.
    assert "System.Environment.Exit(0);" not in cs.replace('\\"', "")


def test_action_name_is_escaped():
    # An action name containing a quote (reachable via execute_raw_action).
    cs = _run('bad"name")); evil(); ((')
    assert cs is not None
    assert _string_literal_balanced(cs)


def test_parts_db_create_arbitrary_property_names(tmp_path):
    # Property names that are NOT valid C# identifiers must not produce broken
    # C# (they used to be minted as `var prop_<name>`).
    mgr = eplan_connection.EPLANConnectionManager()
    mgr.connected = True
    fake = _FakeClient()
    mgr.client = fake
    # Monkeypatch scripted's manager resolution to our fake.
    import api.actions._base as base
    saved = base.get_manager
    base.get_manager = lambda *a, **k: mgr
    try:
        scripted.parts_db_create("PN-1", {"a b": "x", 'q"uote': "y", "1leading": "z", "a b": "dup"})
    finally:
        base.get_manager = saved
    cs = fake.captured_cs
    assert cs is not None
    assert _string_literal_balanced(cs)
    assert "var prop_" not in cs  # no per-name identifier minting
