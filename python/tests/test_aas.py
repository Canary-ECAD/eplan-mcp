"""Offline tests for the AAS package (mapping, builder, inspect, dry-run import).

Run from python/:  python -m pytest tests/ -v
No EPLAN needed - everything here is the pure-Python side of the AAS tools.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_server"))

from api.aas import builder, mapping  # noqa: E402
from api.aas.import_ import inspect_package, import_parts  # noqa: E402

SAMPLE_PART = {
    "PartNr": "SIE.3RV2011-1EA10",
    "Description1": "Circuit breaker size S00",
    "Description2": "",
    "Manufacturer": "SIE",
    "Supplier": "SIE",
    "OrderNr": "3RV2011-1EA10",
    "ProductGroup": "Motor overload protection",
    "ProductSubGroup": "Circuit breaker",
    "ProductTopGroup": "Electrical engineering",
}


def test_id_short_sanitization():
    # basyx AASd-002: idShort must START WITH A LETTER (not a digit, not '_').
    for raw in ["3RV2011-1EA10", "", "___", "9", "-x-"]:
        result = builder._id_short(raw)
        assert result[0].isalpha(), f"{raw!r} -> {result!r} must start with a letter"
    assert " " not in builder._id_short("my part name")
    assert len(builder._id_short("z" * 500)) <= 128


def test_id_short_accepted_by_basyx_for_leading_digit():
    # Regression: leading-digit part numbers used to crash export.
    from basyx.aas import model
    model.Property(id_short=builder._id_short("3RV2011-1EA10"),
                   value_type=model.datatypes.String, value="x")


def test_export_part_leading_digit_part_number(tmp_path):
    from api.aas.export_ import export_part
    from api.actions import scripted as scripted_mod

    part = dict(SAMPLE_PART, PartNr="3RV2011-1EA10")
    saved = scripted_mod.parts_db_get_part
    scripted_mod.parts_db_get_part = lambda pn: {"success": True, "results": {"found": True, "part": part}}
    try:
        out = str(tmp_path / "p.aasx")
        result = export_part("3RV2011-1EA10", out)
        assert result["success"], result
        assert os.path.isfile(out)
    finally:
        scripted_mod.parts_db_get_part = saved


def test_make_identifier_stable_and_safe():
    ident = builder.make_identifier("aas", "SIE.3RV2011-1EA10")
    assert ident == builder.make_identifier("aas", "SIE.3RV2011-1EA10")
    assert " " not in ident and ident.startswith(builder.ID_BASE)


def test_nameplate_maps_part_fields():
    sm = builder.build_nameplate(SAMPLE_PART, SAMPLE_PART["PartNr"])
    assert sm.id_short == "Nameplate"
    assert sm.semantic_id.key[0].value == mapping.NAMEPLATE_SEMANTIC_ID
    values = {e.id_short: e.value for e in sm.submodel_element}
    assert values["ManufacturerName"] == "SIE"
    assert values["ManufacturerProductDesignation"] == "Circuit breaker size S00"
    assert values["OrderCodeOfManufacturer"] == "3RV2011-1EA10"
    assert values["ProductArticleNumberOfManufacturer"] == "SIE.3RV2011-1EA10"


def test_nameplate_skips_empty_fields():
    sm = builder.build_nameplate({"Manufacturer": "SIE", "OrderNr": ""}, "x")
    id_shorts = [e.id_short for e in sm.submodel_element]
    assert id_shorts == ["ManufacturerName"]


def test_technical_data_general_information_and_extras():
    part = dict(SAMPLE_PART, VOLTAGE="690 V")
    sm = builder.build_technical_data(part, part["PartNr"])
    collections = {c.id_short: c for c in sm.submodel_element}
    general = {e.id_short: e.value for e in collections["GeneralInformation"].value}
    assert general["ManufacturerArticleNumber"] == "SIE.3RV2011-1EA10"
    technical = {e.id_short: e.value for e in collections["TechnicalProperties"].value}
    assert technical["VOLTAGE"] == "690 V"


def test_shell_references_submodels():
    sm = builder.build_nameplate(SAMPLE_PART, SAMPLE_PART["PartNr"])
    shell = builder.build_shell(SAMPLE_PART["PartNr"], "part", [sm])
    assert len(shell.submodel) == 1
    assert shell.asset_information.global_asset_id.startswith(builder.ID_BASE)


@pytest.fixture
def sample_aasx(tmp_path):
    submodels = [
        builder.build_nameplate(SAMPLE_PART, SAMPLE_PART["PartNr"]),
        builder.build_technical_data(SAMPLE_PART, SAMPLE_PART["PartNr"]),
    ]
    shell = builder.build_shell(SAMPLE_PART["PartNr"], "part", submodels)
    path = str(tmp_path / "part.aasx")
    summary = builder.write_aasx(path, [shell], submodels)
    assert os.path.isfile(path)
    assert summary["shells"] == [shell.id]
    return path


def test_roundtrip_inspect(sample_aasx):
    result = inspect_package(sample_aasx)
    assert result["success"]
    assert len(result["shells"]) == 1
    id_shorts = {sm["idShort"] for sm in result["submodels"]}
    assert id_shorts == {"Nameplate", "TechnicalData"}
    nameplate = next(sm for sm in result["submodels"] if sm["idShort"] == "Nameplate")
    assert nameplate["semanticId"] == mapping.NAMEPLATE_SEMANTIC_ID
    assert nameplate["properties"]["ManufacturerName"] == "SIE"


def test_inspect_missing_file():
    result = inspect_package("Z:/does/not/exist.aasx")
    assert result["success"] is False
    assert "error" in result


def test_import_dry_run_proposes_correct_writes(sample_aasx):
    result = import_parts(sample_aasx, dry_run=True)
    assert result["success"] and result["dryRun"]
    [plan] = result["proposed"]
    assert plan["partNumber"] == "SIE.3RV2011-1EA10"
    assert plan["fields"]["ARTICLE_MANUFACTURER"] == "SIE"
    assert plan["fields"]["ARTICLE_DESCR1"] == "Circuit breaker size S00"
    assert plan["fields"]["ARTICLE_ORDERNR"] == "3RV2011-1EA10"
    # ARTICLE_PARTNR is the identity, never a field write
    assert "ARTICLE_PARTNR" not in plan["fields"]


def test_export_project_offline_documents_only(tmp_path):
    from api.aas.export_ import export_project

    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")
    out = str(tmp_path / "project.aasx")
    result = export_project(
        "TestProject",
        out,
        document_paths=[str(doc), "Z:/missing.pdf"],
        properties={"ProjectName": "TestProject", "Customer": "ACME"},
    )
    assert result["success"], result
    assert result["missingDocuments"] == ["Z:/missing.pdf"]

    inspection = inspect_package(out)
    id_shorts = {sm["idShort"] for sm in inspection["submodels"]}
    assert id_shorts == {"TechnicalData", "HandoverDocumentation"}
    assert any("report" in f for f in inspection["embeddedFiles"])


def test_export_project_rejects_empty_export(tmp_path):
    from api.aas.export_ import export_project

    result = export_project("Empty", str(tmp_path / "e.aasx"))
    assert result["success"] is False


def test_export_project_duplicate_docs_both_embedded(tmp_path):
    from api.aas.export_ import export_project

    d1 = tmp_path / "a"; d1.mkdir(); (d1 / "report.pdf").write_bytes(b"%PDF-1")
    d2 = tmp_path / "b"; d2.mkdir(); (d2 / "report.pdf").write_bytes(b"%PDF-2")
    out = str(tmp_path / "proj.aasx")
    result = export_project("P", out, document_paths=[str(d1 / "report.pdf"), str(d2 / "report.pdf")],
                            properties={"Customer": "ACME"})
    assert result["success"], result
    inspection = inspect_package(out)
    # Both documents survive (disambiguated), not silently collapsed to one.
    assert len(inspection["embeddedFiles"]) == 2


def test_export_project_duplicate_identifier_clean_error(tmp_path):
    from api.aas.export_ import export_project
    from api.actions import scripted as scripted_mod

    saved = scripted_mod.parts_db_get_part
    scripted_mod.parts_db_get_part = lambda pn: {"success": True, "results": {"found": True, "part": dict(SAMPLE_PART, PartNr=pn)}}
    try:
        # project_name equals a part number -> colliding AAS id must be a clean
        # error dict, not an uncaught exception.
        result = export_project("DUP", str(tmp_path / "d.aasx"),
                                part_numbers=["DUP"], properties={"x": "y"})
        assert result["success"] is False
        assert "identifier" in result["error"].lower() or "duplicate" in result["error"].lower()
    finally:
        scripted_mod.parts_db_get_part = saved


def test_import_reads_multilanguage_property(tmp_path):
    from basyx.aas import model

    nameplate = model.Submodel(
        id_=builder.make_identifier("sm:nameplate", "MLP"),
        id_short="Nameplate",
        semantic_id=builder._external_ref(mapping.NAMEPLATE_SEMANTIC_ID),
        submodel_element=[
            model.MultiLanguageProperty(
                id_short="ManufacturerName",
                value=model.MultiLanguageTextType({"de": "Siemens AG", "en": "Siemens"}),
            ),
            model.MultiLanguageProperty(
                id_short="ProductArticleNumberOfManufacturer",
                value=model.MultiLanguageTextType({"en": "3RV-XYZ"}),
            ),
        ],
    )
    shell = builder.build_shell("MLP", "part", [nameplate])
    path = str(tmp_path / "mlp.aasx")
    builder.write_aasx(path, [shell], [nameplate])

    result = import_parts(path, dry_run=True)
    assert result["success"] and result["dryRun"]
    [plan] = result["proposed"]
    assert plan["partNumber"] == "3RV-XYZ"
    # Prefers English text out of the MLP.
    assert plan["fields"]["ARTICLE_MANUFACTURER"] == "Siemens"


def test_technical_data_colliding_extra_keys_no_crash():
    # Two keys that sanitize to the same idShort must not raise (AASd-022).
    part = {"Manufacturer": "SIE", "a b": "1", "a_b": "2"}
    sm = builder.build_technical_data(part, "collide")
    tech = next(c for c in sm.submodel_element if c.id_short == "TechnicalProperties")
    id_shorts = [e.id_short for e in tech.value]
    assert len(id_shorts) == len(set(id_shorts))  # all unique


def test_export_part_content_type_from_extension(tmp_path):
    from api.aas.export_ import export_project

    doc = tmp_path / "data.xlsx"
    doc.write_bytes(b"PK\x03\x04fake")
    out = str(tmp_path / "ct.aasx")
    result = export_project("CT", out, document_paths=[str(doc)], properties={"x": "y"})
    assert result["success"], result
    inspection = inspect_package(out)
    hd = next(sm for sm in inspection["submodels"] if sm["idShort"] == "HandoverDocumentation")
    # Not falsely labelled application/pdf.
    assert "data" in " ".join(inspection["embeddedFiles"])
