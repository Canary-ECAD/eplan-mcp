"""Offline checks for pdf/dwg inspection, verify_actions, navigator_select and the live_objects additions."""

from api.actions import addons, inspect_files, navigation, objects

_DXF = "\n".join([
    "0", "SECTION", "2", "ENTITIES",
    "0", "TEXT", "8", "LAYER_A", "10", "1.5", "20", "2.5", "1", "Hello", "410", "Model",
    "0", "MTEXT", "8", "LAYER_B", "10", "3", "20", "4", "3", "Part one ", "1", "\\Lpart two", "410", "Sheet1",
    "0", "LINE", "8", "LAYER_A",
    "0", "ENDSEC", "0", "EOF", ""])


def test_dxf_texts_layouts_and_counts(tmp_path):
    p = tmp_path / "sheet.dxf"
    p.write_text(_DXF, encoding="utf-8")
    r = inspect_files.dwg_inspect(str(p))
    assert r["success"] and r["format"] == "dxf"
    assert r["layouts"] == ["Model", "Sheet1"]
    assert r["entity_counts"] == {"LINE": 1, "MTEXT": 1, "TEXT": 1}
    assert [t["value"] for t in r["texts"]] == ["Hello", "Part one \\Lpart two"]
    assert [t["underline_hint"] for t in r["texts"]] == [False, True]


def test_dxf_layer_filter_keeps_total(tmp_path):
    p = tmp_path / "sheet.dxf"
    p.write_text(_DXF, encoding="utf-8")
    r = inspect_files.dwg_inspect(str(p), layer_filter="^LAYER_B$")
    assert r["text_total"] == 2 and [t["layer"] for t in r["texts"]] == ["LAYER_B"]


def test_inspectors_reject_missing_and_wrong_files(tmp_path):
    assert inspect_files.pdf_inspect(str(tmp_path / "nope.pdf"))["success"] is False
    bad = tmp_path / "x.txt"
    bad.write_text("x")
    assert "unsupported extension" in inspect_files.dwg_inspect(str(bad))["error"]


def test_pdf_not_measured_is_none_not_zero(tmp_path):
    # goto_link_count must stay None when links were never counted.
    r = inspect_files.pdf_inspect(str(tmp_path / "nope.pdf"), include=["outline"])
    assert r["goto_link_count"] is None


def test_verify_actions_validates_names():
    assert addons.verify_actions([])["success"] is False
    assert "Invalid action names" in addons.verify_actions(["ok_name", "bad name;"])["error"]


def test_macrobox_kind_and_area_pseudo_prop():
    assert "macrobox" in objects.KINDS
    r = objects.live_objects_edit("macrobox", set={"area": "0,0,1,1"})
    assert r["success"] is False and "cannot be set" in r["error"]


def test_project_argument_is_escaped_into_script():
    body = objects._body("page", [], ["name"], {}, False, True, 10, project='a"b')
    assert 'PickProject(project, "a\\"b")' in body


def test_navigator_select_requires_connection_not_crash(monkeypatch):
    seen = {}
    monkeypatch.setattr(navigation, "_run_as_action",
                        lambda script, project: seen.setdefault("s", script) and {"success": True})
    navigation.navigator_select("Proj", pages=['=A+B/1', 'x"y'], open_page=False)
    s = seen["s"]
    assert 'PickProject(project, "Proj")' in s
    assert '"x\\"y"' in s and "bool allowOpen = false;" in s


def test_discard_removes_read_only_files(tmp_path):
    import os
    import stat

    from api.actions import fixtures
    edb = tmp_path / "x.edb" / "DOC"
    edb.mkdir(parents=True)
    f = edb / "external.dwg"
    f.write_text("x")
    os.chmod(f, stat.S_IREAD)
    fixtures._rmtree_writable(str(tmp_path / "x.edb"))
    assert not (tmp_path / "x.edb").exists()


def test_pdf_unreadable_page_is_not_counted_as_no_links(tmp_path, monkeypatch):
    import sys
    import types

    class Page:
        def __init__(self, ok):
            self.ok = ok

        def get_links(self):
            if not self.ok:
                raise RuntimeError("damaged page")
            return []

        def get_label(self):
            return None

        def annots(self):
            return []

    class Doc:
        is_encrypted = False
        page_count = 2

        def __getitem__(self, i):
            return Page(i == 0)

        def get_toc(self, simple=False):
            return []

        def close(self):
            pass

    fake = types.SimpleNamespace(open=lambda p: Doc(), LINK_GOTO=1, LINK_NAMED=4, LINK_URI=2)
    monkeypatch.setitem(sys.modules, "fitz", fake)
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    r = inspect_files.pdf_inspect(str(p))
    assert r["success"] and r["goto_link_count"] is None and r["unmeasured_pages"] == [1]


def test_verify_actions_rejects_trailing_newline():
    assert "Invalid action names" in addons.verify_actions(["Good_Name\n"])["error"]


def test_dxf_counts_only_drawn_entities_and_survives_bom(tmp_path):
    tables = "\n".join(["0", "SECTION", "2", "TABLES", "0", "LAYER", "2", "L1", "0", "ENDSEC", ""])
    p = tmp_path / "bom.dxf"
    p.write_text(tables + _DXF, encoding="utf-8-sig")
    r = inspect_files.dwg_inspect(str(p))
    assert r["entity_counts"] == {"LINE": 1, "MTEXT": 1, "TEXT": 1}
