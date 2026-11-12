"""
Nothing may be written to stdout under stdio transport.

Under stdio transport stdout IS the JSON-RPC channel. print() buffers into
sys.stdout's own TextIOWrapper while the MCP server writes frames through a
second wrapper on the same file descriptor, so anything print()ed is flushed
at an arbitrary later point and spliced into the middle of an outgoing frame.

Measured in the client logs before this was fixed:
  - "Ignoring non-JSON line on stdout: JSON Parse error: Unexpected identifier
    \"Server\"" - the fragment of "EPLAN MCP Server" that landed mid-frame,
    24h after the banner was printed.
  - the response that frame carried was lost, so a tool bounded to 15s
    (eplan_ping) was still reported "running" 1291s later.
  - the client then dropped the transport with "Received a response for an
    unknown message ID".

Runs with EPLAN closed.
"""

import ast
import os
import subprocess
import sys

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "mcp_server", "server.py")


def _run_handshake():
    """Start the server over stdio, send initialize, return (stdout, stderr)."""
    req = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2024-11-05","capabilities":{},'
        '"clientInfo":{"name":"stdout-guard","version":"0"}}}\n'
    )
    proc = subprocess.Popen(
        [sys.executable, SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        out, err = proc.communicate(req, timeout=180)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return out, err


def test_stdout_carries_only_json_rpc():
    out, err = _run_handshake()
    offenders = []
    for line in out.splitlines():
        if not line.strip():
            continue
        if not line.lstrip().startswith("{"):
            offenders.append(line)
    assert not offenders, (
        "non-JSON written to the stdio JSON-RPC channel: %r\n"
        "Every diagnostic must go to stderr (file=sys.stderr)." % offenders[:10]
    )


def test_banner_still_reaches_stderr():
    """The banner is not deleted, only redirected - it is how a human checks
    which EPLAN version the server targets."""
    out, err = _run_handshake()
    assert "EPLAN MCP Server" in err
    # Not asserted against `out`: "EPLAN MCP Server" is also the serverInfo
    # name inside the legitimate initialize response. The banner LINE is what
    # must not be there, and test_stdout_carries_only_json_rpc already pins
    # that every stdout line is a JSON frame.
    assert "All actions run as eplan_*" in err


# ---------------------------------------------------------------------------
# Source-level guard.
#
# The end-to-end check above cannot catch this on its own: on a clean exit the
# MCP stdio server closes sys.stdout.buffer first, so the banner still sitting
# in sys.stdout's own TextIOWrapper is silently DISCARDED and never appears in
# the captured stdout at all. It only materialises on the paths where the
# buffer is flushed while the stream is still open - which is precisely the
# case that splices it into a JSON-RPC frame. So the reliable pin is static:
# no print() in the server may target stdout.
# ---------------------------------------------------------------------------

SRC_DIRS = [
    os.path.join(os.path.dirname(SERVER)),
    os.path.join(os.path.dirname(SERVER), "api"),
]


def _python_files():
    for d in SRC_DIRS:
        for root, _dirs, files in os.walk(d):
            if "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)


def _prints_to_stdout(path):
    """Yield line numbers of print() calls with no file= keyword."""
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "print"):
            continue
        if any(kw.arg == "file" for kw in node.keywords):
            continue
        yield node.lineno


def test_no_print_targets_stdout():
    offenders = []
    for path in _python_files():
        for lineno in _prints_to_stdout(path):
            offenders.append("%s:%d" % (os.path.relpath(path), lineno))
    assert not offenders, (
        "print() without file=sys.stderr reaches the stdio JSON-RPC channel "
        "at: %s" % ", ".join(offenders)
    )
