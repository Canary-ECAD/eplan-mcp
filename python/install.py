"""Create this server's own venv, install its dependencies and register it with Claude Code.

    python install.py                       # user scope, default settings
    python install.py -e EPLAN_MCP_MODE=discovery   # extra args go to `claude mcp add`

Safe to re-run: reuses the venv, upgrades dependencies and re-registers the server.
"""
import shutil
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
PY = VENV / "Scripts" / "python.exe"
SERVER = HERE / "mcp_server" / "server.py"
REQS = HERE / "mcp_server" / "requirements.txt"

if sys.maxsize <= 2**32 or sys.version_info < (3, 10):
    sys.exit("Need 64-bit Python 3.10+ (to match EPLAN's process).")

if not PY.exists():
    print(f"Creating venv in {VENV}")
    venv.create(VENV, with_pip=True)
subprocess.run([str(PY), "-m", "pip", "install", "-q", "--upgrade", "-r", str(REQS)], check=True)

claude = shutil.which("claude")
if not claude:
    sys.exit(f"Dependencies installed. Claude Code not found; register manually:\n"
             f"  claude mcp add eplan -s user -- \"{PY}\" \"{SERVER}\"")
subprocess.run([claude, "mcp", "remove", "eplan", "-s", "user"], capture_output=True)
subprocess.run([claude, "mcp", "add", "eplan", "-s", "user", *sys.argv[1:], "--", str(PY), str(SERVER)], check=True)
print("Done. Start EPLAN, open Claude Code and say `connect to eplan`.")
