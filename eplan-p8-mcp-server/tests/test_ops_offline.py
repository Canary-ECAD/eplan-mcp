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
    """Stands in for the connection manager on the registered path."""

    def __init__(self, acknowledge=True, register_ok=True):
        self.calls = []
        self.acknowledge = acknowledge
        self.register_ok = register_ok

    def execute_action(self, action, quiet_mode=False):
        self.calls.append(action)
        if action.startswith("RegisterScript"):
            return {"success": self.register_ok}
        if action.startswith("McpOps_"):
            if self.acknowledge:
                # The action writes its ".started" marker, then the result.
                result = action.split('/result:"')[1].rstrip('"')
                open(result + ".started", "w").close()
                with open(result, "w", encoding="utf-8") as fh:
                    json.dump({"success": True, "project": "P", "page": "=+CE/0",
                               "ops": [{"index": 0, "op": "find", "success": True,
                                        "matched": 0, "items": []}],
                               "labels": {}, "failed": 0, "allOk": True}, fh)
            return {"success": True}
        return {"success": True}


@pytest.fixture
def fast_wait(monkeypatch):
    monkeypatch.setattr(ops, "STARTED_TIMEOUT_S", 0.2)


@pytest.fixture
def one_shot(monkeypatch, tmp_path):
    """Force the one-shot engine and capture the script it would run."""
    captured = {}
    monkeypatch.setenv("EPLAN_MCP_OPS_MODE", "script")
    monkeypatch.setattr(ops, "_get_connected_manager", lambda: (FakeManager(), None))
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
    cs = ops._interpreter_source("McpOps_t", "McpOps_t")
    for line in cs.splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line
    assert "?." not in cs                      # C# 5 floor
    assert "LockingStep" in cs and 'GetMethod("Dispose")' in cs
    assert "ResolveProject(" in cs and "GuardScratch(" in cs
    assert '[DeclareAction("McpOps_t")]' in cs
    assert "[Start]" in cs
    for op in ("place", "rect", "macro", "update", "move", "remove", "dimension", "line", "find", "read"):
        assert 'case "%s":' % op in cs


def test_action_name_follows_the_source():
    """A changed op must never hit a stale registration."""
    a = ops._action_name()
    assert a.startswith("McpOps_") and len(a) == len("McpOps_") + 10
    assert a == ops._action_name()


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
# Registered engine
# ---------------------------------------------------------------------------

def test_registered_path_registers_once_then_calls_the_action(monkeypatch, tmp_path, fast_wait):
    mgr = FakeManager()
    monkeypatch.delenv("EPLAN_MCP_OPS_MODE", raising=False)
    monkeypatch.setattr(ops, "_get_connected_manager", lambda: (mgr, None))
    monkeypatch.setattr(ops, "OPS_DIR", str(tmp_path / "ops"))
    monkeypatch.setattr(scripted, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(scripted, "SCRIPT_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(ops, "_registered", set())
    monkeypatch.setattr(scripted, "_execute_script", lambda *a, **k: pytest.fail("one-shot must not run"))

    out = ops.live_find_placements("=+CE/0")
    assert out["success"] and out["engine"] == "registered"
    out = ops.live_find_placements("=+CE/0")
    assert out["engine"] == "registered"
    registers = [c for c in mgr.calls if c.startswith("RegisterScript")]
    runs = [c for c in mgr.calls if c.startswith("McpOps_")]
    assert len(registers) == 1 and len(runs) == 2
    assert os.path.exists(os.path.join(ops.OPS_DIR, ops._action_name() + ".cs"))
    assert '/ops:"' in runs[0] and '/result:"' in runs[0]


def test_writes_never_use_the_registered_action(monkeypatch, tmp_path, fast_wait):
    """Inside the action every write lock fails (measured), so writes compile a one-shot."""
    mgr = FakeManager()
    monkeypatch.delenv("EPLAN_MCP_OPS_MODE", raising=False)
    monkeypatch.setattr(ops, "_get_connected_manager", lambda: (mgr, None))
    monkeypatch.setattr(ops, "OPS_DIR", str(tmp_path / "ops"))
    monkeypatch.setattr(scripted, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(scripted, "SCRIPT_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(ops, "_registered", set())
    ran = {}

    def fake_execute(script, timeout=30.0):
        ran["script"] = script
        return {"success": True, "results": {"success": True, "ops": [{"index": 0, "op": "rect", "success": True, "handle": "1/1/1/0"}],
                                             "labels": {}, "failed": 0, "allOk": True}}

    monkeypatch.setattr(scripted, "_execute_script", fake_execute)
    out = ops.live_batch("=+CE/0", [{"op": "rect", "x": 0, "y": 0, "width": 1, "height": 1, "tag": "-Z"}])
    assert out["success"] and out["engine"] == "script"
    assert mgr.calls == [] and "LockObject" in ran["script"]


def test_registered_path_falls_back_when_the_action_does_not_answer(monkeypatch, tmp_path, fast_wait):
    mgr = FakeManager(acknowledge=False)
    monkeypatch.delenv("EPLAN_MCP_OPS_MODE", raising=False)
    monkeypatch.setattr(ops, "_get_connected_manager", lambda: (mgr, None))
    monkeypatch.setattr(ops, "OPS_DIR", str(tmp_path / "ops"))
    monkeypatch.setattr(scripted, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(scripted, "SCRIPT_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(ops, "_registered", set())
    ran = {}

    def fake_execute(script, timeout=30.0):
        ran["script"] = script
        return {"success": True, "results": {"success": True, "ops": [{"index": 0, "op": "find", "success": True, "items": []}],
                                             "labels": {}, "failed": 0, "allOk": True}}

    monkeypatch.setattr(scripted, "_execute_script", fake_execute)
    out = ops.live_find_placements("=+CE/0")
    assert out["success"] and out["engine"] == "script"
    # Registered twice (stale registration re-tried once), then the one-shot ran.
    assert sum(1 for c in mgr.calls if c.startswith("RegisterScript")) == 2
    assert "[Start]" in ran["script"]
    assert ops._action_name() not in ops._registered


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
