"""Offline tests for api/actions/ops.py and target.py.

No EPLAN: the script runner and the action manager are replaced by stubs
that capture what would have been sent and answer with canned results.
"""

import json
import os

import pytest

from api.actions import _base, live, ops, scripted, target


@pytest.fixture(autouse=True)
def _no_target():
    target.set_target("")
    yield
    target.set_target("")


class FakeManager:
    """Stands in for the connection manager; records any direct action."""

    def __init__(self):
        self.calls = []

    def execute_action(self, action, quiet_mode=False):
        self.calls.append(action)
        return {"success": True}


@pytest.fixture
def one_shot(monkeypatch, tmp_path):
    """Force the one-shot engine and capture the script it would run."""
    captured = {}
    manager = FakeManager()
    captured["manager"] = manager
    monkeypatch.setattr(ops, "_get_connected_manager", lambda: (manager, None))
    monkeypatch.setattr(ops, "OPS_DIR", str(tmp_path / "ops"))
    monkeypatch.setattr(scripted, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(scripted, "SCRIPT_DIR", str(tmp_path / "generated"))

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        captured["timeout"] = timeout
        ops_path = script.split('RunOps(@"')[1].split('"')[0].replace("\\\\", "\\")
        captured["request"] = json.load(open(ops_path, encoding="utf-8"))
        return {"success": True, "results": captured.get("canned") or {
            "success": True, "project": "P", "page": "=+CE/0",
            "ops": [{"index": 0, "op": "place", "success": True, "handle": "1/2/3/0",
                     "route": "Create(Page,SymbolVariant)+Location", "name": "=+CE-X1:1",
                     "placed": {"handle": "1/2/3/0", "clrType": "Terminal"}}],
            "labels": {"t": "1/2/3/0"}, "failed": 0, "allOk": True}}

    monkeypatch.setattr(scripted, "_execute_script", fake_execute)
    return captured


# ---------------------------------------------------------------------------
# The interpreter source
# ---------------------------------------------------------------------------

def test_interpreter_has_the_traps_covered():
    cs = ops._interpreter_source("McpOps_t")
    for line in cs.splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line
    assert "?." not in cs                      # C# 5 floor
    assert "LockingStep" in cs and 'GetMethod("Dispose")' in cs
    assert "ResolveProject(" in cs and "GuardScratch(" in cs
    assert "[DeclareAction" not in cs, "nothing may be registered in EPLAN"
    assert "[Start]" in cs
    for op in ("place", "rect", "macro", "update", "move", "remove", "dimension", "line", "text", "find", "read"):
        assert 'case "%s":' % op in cs


def test_the_target_project_token_is_substituted():
    """Left as the literal token, "{{TARGET_PROJECT}}".Length > 0 is always true."""
    cs = ops._interpreter_source("McpOps_t")
    assert "{{TARGET_PROJECT}}" not in cs
    assert '"".Length > 0' in cs, "no target pinned: no explicit lock"
    path = r"C:\scratch\P.elk"
    target.set_target(path)
    assert '"%s".Length > 0' % _base.cs_escape(path) in ops._interpreter_source("McpOps_t")


# ---------------------------------------------------------------------------
# One-shot engine
# ---------------------------------------------------------------------------

def test_batch_writes_the_request_and_runs_one_script(one_shot):
    out = ops.live_batch("=+CE/0", [{"op": "place", "library": "SPECIAL", "symbol": "X2_1",
                                     "x": 80, "y": 200, "label": "t", "tag": "=+CE-X1:1"}],
                         read_back=True, timeout_seconds=42)
    assert out["success"] is True
    assert out["engine"] == "script"
    assert out["labels"] == {"t": "1/2/3/0"}
    req = one_shot["request"]
    assert req["page"] == "=+CE/0" and req["readBack"] is True and req["allowReal"] is False
    assert req["ops"][0]["tag"] == "=+CE-X1:1"
    assert req["scratchRoot"]
    assert one_shot["timeout"] == 42
    # Request and marker files do not pile up.
    assert not os.listdir(ops.OPS_DIR)


def test_batch_rejects_malformed_operations(one_shot):
    assert ops.live_batch("=+CE/0", "nope")["success"] is False
    assert ops.live_batch("=+CE/0", [{"x": 1}])["success"] is False
    assert "request" not in one_shot


def test_a_failed_op_fails_the_batch_but_keeps_the_detail(one_shot):
    one_shot["canned"] = {"success": True, "project": "P", "page": "=+CE/0",
                          "ops": [{"index": 0, "op": "update", "success": False, "error": "No placement named '-K9'"}],
                          "labels": {}, "failed": 1, "allOk": False, "stoppedAt": 0}
    out = ops.live_batch("=+CE/0", [{"op": "update", "ref": "-K9", "tag": "-K1"}])
    assert out["success"] is False
    assert out["stoppedAt"] == 0
    assert "No placement" in out["ops"][0]["error"]


def test_single_op_tools_lift_their_op(one_shot):
    out = ops.live_place_terminal("=+CE/0", "SPECIAL", "X2_1", 80, 200, strip="=+CE-X1", number="1")
    assert out["success"] and out["handle"] == "1/2/3/0"
    assert out["route"].endswith("+Location")
    assert one_shot["request"]["ops"][0]["tag"] == "=+CE-X1:1"
    assert one_shot["request"]["ops"][0]["snap"] is False


def test_plc_point_sets_definition_and_designation(one_shot):
    ops.live_place_plc_point("=+CE/2", 80, 172, "DI", designation="DI a.0", tag="=+CE-A1", address="I0.0")
    op = one_shot["request"]["ops"][0]
    assert op["functionDefinition"] == {"category": "PLCTerminal", "group": 1, "id": 2}
    assert op["properties"]["FUNC_CONNECTIONDESIGNATION[1]"] == "DI a.0"
    assert op["properties"]["FUNC_PLCADDRESS"] == "I0.0"
    assert ops.live_place_plc_point("=+CE/2", 0, 0, "AI")["success"] is False


def test_panel_item_uses_macro_or_rectangle(one_shot):
    ops.live_place_panel_item("=+CE/0", "=+CE-A1", 180, 345, macro_file=r"C:\m\cpu.ema", part="SIE.6ES7")
    op = one_shot["request"]["ops"][0]
    assert op["op"] == "macro" and op["representation"] == "ArticlePlacement" and op["anchor"] == "top_left"
    ops.live_place_panel_item("=+CE/0", "=+CE-F1", 180, 575, width=54, height=90, part="SIE.5SL", mounting_plate="=+CE-M1")
    op = one_shot["request"]["ops"][0]
    assert op["op"] == "rect" and op["width"] == 54 and op["mountingPlate"] == "=+CE-M1"
    assert ops.live_place_panel_item("=+CE/0", "-F1", 0, 0)["success"] is False


def test_find_is_a_read_and_needs_no_scratch_guard(one_shot):
    one_shot["canned"] = {"success": True, "project": "P", "page": "=+CE/0",
                          "ops": [{"index": 0, "op": "find", "success": True, "matched": 1,
                                   "items": [{"handle": "1/1/1/0", "name": "=+CE-K1"}]}],
                          "labels": {}, "failed": 0, "allOk": True}
    out = ops.live_find_placements("=+CE/0", name="-K1")
    assert out["success"] and out["items"][0]["handle"] == "1/1/1/0"
    assert one_shot["request"]["write"] is False


# ---------------------------------------------------------------------------
# No registered action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda: ops.live_find_placements("=+CE/0"),
    lambda: ops.live_batch("=+CE/0", [{"op": "rect", "x": 0, "y": 0, "width": 1, "height": 1, "tag": "-Z"}]),
])
def test_reads_and_writes_run_one_shot_and_register_nothing(one_shot, call):
    out = call()
    assert out["engine"] == "script"
    assert "[Start]" in one_shot["script"]
    assert one_shot["manager"].calls == [], "no RegisterScript, no direct action"


# ---------------------------------------------------------------------------
# Overlaps
# ---------------------------------------------------------------------------

def _pl(name, x0, y0, x1, y1, t="Function"):
    return {"clrType": t, "name": name, "handle": name,
            "boundingBox": [{"x": x0, "y": y0}, {"x": x1, "y": y1}]}


def test_overlaps_report_crossing_but_not_containment():
    plate = _pl("-M1", 0, 0, 300, 500)
    a = _pl("-K1", 10, 10, 50, 60)
    b = _pl("-K2", 40, 10, 80, 60)       # crosses -K1
    c = _pl("-X1", 100, 100, 110, 150)   # alone
    line = _pl("L", 0, 0, 1000, 1000, t="PolyLine")
    found = ops._overlaps([plate, a, b, c, line])
    assert len(found) == 1
    assert found[0]["kind"] == "outline/outline"
    assert {found[0]["a"]["name"], found[0]["b"]["name"]} == {"-K1", "-K2"}
    assert found[0]["area_mm2"] == 500.0


def test_overlaps_see_texts_and_autoconnect_lines():
    rail = _pl("-DIN1", 170, 513, 410, 548)
    rail["texts"] = [[282, 520, 297, 527]]              # caption in the rail's middle
    psu = _pl("-G1", 245, 471, 343, 600)                # sits on the rail
    x1 = _pl("-X1:1", 365, 271, 370, 320, t="Terminal")
    x1["texts"] = [[360, 300, 380, 306]]
    x2 = _pl("-X1:2", 370, 271, 375, 320, t="Terminal")
    x2["texts"] = [[365, 300, 385, 306]]                # on top of -X1:1's caption
    dim = _pl("dim", 398, 400, 398.1, 450, t="DimensionItem")
    dim["texts"] = [[366, 295, 372, 310]]               # dimension text over -X1:1
    plate = _pl("-M1", 0, 0, 500, 700)
    plate_cap = _pl("-Canal1", 130, 115, 170, 650)
    plate_cap["texts"] = [[135, 300, 165, 320]]         # a duct's caption, on the plate: normal
    # A coil above a 0V rail: pins face each other, the line runs through -S9.
    coil = _pl("-K1", 76, 96, 84, 104)
    coil["pins"] = [{"direction": "Down", "point": {"x": 80, "y": 96}}]
    node = _pl("T", 79, 59, 81, 61, t="SymbolReference")
    node["pins"] = [{"direction": "Up", "point": {"x": 80, "y": 60}}]
    s9 = _pl("-S9", 75, 70, 85, 90)
    # A PLC point inside its box: its designation and its line are not collisions with the box.
    box = _pl("-A1", 60, 104, 380, 180, t="PLC")
    pt = _pl("-A1:DI a.0", 78, 170, 82, 176, t="Terminal")
    pt["texts"] = [[70, 160, 90, 168]]
    pt["pins"] = [{"direction": "Up", "point": {"x": 80, "y": 176}}]
    x1t = _pl("-X1:9", 79, 190, 81, 192, t="Terminal")
    x1t["pins"] = [{"direction": "Down", "point": {"x": 80, "y": 190}}]
    kinds = {}
    for f in ops._overlaps([rail, psu, x1, x2, dim, plate, plate_cap, coil, node, s9, box, pt, x1t]):
        kinds.setdefault(f["kind"], []).append((f["a"]["name"], f["b"]["name"]))
    assert ("-DIN1", "-G1") in kinds["text/outline"]          # rail caption over the PSU
    assert ("-X1:1", "-X1:2") in kinds["text/text"]            # terminal captions, once per pair
    assert kinds["text/text"].count(("-X1:1", "-X1:2")) == 1
    assert ("dim", "-X1:1") in kinds["text/outline"]           # dimension text over a terminal
    assert [p for p in kinds["line/outline"] if p[1] == "-S9" and p[0] in ("-K1", "T")]  # 0V line through -S9
    assert "outline/outline" in kinds                          # the rail still crosses the PSU
    flat = [pair for pairs in kinds.values() for pair in pairs]
    assert not any("-M1" in pair for pair in flat)             # the plate contains everything
    assert not any("-A1" in pair and "-A1:DI a.0" in pair for pair in flat)
    assert not any(pair == ("-A1:DI a.0", "-A1") for pair in flat)


# ---------------------------------------------------------------------------
# Target project
# ---------------------------------------------------------------------------

def test_target_project_reaches_scripts_and_actions():
    assert target.live_set_target_project(r"D:\EPLAN\Test\T.elk")["success"]
    cs = live._script("T_1", "")
    assert 'ResolveProject("D:\\\\EPLAN\\\\Test\\\\T.elk")' in cs
    assert "OpenProjects" in cs and "GetCurrentProject" in cs
    assert _base._build_action("check", TYPE="PROJECT", PROJECTNAME=None) == \
        'check /TYPE:PROJECT /PROJECTNAME:D:\\EPLAN\\Test\\T.elk'
    # An explicit project still wins.
    assert "/PROJECTNAME:X.elk" in _base._build_action("check", PROJECTNAME="X.elk")
    cleared = target.live_set_target_project("")
    assert cleared["previous"].endswith("T.elk") and cleared["target"] == ""
    assert 'ResolveProject("")' in live._script("T_2", "")
    assert "PROJECTNAME" not in _base._build_action("check", PROJECTNAME=None)


def test_target_must_be_an_elk():
    out = target.live_set_target_project(r"D:\EPLAN\Test")
    assert out["success"] is False and target.get() == ""


def test_duplicate_labels_same_wire_only():
    def lab(h, x, y, des="24V", col="BU", sec="2.5"):
        return {"clrType": "ConnectionDefinitionPoint", "handle": h, "location": {"x": x, "y": y},
                "designation": des, "wireNumber": col, "crossSection": sec}
    a = lab("1", 60, 150)
    b = lab("2", 60, 145)                       # 5 mm below a on the same wire: duplicate
    c = lab("3", 60, 125)                       # 25 mm away: the next wire's own label
    d = lab("4", 76, 150, des="GND")            # another wire, another text
    e = lab("5", 88, 194, des="24V", sec="1.5")
    f = lab("6", 88, 189, des="24V", sec="1.5") # duplicate pair on a vertical wire
    g = lab("7", 100, 189, des="24V", sec="1.5")  # same row as f, 12 mm: a neighbouring wire
    dev = {"clrType": "Terminal", "handle": "9", "name": "-X1:1", "location": {"x": 60, "y": 132}}
    found = ops._duplicate_labels([a, b, c, d, e, f, g, dev])
    pairs = {(p["a"]["handle"], p["b"]["handle"]) for p in found}
    assert pairs == {("1", "2"), ("5", "6"), ("6", "7")}
    assert {p["designation"] for p in found} == {"24V BU 2.5", "24V BU 1.5"}
    assert found[0]["gap_mm"] == 5.0
    # A label without text is nothing to compare.
    assert ops._duplicate_labels([lab("1", 0, 0, des=""), lab("2", 0, 2, des="")]) == []


def test_a_batch_blocked_by_a_dialog_keeps_the_typed_failure(one_shot, monkeypatch):
    """schematic._shape used to flatten it to a bare "error", losing next_step."""
    blocked = {"success": False, "errorType": "EplanBlockedByDialog",
               "error": "EPLAN stopped at dialog 'X'", "message": "EPLAN stopped at dialog 'X'",
               "next_step": "eplan_click_dialog_button(...)", "timed_out": True,
               "dialogs": [{"hwnd": 1, "title": "X"}]}
    monkeypatch.setattr(scripted, "_execute_script", lambda script, timeout=30.0: dict(blocked))
    out = ops.live_find_placements("=+CE/0")
    assert out["success"] is False
    assert out["errorType"] == "EplanBlockedByDialog"
    assert out["next_step"] and out["dialogs"]
