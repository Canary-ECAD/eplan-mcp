"""
AAS -> EPLAN import tools (registered as MCP tools with the aas_ prefix).

inspect_package works fully offline; import_parts maps supplier AASX data
onto the EPLAN parts database with a mandatory dry-run preview.
"""

from basyx.aas import model

from . import mapping


def _mlp_text(mlp):
    """Best single string from a MultiLanguageProperty (prefer English)."""
    value = mlp.value
    if value is None:
        return None
    try:
        texts = dict(value.items())
    except AttributeError:
        return str(value)
    if not texts:
        return None
    for lang in ("en", "en-US", "en-GB"):
        if lang in texts:
            return texts[lang]
    return next(iter(texts.values()))


def _iter_properties(element, prefix=""):
    """Yield (idShort, value) for Property and MultiLanguageProperty elements,
    recursing into collections and lists.

    Handling MultiLanguageProperty is essential: the IDTA Digital Nameplate
    template mandates MLPs for ManufacturerName etc., so a spec-conformant
    supplier package would otherwise import nothing.
    """
    if isinstance(element, model.Property):
        yield (prefix + (element.id_short or ""), element.value)
    elif isinstance(element, model.MultiLanguageProperty):
        yield (prefix + (element.id_short or ""), _mlp_text(element))
    elif isinstance(element, (model.SubmodelElementCollection, model.SubmodelElementList)):
        for child in element.value:
            yield from _iter_properties(child, prefix)


def _submodel_properties(submodel):
    """Flat {idShort: value} of all properties in a submodel (collections flattened)."""
    props = {}
    for element in submodel.submodel_element:
        for id_short, value in _iter_properties(element):
            if id_short and value is not None and id_short not in props:
                props[id_short] = str(value)
    return props


def inspect_package(aasx_path: str) -> dict:
    """
    Inspect a .aasx package: shells, submodels, and embedded files.

    Works offline - no EPLAN connection needed. Use this before
    aas_import_parts to see what a supplier package contains.

    Args:
        aasx_path: Path to the .aasx file

    Returns:
        dict with shells (id, idShort, submodel refs), submodels
        (id, idShort, semanticId, properties) and embedded file names.
    """
    from . import builder

    try:
        object_store, file_store = builder.read_aasx(aasx_path)
    except (OSError, ValueError) as e:
        return {"success": False, "error": f"Could not read AASX: {e}"}

    shells = []
    submodels = []
    for obj in object_store:
        if isinstance(obj, model.AssetAdministrationShell):
            shells.append({
                "id": obj.id,
                "idShort": obj.id_short,
                "globalAssetId": obj.asset_information.global_asset_id,
                "submodelRefs": [
                    ref.key[0].value if ref.key else None for ref in obj.submodel
                ],
            })
        elif isinstance(obj, model.Submodel):
            semantic_id = None
            if obj.semantic_id and getattr(obj.semantic_id, "key", None):
                semantic_id = obj.semantic_id.key[0].value
            submodels.append({
                "id": obj.id,
                "idShort": obj.id_short,
                "semanticId": semantic_id,
                "properties": _submodel_properties(obj),
            })

    return {
        "success": True,
        "path": aasx_path,
        "shells": shells,
        "submodels": submodels,
        "embeddedFiles": list(file_store),
    }


def import_parts(aasx_path: str, dry_run: bool = True) -> dict:
    """
    Import supplier AASX data into the EPLAN parts database.

    Maps Digital Nameplate / Technical Data submodel properties onto
    parts-DB fields (manufacturer, designation, order number). Parts that
    do not exist are created; existing parts are updated. ALWAYS returns a
    dry-run preview first: call with dry_run=True (default), show the user
    the proposed writes, and only after their confirmation call again with
    dry_run=False. Requires an EPLAN connection when dry_run=False.

    Args:
        aasx_path: Path to the supplier .aasx file
        dry_run: If True (default), only report what would be written.

    Returns:
        dict with per-part proposed (or executed) creates/updates.
    """
    inspection = inspect_package(aasx_path)
    if not inspection.get("success"):
        return inspection

    # Group submodel properties per part: use the shell's submodel refs so
    # nameplate + technical data of the same shell merge into one record.
    submodels_by_id = {sm["id"]: sm for sm in inspection["submodels"]}
    plans = []
    seen_part_numbers = set()
    for shell in inspection["shells"] or [None]:
        if shell is None:
            # Package without shells: treat all submodels as one record
            merged = {}
            for sm in inspection["submodels"]:
                merged.update(sm["properties"])
        else:
            merged = {}
            for ref in shell["submodelRefs"]:
                sm = submodels_by_id.get(ref)
                if sm:
                    merged.update(sm["properties"])
        if not merged:
            continue

        part_number = None
        for id_short in mapping.PART_NUMBER_IDSHORTS:
            if merged.get(id_short):
                part_number = merged[id_short]
                break

        # Skip a second shell resolving to the same part (e.g. shells sharing
        # a nameplate) so a live import doesn't write the same part twice.
        if part_number is not None and part_number in seen_part_numbers:
            continue
        if part_number is not None:
            seen_part_numbers.add(part_number)

        fields = {}
        for id_short, value in merged.items():
            db_property = mapping.IDSHORT_TO_PARTS_DB.get(id_short)
            if db_property and db_property != "ARTICLE_PARTNR" and value:
                fields[db_property] = value

        plans.append({
            "shell": shell["idShort"] if shell else None,
            "partNumber": part_number,
            "fields": fields,
        })

    if not plans:
        return {"success": False, "error": "No importable part data found in package"}

    unidentified = [p for p in plans if not p["partNumber"]]
    if dry_run:
        return {
            "success": True,
            "dryRun": True,
            "proposed": plans,
            "unidentified": len(unidentified),
            "note": "Nothing was written. Show this to the user; re-run with "
                    "dry_run=False after they confirm.",
        }

    # Live import
    from ..actions import scripted

    outcomes = []
    for plan in plans:
        if not plan["partNumber"]:
            outcomes.append({**plan, "status": "skipped", "reason": "no part number found"})
            continue
        lookup = scripted.parts_db_get_part(plan["partNumber"])
        found = lookup.get("success") and lookup.get("results", {}).get("found")
        if found:
            updated, failed = [], []
            for db_property, value in plan["fields"].items():
                result = scripted.parts_db_update(plan["partNumber"], db_property, value)
                ok = result.get("success") and result.get("results", {}).get("success", True)
                (updated if ok else failed).append(db_property)
            outcomes.append({**plan, "status": "updated", "updated": updated,
                             **({"failed": failed} if failed else {})})
        else:
            result = scripted.parts_db_create(plan["partNumber"], plan["fields"])
            ok = result.get("success") and result.get("results", {}).get("success")
            outcomes.append({
                **plan,
                "status": "created" if ok else "create-failed",
                **({} if ok else {"error": result.get("results", {}).get("error") or result.get("message")}),
            })

    return {"success": True, "dryRun": False, "outcomes": outcomes}
