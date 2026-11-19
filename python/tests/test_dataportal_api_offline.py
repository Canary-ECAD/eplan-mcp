"""
The Data Portal web API tools shape requests and answers correctly, without network.

The response shapes below are trimmed copies of what dataportal.eplan.com/api
returned on 2026-11-19 (see the module docstring for the routes that differ
from the published spec). _request is replaced, so nothing leaves the machine.
"""

import json

import pytest

from api.actions import dataportal_api as dp

PARTSCHECK = {"data": [
    {"type": "partscheckresult", "attributes": {
        "search": "SIE.5SL6316-7", "partid": 454767, "partnr": "SIE.5SL6316-7", "typenr": "5SL6316-7",
        "ordernr": "5SL6316-7", "upload_date": "2025-10-22", "data_supplier": "SIE",
        "url": "https://dataportal.eplan.com/part-details/SIE/SIE.5SL6316-7/id-454767"}},
    {"type": "partscheckresult", "attributes": {
        "search": "SIE.5SL6316-7", "partid": 454767, "partnr": "SIE.5SL6316-7", "data_supplier": "SIE"}},
    {"type": "partscheckmissingresult", "attributes": {"search": "NOPE.XYZ"}},
]}

PART = {"data": {"type": "parts", "id": "454767", "attributes": {
    "part_number": "SIE.5SL6316-7", "order_number": "5SL6316-7", "type_number": "5SL6316-7",
    "designation": {"en_US": "Miniature circuit breaker", "es_ES": "Interruptor"},
    "description": {"en_US": "MCB 3-pole C16"}, "data_supplier": "SIE",
    "lifecycle": {"value": 0, "name": "Active"}, "graphic_macro_path": "S\\x_3D.ema"},
    "relationships": {
        "manufacturer": {"data": {"type": "manufacturers", "id": "65"}},
        "product_group": {"data": {"type": "eplan_catalog_entries", "id": "200070000"}},
        "data_types": {"data": [{"type": "data_types", "id": "3d_graphical_data"}]},
        "graphic_macro": {"data": {"type": "macros", "id": "19832608"}},
        "group_symbol_macro": {"data": None},
        "eclass_level1": {"data": None}}},
    "included": [{"type": "manufacturers", "id": "65", "attributes": {"short_name": "SIE", "long_name": "Siemens"}}]}

MACRO = {"data": {"type": "macros", "id": "19832608", "attributes": {"name": "x_3D"}, "relationships": {
    "preview": {"data": {"type": "preview", "id": "S\\x_3D.ema"}},
    "macro_variants": {"data": [{"type": "macro_variants", "id": "69290004"}]}}}}
VARIANT = {"data": [{"type": "macro_variants", "id": "69290004",
                     "attributes": {"representation_type": 10, "variant": 0, "name": "", "description": ""}}]}


@pytest.fixture
def api(monkeypatch):
    calls = []
    answers = {}

    def fake(method, path, params=None, body=None, content_type=None, auth=False, raw=False):
        calls.append({"method": method, "path": path, "params": params or {}, "body": body, "auth": auth})
        answer = answers.get((method, path))
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise dp.DataPortalError(404, "HTTP 404")
        return answer

    monkeypatch.setattr(dp, "_request", fake)
    monkeypatch.delenv(dp.PAT_ENV, raising=False)
    return calls, answers


def test_find_parts_posts_one_value_per_line_and_splits_found_from_missing(api):
    calls, answers = api
    answers[("POST", "/partscheck")] = PARTSCHECK
    res = dp.dataportal_api_find_parts(["SIE.5SL6316-7", "NOPE.XYZ"])
    assert calls[0]["body"] == "SIE.5SL6316-7\nNOPE.XYZ"
    assert calls[0]["auth"] is False            # public route
    assert [f["dataportal_id"] for f in res["found"]] == ["454767"]   # repeated hit dropped
    assert res["missing"] == ["NOPE.XYZ"]


def test_search_uses_the_filter_names_the_live_api_accepts(api):
    calls, answers = api
    answers[("GET", "/parts")] = {"meta": {"page": {"offset": 0, "limit": 5, "total": 1}},
                                  "data": [PART["data"]]}
    res = dp.dataportal_api_search_parts("5SL", manufacturer="SIE", data_types=["3d_graphical_data", "dxf_data"],
                                         eds_min_version=1, sort="-download_count", limit=5, language="es_ES")
    p = calls[0]["params"]
    assert p["filter[data_types]"] == "3d_graphical_data,dxf_data"   # not filter[features]
    assert p["filter[manufacturer]"] == "SIE"
    assert p["filter[eplan_data_standard][ge]"] == 1
    assert p["page[limit]"] == 5 and p["sort"] == "-download_count"
    part = res["parts"][0]
    assert res["total"] == 1 and part["designation"] == "Interruptor"
    assert part["description"] == "MCB 3-pole C16"     # falls back to en_US
    assert part["url"].endswith("/SIE/SIE.5SL6316-7/id-454767")


def test_search_refuses_bad_arguments_without_calling(api):
    calls, _ = api
    assert dp.dataportal_api_search_parts("x", data_types=["features"])["success"] is False
    assert dp.dataportal_api_search_parts("x", sort="price")["success"] is False
    assert dp.dataportal_api_search_parts()["success"] is False
    assert dp.dataportal_api_search_parts("x" * 101)["success"] is False
    assert calls == []


def test_get_part_by_number_resolves_then_expands_macros(api):
    calls, answers = api
    answers[("POST", "/partscheck")] = PARTSCHECK
    answers[("GET", "/parts/454767")] = PART
    answers[("GET", "/macros/19832608")] = MACRO
    answers[("GET", "/macro_variants/69290004")] = VARIANT
    res = dp.dataportal_api_get_part(part_number="SIE.5SL6316-7")
    assert res["success"] is True
    assert res["manufacturer"]["long_name"] == "Siemens"
    assert res["part"]["product_group"] == "200070000"
    assert res["graphic_macro"]["variants"] == [{"macro_variant_id": "69290004", "representation_type": 10,
                                                 "variant": 0, "name": None, "description": None}]
    assert res["group_symbol_macro"] is None


def test_get_part_reports_an_unknown_number(api):
    _, answers = api
    answers[("POST", "/partscheck")] = {"data": [{"type": "partscheckmissingresult", "attributes": {"search": "X.Y"}}]}
    res = dp.dataportal_api_get_part(part_number="X.Y")
    assert res["success"] is False and res["errorType"] == "PartNotFound"


def test_catalog_merges_facet_counts_and_children(api):
    calls, answers = api
    answers[("GET", "/eplan_catalog_entries")] = {
        "meta": {"facets_counts": {"eplan_catalog": {"data": [{"id": "200070002", "count": 39066}]}}},
        "data": [{"type": "eplan_catalog_entries", "id": "200070002", "attributes": {"name": "General"}}]}
    res = dp.dataportal_api_catalog("eplan_catalog", parent="200070000")
    assert calls[0]["params"]["filter[catalog_eplan]"] == "200070000"
    assert res["entries"] == [{"id": "200070002", "name": "General", "count": 39066}]
    assert dp.dataportal_api_catalog("nope")["success"] is False
    assert dp.dataportal_api_catalog("suggestions")["success"] is False


def test_token_routes_refuse_without_a_pat_and_never_call(api):
    calls, _ = api
    for res in (dp.dataportal_api_download("e3d", macro_variant_id="1"),
                dp.dataportal_api_download_list("list")):
        assert res["success"] is False and res["errorType"] == "DataPortalTokenMissing"
        assert dp.PAT_ENV in res["userAction"]
    assert calls == []


def test_download_picks_the_route_and_saves_the_file(api, monkeypatch, tmp_path):
    calls, answers = api
    monkeypatch.setenv(dp.PAT_ENV, "secret-token")
    answers[("GET", "/download/e3d_data/69290004")] = (b"E3D", {"Content-Disposition": 'attachment; filename="x_3D.e3d"',
                                                              "Content-Type": "application/octet-stream"})
    answers[("POST", "/download/dxf_data/part")] = (b"PK", {})
    res = dp.dataportal_api_download("e3d", macro_variant_id="69290004", out_dir=str(tmp_path))
    assert res["success"] and res["bytes"] == 3
    assert (tmp_path / "x_3D.e3d").read_bytes() == b"E3D"
    res = dp.dataportal_api_download("dxf", part_ids=["1", "2"], out_dir=str(tmp_path))
    assert calls[-1]["body"] == "1,2" and calls[-1]["auth"] is True
    assert res["path"].endswith("dxf_data.zip")
    assert "secret-token" not in json.dumps(res)
    assert dp.dataportal_api_download("dxf", part_ids=["1"], from_download_list=True)["success"] is False


def test_download_list_add_resolves_part_numbers_and_sends_jsonapi(api, monkeypatch):
    calls, answers = api
    monkeypatch.setenv(dp.PAT_ENV, "t")
    answers[("POST", "/partscheck")] = PARTSCHECK
    answers[("POST", "/basketitems")] = {"data": [{"type": "basketitems", "id": "9"}]}
    res = dp.dataportal_api_download_list("add", parts=["SIE.5SL6316-7", {"dataportal_id": "12", "count": 3}])
    body = calls[-1]["body"]["data"]
    assert [b["relationships"]["part"]["data"]["id"] for b in body] == ["12", "454767"]
    assert body[0]["attributes"]["count"] == 3
    assert res["item_ids"] == ["9"] and "userAction" in res


def test_download_list_add_stops_on_an_unknown_part(api, monkeypatch):
    calls, answers = api
    monkeypatch.setenv(dp.PAT_ENV, "t")
    answers[("POST", "/partscheck")] = PARTSCHECK
    res = dp.dataportal_api_download_list("add", parts=["NOPE.XYZ"])
    assert res["errorType"] == "PartNotFound"
    assert all(c["path"] != "/basketitems" for c in calls)


def test_a_refused_token_is_named(api, monkeypatch):
    _, answers = api
    monkeypatch.setenv(dp.PAT_ENV, "t")
    answers[("GET", "/basketitems")] = dp.DataPortalError(401, "HTTP 401: Invalid token")
    res = dp.dataportal_api_download_list("list")
    assert res["errorType"] == "DataPortalUnauthorized" and res["httpStatus"] == 401


def test_downloads_with_the_same_name_do_not_overwrite(api, monkeypatch, tmp_path):
    _, answers = api
    monkeypatch.setenv(dp.PAT_ENV, "t")
    cd = {"Content-Disposition": 'attachment; filename="commercial_data.csv"'}
    answers[("GET", "/download/commercial_data/part/1")] = (b"one", cd)
    answers[("GET", "/download/commercial_data/part/2")] = (b"two", cd)
    first = dp.dataportal_api_download("commercial_data", part_ids=["1"], out_dir=str(tmp_path))
    second = dp.dataportal_api_download("commercial_data", part_ids=["2"], out_dir=str(tmp_path))
    assert first["path"] != second["path"]
    assert (tmp_path / "commercial_data.csv").read_bytes() == b"one"
    assert (tmp_path / "commercial_data_2.csv").read_bytes() == b"two"


def test_macro_variant_texts_come_in_one_language():
    # As /macro_variants returned it for SIE.6ES7512-1SM03-0AB0.
    text = "de_DE@CPU 1512SP F-1 PN\nPower Supply;en_US@CPU 1512SP F-1 PN\nRack layout;fr_FR@x;"
    assert dp._ml(text, "en_US") == "CPU 1512SP F-1 PN\nRack layout"
    assert dp._ml(text, "es_ES") == "CPU 1512SP F-1 PN\nRack layout"   # falls back to en_US
    assert dp._ml("plain", "en_US") == "plain" and dp._ml("", "en_US") is None
