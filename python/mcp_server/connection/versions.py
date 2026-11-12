"""EPLAN installations on this machine."""

import os
import re


# Root folder of EPLAN installations. Override with the EPLAN_PLATFORM_ROOT
# environment variable for non-standard install locations.
PLATFORM_ROOT = os.environ.get("EPLAN_PLATFORM_ROOT", r"C:\Program Files\EPLAN\Platform")


def _version_key(name: str):
    return tuple(int(p) for p in name.split(".") if p.isdigit())


def detect_installed_versions() -> list:
    """Detect EPLAN installations under PLATFORM_ROOT.

    Returns a list of dicts sorted newest-first, one per major version:
    [{"version": "2027", "full_version": "2027.0.3", "bin": "...", "runtime": "coreclr"}]

    runtime: "coreclr" for .NET 8 builds (EPLAN 2027+, detected via the
    .NET 8-only Grpc.Net.Client.dll), "netfx" for 2026 and older.
    """
    installs = {}
    try:
        for name in os.listdir(PLATFORM_ROOT):
            bin_dir = os.path.join(PLATFORM_ROOT, name, "Bin")
            if not os.path.exists(os.path.join(bin_dir, "Eplan.EplApi.RemoteClientu.dll")):
                continue
            major = "2.9" if re.match(r"^2\.9(?:\.|$)", name) else name.split(".")[0]
            runtime = "coreclr" if os.path.exists(os.path.join(bin_dir, "Grpc.Net.Client.dll")) else "netfx"
            entry = {"version": major, "full_version": name, "bin": bin_dir, "runtime": runtime}
            if major not in installs or _version_key(name) > _version_key(installs[major]["full_version"]):
                installs[major] = entry
    except FileNotFoundError:
        pass
    return sorted(installs.values(), key=lambda e: _version_key(e["full_version"]), reverse=True)
