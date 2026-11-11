"""Corner-case tests for api/aas/import_.py and export_.py.

The grouping logic of import_parts is tested against hand-built inspection
dicts (inspect_package patched); the live-import path runs against mocked
parts_db_* functions. No EPLAN needed.
"""

import pytest
from basyx.aas import model

from api.aas import builder, mapping
from api.aas import import_ as import_mod
from api.aas.import_ import _iter_properties, _mlp_text, import_parts, inspect_package
from api.actions import scripted


PART = {
    "PartNr": "SIE.3RV2011-1EA10",
    "Description1": "Circuit breaker",
    "Manufacturer": "SIE",
    "OrderNr": "3RV2011-1EA10",
}


def _inspection(shells, submodels):
    return {"success": True, "shells": shells, "submodels": submodels,
            "embeddedFiles": [], "path": "fake.aasx"}


@pytest.fixture
def fake_inspection(monkeypatch):
    def set_result(shells, submodels):
        monkeypatch.setattr(import_mod, "inspect_package",
                            lambda path: _inspection(shells, submodels))
    return set_result


# ---------------------------------------------------------------------------
# _mlp_text / _iter_properties
# ---------------------------------------------------------------------------

def test_mlp_text_prefers_english_variants():
    mlp = model.MultiLanguageProperty(
        id_short="N", value=model.MultiLanguageTextType({"de": "DE", "en-GB": "GB"}))
    assert _mlp_text(mlp) == "GB"


def test_mlp_text_falls_back_to_any_language():
    mlp = model.MultiLanguageProperty(
        id_short="N", value=model.MultiLanguageTextType({"fr": "FR"}))
    assert _mlp_text(mlp) == "FR"


def test_mlp_text_none_value():
    mlp = model.MultiLanguageProperty(id_short="N")
    assert _mlp_text(mlp) is None


def test_iter_properties_recurses_nested_collections():
    inner = model.SubmodelElementCollection(id_short="Inner", value=[
        model.Property(id_short="Deep", value_type=model.datatypes.String, value="d"),
    ])
    outer = model.SubmodelElementCollection(id_short="Outer", value=[inner])
    assert dict(_iter_properties(outer)) == {"Deep": "d"}


def test_iter_properties_ignores_non_property_elements():
    f = model.File(id_short="F", content_type="application/pdf", value="/aasx/x.pdf")
    assert list(_iter_properties(f)) == []


# ---------------------------------------------------------------------------
# import_parts grouping (patched inspection)
# ---------------------------------------------------------------------------

def test_import_package_without_shells_merges_all_submodels(fake_inspection):
    fake_inspection([], [
        {"id": "sm1", "idShort": "Nameplate", "semanticId": None,
         "properties": {"ManufacturerName": "SIE"}},
        {"id": "sm2", "idShort": "TechnicalData", "semanticId": None,
         "properties": {"ManufacturerArticleNumber": "PN-9"}},
    ])
    result = import_parts("fake.aasx", dry_run=True)
    assert result["success"]
    [plan] = result["proposed"]
    assert plan["partNumber"] == "PN-9"
    assert plan["fields"]["ARTICLE_MANUFACTURER"] == "SIE"


def test_import_shell_with_dangling_submodel_ref_is_skipped(fake_inspection):
    fake_inspection(
        [{"id": "aas1", "idShort": "S", "globalAssetId": "g",
          "submodelRefs": ["missing-id", None]}],
        [{"id": "sm1", "idShort": "Nameplate", "semanticId": None,
          "properties": {"ManufacturerName": "SIE"}}],
    )
    result = import_parts("fake.aasx", dry_run=True)
    # Shell resolves no submodels -> no plans -> clean error, not a crash.
    assert result["success"] is False
    assert "No importable" in result["error"]


def test_import_duplicate_part_numbers_yield_single_plan(fake_inspection):
    sm = {"id": "sm1", "idShort": "Nameplate", "semanticId": None,
          "properties": {"ProductArticleNumberOfManufacturer": "PN-1"}}
    fake_inspection(
        [{"id": "a1", "idShort": "S1", "globalAssetId": "g", "submodelRefs": ["sm1"]},
         {"id": "a2", "idShort": "S2", "globalAssetId": "g", "submodelRefs": ["sm1"]}],
        [sm],
    )
    result = import_parts("fake.aasx", dry_run=True)
    assert len(result["proposed"]) == 1


def test_import_part_number_fallback_order(fake_inspection):
    fake_inspection(
        [{"id": "a1", "idShort": "S1", "globalAssetId": "g", "submodelRefs": ["sm1"]}],
        [{"id": "sm1", "idShort": "Nameplate", "semanticId": None,
          "properties": {"OrderCodeOfManufacturer": "ORD-7", "ManufacturerName": "M"}}],
    )
    result = import_parts("fake.aasx", dry_run=True)
    [plan] = result["proposed"]
    assert plan["partNumber"] == "ORD-7"


def test_import_unidentified_shell_counted(fake_inspection):
    fake_inspection(
        [{"id": "a1", "idShort": "S1", "globalAssetId": "g", "submodelRefs": ["sm1"]}],
        [{"id": "sm1", "idShort": "Nameplate", "semanticId": None,
          "properties": {"ManufacturerName": "OnlyName"}}],
    )
    result = import_parts("fake.aasx", dry_run=True)
    assert result["unidentified"] == 1
    assert result["proposed"][0]["partNumber"] is None


def test_import_failed_inspection_propagates(monkeypatch):
    monkeypatch.setattr(import_mod, "inspect_package",
                        lambda path: {"success": False, "error": "boom"})
    result = import_parts("fake.aasx", dry_run=True)
    assert result == {"success": False, "error": "boom"}


# ---------------------------------------------------------------------------
# import_parts live path (mocked parts_db_*)
# ---------------------------------------------------------------------------

def _single_part_inspection():
    return (
        [{"id": "a1", "idShort": "S1", "globalAssetId": "g", "submodelRefs": ["sm1"]}],
        [{"id": "sm1", "idShort": "Nameplate", "semanticId": None,
          "properties": {"ProductArticleNumberOfManufacturer": "PN-1",
                         "ManufacturerName": "SIE"}}],
    )


def test_live_import_creates_missing_part(fake_inspection, monkeypatch):
    fake_inspection(*_single_part_inspection())
    calls = {}

    def fake_create(pn, fields):
        calls["create"] = (pn, fields)
        return {"success": True, "results": {"success": True}}

    monkeypatch.setattr(scripted, "parts_db_get_part",
                        lambda pn: {"success": True, "results": {"found": False}})
    monkeypatch.setattr(scripted, "parts_db_create", fake_create)
    result = import_parts("fake.aasx", dry_run=False)
    assert result["success"] and not result["dryRun"]
    [outcome] = result["outcomes"]
    assert outcome["status"] == "created"
    assert calls["create"][0] == "PN-1"
    assert calls["create"][1] == {"ARTICLE_MANUFACTURER": "SIE"}


def test_live_import_updates_existing_part(fake_inspection, monkeypatch):
    fake_inspection(*_single_part_inspection())
    updates = []
    monkeypatch.setattr(scripted, "parts_db_get_part",
                        lambda pn: {"success": True, "results": {"found": True}})
    monkeypatch.setattr(scripted, "parts_db_update",
                        lambda pn, prop, val: updates.append((pn, prop, val))
                        or {"success": True, "results": {"success": True}})
    result = import_parts("fake.aasx", dry_run=False)
    [outcome] = result["outcomes"]
    assert outcome["status"] == "updated"
    assert outcome["updated"] == ["ARTICLE_MANUFACTURER"]
    assert updates == [("PN-1", "ARTICLE_MANUFACTURER", "SIE")]


def test_live_import_records_failed_updates(fake_inspection, monkeypatch):
    fake_inspection(*_single_part_inspection())
    monkeypatch.setattr(scripted, "parts_db_get_part",
                        lambda pn: {"success": True, "results": {"found": True}})
    monkeypatch.setattr(scripted, "parts_db_update",
                        lambda pn, prop, val: {"success": False})
    result = import_parts("fake.aasx", dry_run=False)
    [outcome] = result["outcomes"]
    assert outcome["failed"] == ["ARTICLE_MANUFACTURER"]
    assert outcome["updated"] == []


def test_live_import_reports_create_failure(fake_inspection, monkeypatch):
    fake_inspection(*_single_part_inspection())
    monkeypatch.setattr(scripted, "parts_db_get_part",
                        lambda pn: {"success": True, "results": {"found": False}})
    monkeypatch.setattr(scripted, "parts_db_create",
                        lambda pn, fields: {"success": True,
                                            "results": {"success": False, "error": "db locked"}})
    result = import_parts("fake.aasx", dry_run=False)
    [outcome] = result["outcomes"]
    assert outcome["status"] == "create-failed"
    assert outcome["error"] == "db locked"


def test_live_import_skips_unidentified_shell(fake_inspection, monkeypatch):
    fake_inspection(
        [{"id": "a1", "idShort": "S1", "globalAssetId": "g", "submodelRefs": ["sm1"]}],
        [{"id": "sm1", "idShort": "Nameplate", "semanticId": None,
          "properties": {"ManufacturerName": "OnlyName"}}],
    )
    monkeypatch.setattr(scripted, "parts_db_get_part",
                        lambda pn: pytest.fail("must not query parts DB without a part number"))
    result = import_parts("fake.aasx", dry_run=False)
    [outcome] = result["outcomes"]
    assert outcome["status"] == "skipped"


# ---------------------------------------------------------------------------
# inspect_package corner cases (real files)
# ---------------------------------------------------------------------------

def test_inspect_valid_zip_but_not_aasx(tmp_path):
    import zipfile
    p = tmp_path / "notopc.aasx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    result = inspect_package(str(p))
    assert result["success"] is False
    assert "error" in result


def test_inspect_garbage_bytes(tmp_path):
    p = tmp_path / "garbage.aasx"
    p.write_bytes(b"definitely not a zip")
    result = inspect_package(str(p))
    assert result["success"] is False


# ---------------------------------------------------------------------------
# export_part / export_project corner cases
# ---------------------------------------------------------------------------

def _patch_get_part(monkeypatch, response):
    monkeypatch.setattr(scripted, "parts_db_get_part", lambda pn: response)


def test_export_part_lookup_failure(tmp_path, monkeypatch):
    from api.aas.export_ import export_part
    _patch_get_part(monkeypatch, {"success": False, "message": "not connected"})
    result = export_part("PN", str(tmp_path / "x.aasx"))
    assert result["success"] is False
    assert "not connected" in result["error"]


def test_export_part_not_found(tmp_path, monkeypatch):
    from api.aas.export_ import export_part
    _patch_get_part(monkeypatch, {"success": True, "results": {"found": False}})
    result = export_part("PN", str(tmp_path / "x.aasx"))
    assert result["success"] is False
    assert "PN" in result["error"]


def test_export_part_without_technical_data(tmp_path, monkeypatch):
    from api.aas.export_ import export_part
    _patch_get_part(monkeypatch,
                    {"success": True, "results": {"found": True, "part": dict(PART)}})
    out = str(tmp_path / "np.aasx")
    result = export_part(PART["PartNr"], out, include_technical_data=False)
    assert result["success"], result
    inspection = inspect_package(out)
    assert {sm["idShort"] for sm in inspection["submodels"]} == {"Nameplate"}


def test_export_project_duplicate_parts_looked_up_once(tmp_path, monkeypatch):
    from api.aas.export_ import export_project
    lookups = []

    def get_part(pn):
        lookups.append(pn)
        return {"success": True, "results": {"found": True, "part": dict(PART, PartNr=pn)}}

    monkeypatch.setattr(scripted, "parts_db_get_part", get_part)
    result = export_project("Proj", str(tmp_path / "p.aasx"),
                            part_numbers=["PN-1", "PN-1", "PN-2"])
    assert result["success"], result
    assert lookups == ["PN-1", "PN-2"]


def test_export_project_part_errors_reported_on_success(tmp_path, monkeypatch):
    from api.aas.export_ import export_project
    _patch_get_part(monkeypatch, {"success": True, "results": {"found": False}})
    result = export_project("Proj", str(tmp_path / "p.aasx"),
                            part_numbers=["GHOST"], properties={"Customer": "ACME"})
    assert result["success"], result
    assert result["partErrors"] == {"GHOST": "not found"}


def test_export_project_all_docs_missing_and_nothing_else(tmp_path):
    from api.aas.export_ import export_project
    result = export_project("Proj", str(tmp_path / "p.aasx"),
                            document_paths=["Z:/nope1.pdf", "Z:/nope2.pdf"])
    assert result["success"] is False
    assert result["missingDocuments"] == ["Z:/nope1.pdf", "Z:/nope2.pdf"]


def test_export_project_properties_only(tmp_path):
    from api.aas.export_ import export_project
    out = str(tmp_path / "props.aasx")
    result = export_project("Proj", out, properties={"Customer": "ACME"})
    assert result["success"], result
    inspection = inspect_package(out)
    assert {sm["idShort"] for sm in inspection["submodels"]} == {"TechnicalData"}
    assert inspection["submodels"][0]["properties"]["Customer"] == "ACME"


def test_export_then_import_roundtrip_dry_run(tmp_path, monkeypatch):
    # Full circle: export a part, then propose importing it back.
    from api.aas.export_ import export_part
    _patch_get_part(monkeypatch,
                    {"success": True, "results": {"found": True, "part": dict(PART)}})
    out = str(tmp_path / "rt.aasx")
    assert export_part(PART["PartNr"], out)["success"]

    result = import_parts(out, dry_run=True)
    assert result["success"]
    [plan] = result["proposed"]
    assert plan["partNumber"] == PART["PartNr"]
    assert plan["fields"]["ARTICLE_MANUFACTURER"] == PART["Manufacturer"]
    assert plan["fields"]["ARTICLE_ORDERNR"] == PART["OrderNr"]
