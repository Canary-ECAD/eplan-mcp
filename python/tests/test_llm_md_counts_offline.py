"""
Pins the tool count that llm.md advertises against what the server publishes.

llm.md tells the model "It exposes **199 tools**". That number is correct today
(the assertion below re-derives it from build_app each run), so this is not a rot
fix - it is a rot *guard*. The count is hand-written prose about a number the
code owns, which is precisely the shape that goes stale silently: add a wrapper
and llm.md is wrong, with nothing to say so.

Offline: builds the app without connecting to EPLAN.
"""

import io
import os
import re

import pytest

from mcp_server import server

LLM_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "llm.md",
)

# llm.md lives at the REPO root, one level above python/.
pytestmark = pytest.mark.skipif(
    not os.path.exists(LLM_MD),
    reason="llm.md not found - running outside a full repo checkout",
)


def _advertised_count():
    text = io.open(LLM_MD, encoding="utf-8").read()
    m = re.search(r"It exposes \*\*([\d,]+) tools\*\*", text)
    assert m, (
        "llm.md no longer carries an 'It exposes **N tools**' line. If the "
        "number was deliberately removed, delete this test with it - do not "
        "leave a guard pointing at nothing."
    )
    return int(m.group(1).replace(",", ""))


def test_llm_md_tool_count_matches_what_the_server_publishes(monkeypatch):
    # The public count only: a private extension pack named in the developer's own
    # environment must not leak into (or break) the number llm.md advertises.
    monkeypatch.setenv("EPLAN_MCP_EXTENSIONS", "")
    app, registry, _ = server.build_app(mode="full")
    published = len(app._tool_manager._tools)
    advertised = _advertised_count()
    assert advertised == published, (
        "llm.md advertises %d tools; build_app(mode='full') publishes %d. "
        "Update the number in llm.md (section 2), or delete it - prose about a "
        "count the code owns will go stale again otherwise."
        % (advertised, published)
    )
