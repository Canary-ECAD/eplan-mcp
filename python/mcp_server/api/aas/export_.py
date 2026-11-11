"""
EPLAN -> AAS export tools (registered as MCP tools with the aas_ prefix).

Pulls data from EPLAN through the existing parts-DB tools and emits .aasx
packages via builder.py. EPLAN imports happen lazily inside the functions so
the AAS package stays importable (and testable) without a connection.
"""


def export_part(part_number: str, output_path: str, include_technical_data: bool = True) -> dict:
    """
    Export a part from the EPLAN parts database as an AAS .aasx package.

    Builds one Asset Administration Shell for the part with a Digital
    Nameplate (IDTA 02006) and optionally a Technical Data (IDTA 02003)
    submodel, from the data in the parts database. Requires an EPLAN
    connection (eplan_connect).

    Args:
        part_number: Part number to export (must exist in the parts database)
        output_path: Target .aasx file path
        include_technical_data: Also build the Technical Data submodel
            (default True)

    Returns:
        dict with the created shells/submodels and the output path.
    """
    from ..actions import scripted
    from . import builder

    lookup = scripted.parts_db_get_part(part_number)
    if not lookup.get("success"):
        return {"success": False, "error": f"Parts DB lookup failed: {lookup.get('message') or lookup.get('error')}"}
    results = lookup.get("results", {})
    if not results.get("found"):
        return {"success": False, "error": f"Part not found in parts database: {part_number}"}
    part = results.get("part", {})

    submodels = [builder.build_nameplate(part, part_number)]
    if include_technical_data:
        submodels.append(builder.build_technical_data(part, part_number))
    shell = builder.build_shell(part_number, "part", submodels)

    try:
        summary = builder.write_aasx(output_path, [shell], submodels)
    except Exception as e:
        return {"success": False, "error": f"Could not write AASX: {e}"}
    summary["success"] = True
    summary["part"] = part
    return summary


def export_project(
    project_name: str,
    output_path: str,
    part_numbers: list = None,
    document_paths: list = None,
    properties: dict = None,
) -> dict:
    """
    Export an EPLAN project as an AAS .aasx package (digital twin handover).

    Builds a project-level Asset Administration Shell containing:
    - Technical Data submodel from the given project properties
    - one shell per listed part (each with Digital Nameplate + Technical
      Data from the parts database)
    - Handover Documentation (IDTA 02004) embedding the given files
      (e.g. a PDF export created beforehand with eplan_export_pdf_project)

    Compose it with the existing tools: first read project properties
    (eplan_get_project_property) and/or export reports, then call this.
    Requires an EPLAN connection only when part_numbers are given.

    Args:
        project_name: Project name used for the AAS identifiers
        output_path: Target .aasx file path
        part_numbers: Optional part numbers to include as sub-shells
        document_paths: Optional local files (PDF reports, ...) to embed as
            Handover Documentation
        properties: Optional {name: value} project properties for the
            project's Technical Data submodel

    Returns:
        dict with the created shells/submodels and the output path.
    """
    import os
    from . import builder

    submodels = []
    shells = []

    if properties:
        submodels.append(builder.build_technical_data(properties, project_name))

    # Embed documents, disambiguating colliding basenames so none is silently
    # dropped (two files from different folders can share a name).
    embedded = {}
    missing_docs = []
    used_names = set()
    for doc in document_paths or []:
        if not os.path.isfile(doc):
            missing_docs.append(doc)
            continue
        base = builder._slug(os.path.basename(doc))
        stem, ext = os.path.splitext(base)
        name = base
        suffix = 1
        while name in used_names:
            suffix += 1
            name = f"{stem}_{suffix}{ext}"
        used_names.add(name)
        embedded[f"/aasx/docs/{name}"] = doc
    if embedded:
        submodels.append(
            builder.build_handover_documentation(sorted(embedded.keys()), project_name)
        )

    project_shell = builder.build_shell(project_name, "project", submodels)
    shells.append(project_shell)

    part_errors = {}
    seen_parts = set()
    if part_numbers:
        from ..actions import scripted

        for part_number in part_numbers:
            if part_number in seen_parts:
                continue  # dedup: same part twice would collide on identifier
            seen_parts.add(part_number)
            lookup = scripted.parts_db_get_part(part_number)
            results = lookup.get("results", {})
            if not (lookup.get("success") and results.get("found")):
                part_errors[part_number] = (
                    lookup.get("message") or lookup.get("error") or "not found"
                )
                continue
            part = results.get("part", {})
            part_submodels = [
                builder.build_nameplate(part, part_number),
                builder.build_technical_data(part, part_number),
            ]
            submodels.extend(part_submodels)
            shells.append(builder.build_shell(part_number, "part", part_submodels))

    if not submodels:
        # Only the empty project shell would be written - nothing useful.
        error = ("Nothing to export: no properties, no documents, and no parts "
                 "resolved. Provide at least one.")
        result = {"success": False, "error": error}
        if part_errors:
            result["partErrors"] = part_errors
        if missing_docs:
            result["missingDocuments"] = missing_docs
        return result

    try:
        summary = builder.write_aasx(output_path, shells, submodels, embedded)
    except Exception as e:
        return {"success": False, "error": f"Could not write AASX: {e}"}
    summary["success"] = True
    if part_errors:
        summary["partErrors"] = part_errors
    if missing_docs:
        summary["missingDocuments"] = missing_docs
    return summary
