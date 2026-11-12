"""
AAS (Asset Administration Shell) package.

MCP tools for the Industrie 4.0 digital twin standard (AAS metamodel V3,
IDTA submodel templates), built on basyx-python-sdk:

- export_part / export_project: EPLAN -> .aasx packages
- inspect_package: look inside any .aasx (offline)
- import_parts: supplier .aasx -> EPLAN parts database (dry-run first)

Registered by server.py with the "aas_" prefix (e.g. aas_export_part).
Unlike api/actions, only inspect_package works without an EPLAN connection;
the mapping/builder internals are offline-testable pure Python.
"""

from .export_ import export_part, export_project
from .import_ import inspect_package, import_parts

__all__ = [
    "export_part",
    "export_project",
    "inspect_package",
    "import_parts",
]
