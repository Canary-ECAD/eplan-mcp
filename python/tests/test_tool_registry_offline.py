"""
ToolRegistry.call (eplan_tools_call, discovery mode) - Audit #42 item 9.

Full mode reaches every tool through FastMCP's own
fn_metadata.call_fn_with_arg_validation, which validates AND COERCES
arguments against the function's type annotations. This call went straight
to func(**arguments) instead, so discovery mode accepted argument types full
mode would reject - a caller sending {"limit": "5"} (a string, from a model
that read a JSON schema saying "integer" and typed a numeral anyway) got a
silently wrong call in discovery mode and a clean coercion everywhere else.

No EPLAN needed - this is pure argument handling before any tool body runs.
"""

import functools
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(os.path.dirname(HERE), "mcp_server")
for p in (MCP,):
    if p not in sys.path:
        sys.path.insert(0, p)

from tool_registry import ToolRegistry  # noqa: E402


def _record_calls(fn):
    """Wrap fn so tests can assert it was (not) reached, and see what it got.

    functools.wraps sets __wrapped__, which inspect.signature (and so
    func_metadata) follows by default - without it the wrapper's own bare
    (**kwargs) signature would be all the registry's coercion step could see,
    losing every real parameter's type.
    """
    calls = []

    @functools.wraps(fn)
    def wrapper(**kwargs):
        calls.append(kwargs)
        return fn(**kwargs)

    wrapper.calls = calls
    return wrapper


def typed_tool(count: int, label: str = "x", enabled: bool = False) -> dict:
    return {"success": True, "count": count, "label": label, "enabled": enabled}


def kwargs_only_tool(**kwargs) -> dict:
    return {"success": True, "received": kwargs}


@pytest.fixture
def registry():
    mod = SimpleNamespace()
    mod.typed_tool = _record_calls(typed_tool)
    mod.kwargs_only_tool = _record_calls(kwargs_only_tool)

    reg = ToolRegistry()
    reg.add("eplan_typed_tool", mod, "typed_tool")
    reg.add("eplan_kwargs_only_tool", mod, "kwargs_only_tool")
    reg.mod = mod
    return reg


def test_string_int_is_coerced_like_full_mode(registry):
    """A JSON caller sending "5" for an int param gets int 5, not a TypeError
    deep inside the wrapper and not a string silently threaded through."""
    result = registry.call("eplan_typed_tool", {"count": "5"})
    assert result["success"] is True
    assert result["count"] == 5
    assert isinstance(result["count"], int)
    assert registry.mod.typed_tool.calls[-1]["count"] == 5


def test_string_bool_is_coerced_like_full_mode(registry):
    result = registry.call("eplan_typed_tool", {"count": 1, "enabled": "true"})
    assert result["success"] is True
    assert result["enabled"] is True


def test_genuinely_invalid_type_is_refused_before_the_call(registry):
    """The whole point: a value full mode would reject must not reach func."""
    result = registry.call("eplan_typed_tool", {"count": "not-a-number"})
    assert result["success"] is False
    assert "validation" in result["error"].lower()
    assert registry.mod.typed_tool.calls == []  # never reached


def test_valid_call_is_unaffected(registry):
    result = registry.call("eplan_typed_tool", {"count": 3, "label": "hi"})
    assert result == {"success": True, "count": 3, "label": "hi", "enabled": False}


def test_unknown_argument_still_caught_by_name_first(registry):
    """The existing did-you-mean guard runs before coercion is ever reached."""
    result = registry.call("eplan_typed_tool", {"count": 1, "cuont": 2})
    assert result["success"] is False
    assert "Unknown argument" in result["error"]
    assert registry.mod.typed_tool.calls == []


def test_missing_required_still_caught_by_name_first(registry):
    result = registry.call("eplan_typed_tool", {"label": "hi"})
    assert result["success"] is False
    assert "Missing required argument" in result["error"]
    assert registry.mod.typed_tool.calls == []


def test_kwargs_only_tool_still_works_uncoerced(registry):
    """A function func_metadata cannot build a strict model for (bare **kwargs,
    no annotations) falls back to the raw arguments rather than blocking the
    call - the behaviour this registry had everywhere before this fix."""
    result = registry.call("eplan_kwargs_only_tool", {"anything": "goes", "n": "5"})
    assert result["success"] is True
    assert result["received"] == {"anything": "goes", "n": "5"}  # untouched, still a string
