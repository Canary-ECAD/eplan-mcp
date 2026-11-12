"""
AAS repository/registry REST client - DEFERRED STUB.

Per the project plan, the file-based AASX workflow ships first; this module
becomes the IDTA Part 2 ("Asset Administration Shell API") client once an
actual AAS server (Eclipse BaSyx, FA3ST, ...) exists to test against.

Planned surface (do not register as MCP tools until implemented and tested
against a live server):

- repo_list_shells()                 GET  {AAS_SERVER_URL}/shells
- repo_get_submodel(submodel_id)     GET  {AAS_SERVER_URL}/submodels/{base64url(id)}
- repo_push(aasx_path)               POST serialized environment
- registry_lookup(asset_id)          GET  registry descriptor lookup

Configuration via env: AAS_SERVER_URL, optional AAS_SERVER_TOKEN.
Implementation notes: use httpx; identifiers are base64url-encoded in URL
paths per the specification.
"""

__all__ = []
