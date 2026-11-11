"""Corner-case tests for api/aas/builder.py (pure offline)."""

import threading

import pytest

from api.aas import builder, mapping


# ---------------------------------------------------------------------------
# _slug / _id_short / _present
# ---------------------------------------------------------------------------

def test_slug_empty_and_symbol_only_inputs():
    assert builder._slug("") == "unnamed"
    assert builder._slug("///") == "unnamed"
    assert builder._slug(None) == "None"  # str() first, then sanitized
    assert builder._slug("a b/c") == "a-b-c"
    # dots, dashes and underscores survive (IRI-safe)
    assert builder._slug("SIE.3RV_2011-1") == "SIE.3RV_2011-1"


def test_id_short_keeps_valid_names_verbatim():
    assert builder._id_short("ManufacturerName") == "ManufacturerName"
    assert builder._id_short("A1_b2") == "A1_b2"


def test_id_short_exactly_at_cap():
    name = "a" * 128
    assert builder._id_short(name) == name
    assert len(builder._id_short("a" * 129)) == 128


def test_id_short_leading_digit_after_truncation_still_letter_first():
    # 128 digits: prefix must be applied before the cap is enforced.
    result = builder._id_short("9" * 128)
    assert result[0].isalpha()
    assert len(result) <= 128


def test_present_keeps_meaningful_falsy_values():
    assert builder._present(0)
    assert builder._present(False)
    assert builder._present("0")
    assert not builder._present(None)
    assert not builder._present("")


# ---------------------------------------------------------------------------
# Submodel builders
# ---------------------------------------------------------------------------

def test_nameplate_from_empty_part_is_valid_but_empty():
    sm = builder.build_nameplate({}, "empty")
    assert sm.id_short == "Nameplate"
    assert list(sm.submodel_element) == []


def test_technical_data_keeps_falsy_extra_values():
    part = {"Manufacturer": "SIE", "Stock": 0}
    sm = builder.build_technical_data(part, "falsy")
    tech = next(c for c in sm.submodel_element if c.id_short == "TechnicalProperties")
    values = {e.id_short: e.value for e in tech.value}
    assert values["Stock"] == "0"


def test_technical_data_no_extras_omits_technical_properties():
    sm = builder.build_technical_data({"Manufacturer": "SIE"}, "min")
    id_shorts = [c.id_short for c in sm.submodel_element]
    assert id_shorts == ["GeneralInformation"]


def test_technical_data_long_colliding_keys_terminate():
    # Two keys that sanitize to the same 128-char (max-length) idShort used
    # to send the disambiguation loop into an infinite spin: the suffix was
    # appended and then truncated straight back off.
    part = {"Manufacturer": "SIE", "z" * 130: "1", "z" * 131: "2", "z" * 132: "3"}
    holder = {}

    def build():
        holder["sm"] = builder.build_technical_data(part, "long-collide")

    worker = threading.Thread(target=build, daemon=True)
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive(), "build_technical_data hangs on max-length colliding keys"

    tech = next(c for c in holder["sm"].submodel_element if c.id_short == "TechnicalProperties")
    id_shorts = [e.id_short for e in tech.value]
    assert len(id_shorts) == 3
    assert len(id_shorts) == len(set(id_shorts))
    assert all(len(s) <= 128 for s in id_shorts)


def test_handover_documentation_numbering_and_content_types():
    sm = builder.build_handover_documentation(
        ["/aasx/docs/manual.pdf", "/aasx/docs/data.bin"], "proj"
    )
    collections = list(sm.submodel_element)
    assert [c.id_short for c in collections] == ["Document01", "Document02"]
    files = {list(c.value)[0].value: list(c.value)[0].content_type for c in collections}
    assert files["/aasx/docs/manual.pdf"] == "application/pdf"
    # Unknown extension falls back instead of mislabeling.
    assert files["/aasx/docs/data.bin"] == "application/octet-stream"


def test_build_shell_sanitizes_id_short():
    sm = builder.build_nameplate({"Manufacturer": "M"}, "3RV 2011")
    shell = builder.build_shell("3RV 2011", "part", [sm])
    assert shell.id_short[0].isalpha()
    assert " " not in shell.id_short


# ---------------------------------------------------------------------------
# write_aasx error handling
# ---------------------------------------------------------------------------

def test_write_aasx_duplicate_identifier_raises_value_error(tmp_path):
    sm = builder.build_nameplate({"Manufacturer": "M"}, "X")
    shell = builder.build_shell("X", "part", [sm])
    shell2 = builder.build_shell("X", "part", [sm])
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        builder.write_aasx(str(tmp_path / "dup.aasx"), [shell, shell2], [sm])


def test_write_aasx_missing_embedded_file_raises(tmp_path):
    sm = builder.build_nameplate({"Manufacturer": "M"}, "Y")
    shell = builder.build_shell("Y", "part", [sm])
    with pytest.raises(OSError):
        builder.write_aasx(
            str(tmp_path / "m.aasx"), [shell], [sm],
            embedded_files={"/aasx/docs/x.pdf": str(tmp_path / "does-not-exist.pdf")},
        )


def test_write_aasx_creates_missing_parent_dirs(tmp_path):
    sm = builder.build_nameplate({"Manufacturer": "M"}, "Z")
    shell = builder.build_shell("Z", "part", [sm])
    out = tmp_path / "deep" / "nested" / "out.aasx"
    summary = builder.write_aasx(str(out), [shell], [sm])
    assert out.is_file()
    assert summary["shells"] == [shell.id]


def test_make_identifier_distinct_kinds_do_not_collide():
    assert builder.make_identifier("aas", "X") != builder.make_identifier("asset:part", "X")


def test_mapping_part_number_idshorts_are_importable():
    # Every idShort used for part identification must have a parts-DB mapping,
    # and the two primary ones must map to the part-number property itself.
    for id_short in mapping.PART_NUMBER_IDSHORTS:
        assert id_short in mapping.IDSHORT_TO_PARTS_DB
    assert mapping.IDSHORT_TO_PARTS_DB["ProductArticleNumberOfManufacturer"] == "ARTICLE_PARTNR"
    assert mapping.IDSHORT_TO_PARTS_DB["ManufacturerArticleNumber"] == "ARTICLE_PARTNR"
