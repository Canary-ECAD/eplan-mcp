"""
Write tools.json: every tool the server publishes in full mode, with its MCP
annotations and EPLAN facts, exactly as a client sees them in tools/list.

    python tools/dump_tools.py          rewrite python/tools.json
    python tools/dump_tools.py --check  exit 1 if the committed file is stale

tools.json is attached to every release, and the release notes are generated
from its diff with the previous tag (tools/release_notes.py). Runs with EPLAN
closed: building the server connects to nothing.
"""

import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.dirname(HERE)
OUTPUT = os.path.join(SERVER_ROOT, "tools.json")

sys.path[:0] = [os.path.join(SERVER_ROOT, "mcp_server"), os.path.join(SERVER_ROOT, "mcp_server", "api")]

ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def contract():
    """The published contract: {"mode", "tools": [{name, annotations, facts}]}."""
    # Extensions are site-specific: they never belong in the published file.
    os.environ.pop("EPLAN_MCP_EXTENSIONS", None)
    import server
    from tool_annotations import META_KEY

    app, _, _ = server.build_app("full")
    tools = asyncio.run(app.list_tools())
    out = []
    for tool in sorted(tools, key=lambda t: t.name):
        annotations = tool.annotations.model_dump() if tool.annotations else {}
        out.append({
            "name": tool.name,
            "annotations": {key: annotations.get(key) for key in ANNOTATIONS},
            "facts": (tool.meta or {}).get(META_KEY),
        })
    return {"mode": "full", "tools": out}


def render(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv):
    text = render(contract())
    if "--check" in argv:
        try:
            # Text mode reads CRLF as LF: a checkout with core.autocrlf is not stale.
            with open(OUTPUT, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            current = None
        if current != text:
            print("tools.json is out of date: run python tools/dump_tools.py and commit it.",
                  file=sys.stderr)
            return 1
        print("tools.json is up to date.")
        return 0
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"Wrote {os.path.relpath(OUTPUT)} ({len(json.loads(text)['tools'])} tools).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
