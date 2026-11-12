"""
AAS object construction and AASX packaging (pure Python, no EPLAN needed).

Built on basyx-python-sdk (Eclipse BaSyx, AAS metamodel V3, AASX Part 5).
Everything here is offline-testable; the EPLAN-facing data flows live in
export.py / import_.py.
"""

import mimetypes
import os
import re

from basyx.aas import model
from basyx.aas.adapter import aasx

from . import mapping

# basyx enforces these (AAS metamodel V3): idShort must start with a letter
# (AASd-002) and NameType is capped at 128 chars.
_ID_SHORT_MAX = 128

# Base for generated AAS/submodel identifiers. Override per site so IDs are
# globally unique, e.g. AAS_ID_BASE=https://aas.mycompany.com/eplan
ID_BASE = os.environ.get("AAS_ID_BASE", "urn:eplan-mcp")


def _slug(text: str) -> str:
    """Filesystem/IRI-safe version of a part or project name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-") or "unnamed"


def _id_short(text: str) -> str:
    """Valid AAS idShort: letters/digits/underscore, MUST start with a letter
    (basyx AASd-002), max 128 chars."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
    if not cleaned or not cleaned[0].isalpha():
        # A leading underscore is NOT allowed by AASd-002, so prefix a letter.
        cleaned = "x" + cleaned
    return cleaned[:_ID_SHORT_MAX]


def make_identifier(kind: str, name: str) -> str:
    """Build a stable AAS identifier, e.g. urn:eplan-mcp:aas:part-3RV2011."""
    return f"{ID_BASE}:{kind}:{_slug(name)}"


def _external_ref(semantic_id: str) -> model.ExternalReference:
    return model.ExternalReference(
        (model.Key(model.KeyTypes.GLOBAL_REFERENCE, semantic_id),)
    )


def _present(value) -> bool:
    """True unless the value is absent - keeps meaningful falsy values like 0/False."""
    return value is not None and value != ""


def _guess_content_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _property(id_short: str, value: str, semantic_id: str = None) -> model.Property:
    return model.Property(
        id_short=id_short,
        value_type=model.datatypes.String,
        value=str(value),
        semantic_id=_external_ref(semantic_id) if semantic_id else None,
    )


def build_nameplate(part: dict, owner_name: str) -> model.Submodel:
    """Digital Nameplate (IDTA 02006) submodel from a parts_db_get_part dict."""
    elements = []
    for part_key, (id_short, semantic_id) in mapping.PART_TO_NAMEPLATE.items():
        value = part.get(part_key)
        if _present(value):
            elements.append(_property(id_short, value, semantic_id))
    return model.Submodel(
        id_=make_identifier("sm:nameplate", owner_name),
        id_short="Nameplate",
        semantic_id=_external_ref(mapping.NAMEPLATE_SEMANTIC_ID),
        submodel_element=elements,
    )


def build_technical_data(part: dict, owner_name: str) -> model.Submodel:
    """Technical Data (IDTA 02003) submodel from a parts_db_get_part dict.

    Mapped fields go into GeneralInformation; any extra keys of the part
    dict (e.g. user-selected ERP/technical properties) go into
    TechnicalProperties verbatim.
    """
    general = []
    mapped_keys = set()
    for part_key, (id_short, semantic_id) in mapping.PART_TO_TECHNICAL_DATA.items():
        value = part.get(part_key)
        if _present(value):
            general.append(_property(id_short, value, semantic_id))
            mapped_keys.add(part_key)

    technical = []
    used_id_shorts = set()
    for key, value in part.items():
        if key in mapped_keys or key in mapping.PART_TO_NAMEPLATE or not _present(value):
            continue
        # _id_short is not injective; disambiguate collisions so basyx does
        # not reject duplicate id_shorts within the collection (AASd-022).
        base = _id_short(key)
        id_short = base
        suffix = 1
        while id_short in used_id_shorts:
            suffix += 1
            # Truncate the base first so the suffix survives the length cap;
            # truncating afterwards would strip the suffix off a max-length
            # base and loop forever.
            tail = f"_{suffix}"
            id_short = base[:_ID_SHORT_MAX - len(tail)] + tail
        used_id_shorts.add(id_short)
        technical.append(_property(id_short, value))

    collections = [
        model.SubmodelElementCollection(id_short="GeneralInformation", value=general)
    ]
    if technical:
        collections.append(
            model.SubmodelElementCollection(id_short="TechnicalProperties", value=technical)
        )
    return model.Submodel(
        id_=make_identifier("sm:technical-data", owner_name),
        id_short="TechnicalData",
        semantic_id=_external_ref(mapping.TECHNICAL_DATA_SEMANTIC_ID),
        submodel_element=collections,
    )


def build_handover_documentation(document_files: list, owner_name: str) -> model.Submodel:
    """Handover Documentation (IDTA 02004) submodel referencing embedded files.

    Args:
        document_files: list of package-internal paths (e.g. "/aasx/docs/x.pdf")
    """
    elements = []
    for i, internal_path in enumerate(document_files, start=1):
        elements.append(
            model.SubmodelElementCollection(
                id_short=f"Document{i:02d}",
                value=[
                    model.File(
                        id_short="DigitalFile",
                        content_type=_guess_content_type(internal_path),
                        value=internal_path,
                    )
                ],
            )
        )
    return model.Submodel(
        id_=make_identifier("sm:handover-documentation", owner_name),
        id_short="HandoverDocumentation",
        semantic_id=_external_ref(mapping.HANDOVER_DOC_SEMANTIC_ID),
        submodel_element=elements,
    )


def build_shell(name: str, kind: str, submodels: list) -> model.AssetAdministrationShell:
    """Asset Administration Shell referencing the given submodels."""
    return model.AssetAdministrationShell(
        id_=make_identifier("aas", name),
        id_short=_id_short(name),
        asset_information=model.AssetInformation(
            asset_kind=model.AssetKind.INSTANCE,
            global_asset_id=make_identifier(f"asset:{kind}", name),
        ),
        submodel={model.ModelReference.from_referable(sm) for sm in submodels},
    )


def write_aasx(output_path: str, shells: list, submodels: list, embedded_files: dict = None) -> dict:
    """Write shells + submodels (+ optional embedded files) to a .aasx package.

    Args:
        output_path: target .aasx path
        shells: AssetAdministrationShell objects
        submodels: Submodel objects
        embedded_files: {package_internal_path: local_file_path} to embed,
            e.g. {"/aasx/docs/manual.pdf": "C:/exports/manual.pdf"}

    Returns:
        summary dict
    """
    object_store = model.DictObjectStore()
    seen_ids = set()
    for obj in list(shells) + list(submodels):
        if obj.id in seen_ids:
            # Distinct inputs collapsed to the same identifier (e.g. two part
            # numbers with the same slug, or a project named like a part).
            raise ValueError(
                f"Duplicate AAS identifier {obj.id!r} - two items map to the "
                f"same id. Rename them or export separately."
            )
        seen_ids.add(obj.id)
        object_store.add(obj)

    file_store = aasx.DictSupplementaryFileContainer()
    for internal_path, local_path in (embedded_files or {}).items():
        with open(local_path, "rb") as f:
            file_store.add_file(internal_path, f, _guess_content_type(local_path))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with aasx.AASXWriter(output_path) as writer:
        writer.write_aas(
            aas_ids=[shell.id for shell in shells],
            object_store=object_store,
            file_store=file_store,
        )
    return {
        "output_path": os.path.abspath(output_path),
        "shells": [shell.id for shell in shells],
        "submodels": [sm.id for sm in submodels],
        "embedded_files": list((embedded_files or {}).keys()),
    }


def read_aasx(aasx_path: str):
    """Read a .aasx package. Returns (object_store, file_store)."""
    object_store = model.DictObjectStore()
    file_store = aasx.DictSupplementaryFileContainer()
    with aasx.AASXReader(aasx_path) as reader:
        reader.read_into(object_store=object_store, file_store=file_store)
    return object_store, file_store
