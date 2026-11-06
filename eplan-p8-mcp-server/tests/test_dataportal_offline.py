"""
The Data Portal tools build the add-in's actions correctly, without EPLAN.

The parameter rules were measured on EPLAN 2026.0.3 (see the module docstring):
PARTNR<i> and PARTID<i> are both required and indexes start at 1. These tests
check the script that is sent, and that a queue result always tells the
assistant to ask the user to download the list in EPLAN.
"""

import pytest

from api.actions import dataportal


@pytest.fixture
def sent(monkeypatch):
    scripts = []

    def fake(script, timeout=30.0):
        scripts.append(script)
        return {"success": True, "results": {"success": True, "executed": True, "context": {"result": "7"}}}

    monkeypatch.setattr(dataportal, "_execute_script", fake)
    return scripts


def test_queue_sends_numbered_part_and_id_pairs_from_one(sent):
    result = dataportal.dataportal_add_to_download_list([
        {"part_number": "DEMO.CT-100", "dataportal_id": "11"},
        {"part_number": "DEMO.CT-200", "dataportal_id": 12},
    ])
    script = sent[0]
    assert 'ctx.AddParameter("PARTNR1", "DEMO.CT-100");' in script
    assert 'ctx.AddParameter("PARTID1", "11");' in script
    assert 'ctx.AddParameter("PARTNR2", "DEMO.CT-200");' in script
    assert 'ctx.AddParameter("PARTID2", "12");' in script
    assert "PARTNR0" not in script
    assert "EDPCloudAddPartsToBasketAction" in script
    assert result["queued"] == ["DEMO.CT-100", "DEMO.CT-200"]
    assert "download" in result["userAction"].lower()
    assert "DEMO.CT-200" in result["userAction"]


def test_queue_refuses_a_part_without_a_numeric_id(sent):
    result = dataportal.dataportal_add_to_download_list([{"part_number": "DEMO.CT-100"}])
    assert result["success"] is False
    assert not sent
    result = dataportal.dataportal_add_to_download_list([{"part_number": "X", "dataportal_id": "id-11"}])
    assert result["success"] is False
    assert dataportal.dataportal_add_to_download_list([])["success"] is False


def test_queue_explains_executed_false(monkeypatch):
    monkeypatch.setattr(
        dataportal, "_execute_script",
        lambda script, timeout=30.0: {"success": True, "results": {"success": True, "executed": False}},
    )
    result = dataportal.dataportal_add_to_download_list([{"part_number": "A", "dataportal_id": "1"}])
    assert "already in the download list" in result["note"]
    assert result["userAction"]


def test_part_numbers_are_escaped_for_csharp(sent):
    dataportal.dataportal_add_to_download_list([{"part_number": 'A"); Evil(); ("', "dataportal_id": "1"}])
    assert 'ctx.AddParameter("PARTNR1", "A\\"); Evil(); (\\"");' in sent[0]


def test_search_count_reads_the_result(sent):
    result = dataportal.dataportal_search_count("CT-100")
    assert result["count"] == 7
    assert 'ctx.AddParameter("search", "CT-100");' in sent[0]
    assert "EDPCloudGetSearchCountAction" in sent[0]
