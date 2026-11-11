"""Offline tests for api/actions/live.py: the generated reflection C# must stay
well-formed, injection-free, and free of the traps that make it fail inside
EPLAN's script engine. _execute_script is replaced by a capture stub, so no
EPLAN is needed."""

import pytest

from api.actions import live


@pytest.fixture
def capture(monkeypatch):
    """Stub _execute_script; captures the generated C# instead of running it."""
    captured = {}

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        captured["timeout"] = timeout
        return {"success": True, "results": {"stubbed": True}}

    monkeypatch.setattr(live, "_execute_script", fake_execute)
    return captured


INJECTION = '"; System.Environment.Exit(0); string y = "'


def _string_literals_balanced(cs: str) -> bool:
    """After stripping escape sequences, every line must contain an even
    number of quotes - i.e. no value broke out of its string literal."""
    stripped = cs.replace("\\\\", "").replace('\\"', "")
    return all(line.count('"') % 2 == 0 for line in stripped.splitlines())


ALL_TOOLS = [
    (live.live_query_functions, {}),
    (live.live_query_pages, {}),
    (live.live_plc_io_list, {}),
    (live.live_set_function_text, {"name": "+X-K1", "text": "hi"}),
    (live.live_set_connection_designations,
     {"name": "+X-K1", "designations": ["Y11", "Y12"]}),
    (live.live_read_check_messages, {}),
]



# ---------------------------------------------------------------------------
# The CS0234 trap: DataModel/HEServices must never appear as `using` directives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_no_datamodel_using_directive(capture, fn, kwargs):
    fn(**kwargs)
    for line in capture["script"].splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line


# ---------------------------------------------------------------------------
# Assembly resolution: never Assembly.Load the native twin as the primary route
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_resolves_types_from_loaded_assemblies(capture, fn, kwargs):
    fn(**kwargs)
    cs = capture["script"]
    # Scanning the loaded set is the primary route.
    assert "AppDomain.CurrentDomain.GetAssemblies()" in cs
    # In the Assembly.Load FALLBACK list, the *Netu names must come first: on
    # 2027 the un-suffixed name is the mixed-mode native twin and loading it
    # throws BadImageFormatException. Scope the check to the candidates array,
    # since the surrounding comment mentions the un-suffixed name too.
    start = cs.index("string[] candidates")
    candidates = cs[start:cs.index("};", start)]
    assert candidates.index('"Eplan.EplApi.DataModelNetu"') < candidates.index('"Eplan.EplApi.DataModelu"')
    assert candidates.index('"Eplan.EplApi.HEServicesNetu"') < candidates.index('"Eplan.EplApi.HEServicesu"')


@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_locking_step_taken_and_disposed(capture, fn, kwargs):
    fn(**kwargs)
    cs = capture["script"]
    assert 'FindType("Eplan.EplApi.DataModel.LockingStep")' in cs
    assert "finally" in cs
    assert 'lsType.GetMethod("Dispose")' in cs


# ---------------------------------------------------------------------------
# Script-engine syntax limits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_no_dictionary_index_initializers(capture, fn, kwargs):
    # `new Dictionary<..> { ["k"] = v }` is CS1525 in EPLAN's script engine.
    fn(**kwargs)
    assert '{ ["' not in capture["script"]
    assert "{[" not in capture["script"].replace(" ", "")


@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_result_path_placeholder_present(capture, fn, kwargs):
    fn(**kwargs)
    assert "{{RESULT_PATH}}" in capture["script"]


# ---------------------------------------------------------------------------
# limit is interpolated outside a string literal -> must be a real integer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_rejects_non_integer_limit(capture, fn, kwargs):
    result = fn(limit=INJECTION, **kwargs)
    assert result["success"] is False
    assert "limit" in result["error"].lower()
    assert "script" not in capture, "malicious limit must never reach the script"


def test_query_coerces_numeric_string_limit(capture):
    result = live.live_query_pages(limit="25")
    assert result["success"] is True
    assert "list.Count < 25" in capture["script"]


def test_query_default_limit_in_script(capture):
    live.live_query_functions()
    assert "list.Count < 100" in capture["script"]


def test_set_function_text_default_limit_is_one(capture):
    # A mistaken name must not mass-edit the project.
    live.live_set_function_text(name="+X-K1", text="hi")
    assert "details.Count >= 1" in capture["script"]


# ---------------------------------------------------------------------------
# String parameters must stay inside their literals
# ---------------------------------------------------------------------------

def test_contains_injection_stays_in_literal(capture):
    live.live_query_functions(contains=INJECTION)
    cs = capture["script"]
    # The payload survives as DATA inside the literal - that is correct. What
    # matters is that its quotes were escaped so it cannot close the literal and
    # become code: no bare `"` remains around the injected text.
    assert '\\"' in cs
    assert _string_literals_balanced(cs)
    # Every quote in the payload is escaped, so the only occurrences of a bare
    # quote are the literal's own delimiters.
    assert '"' + INJECTION not in cs


def test_name_and_text_injection_stay_in_literal(capture):
    live.live_set_function_text(name=INJECTION, text=INJECTION)
    cs = capture["script"]
    assert _string_literals_balanced(cs)


def test_backslash_path_is_escaped(capture):
    live.live_set_function_text(name=r"+X-K1", text=r"C:\Temp\A1")
    cs = capture["script"]
    # A raw C:\Temp\A1 would be CS1009 (unrecognized escape \T, \A).
    assert r"C:\\Temp\\A1" in cs
    assert _string_literals_balanced(cs)


def test_unicode_line_terminator_stays_in_literal(capture):
    ls = chr(0x2028)
    live.live_query_pages(contains=f"a{ls}b")
    assert ls not in capture["script"]


# ---------------------------------------------------------------------------
# Contract details
# ---------------------------------------------------------------------------

def test_set_function_text_requires_name(capture):
    result = live.live_set_function_text(name="", text="hi")
    assert result["success"] is False
    assert "script" not in capture


@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_timeout_is_forwarded(capture, fn, kwargs):
    fn(timeout_seconds=123.0, **kwargs)
    assert capture["timeout"] == 123.0


@pytest.mark.parametrize("fn,kwargs", ALL_TOOLS)
def test_class_names_are_unique_per_call(capture, fn, kwargs):
    fn(**kwargs)
    first = capture["script"]
    fn(**kwargs)
    second = capture["script"]
    # Same script twice would collide in EPLAN's script engine cache.
    assert first != second


def test_ambiguous_match_guard_present(capture):
    # Function.Properties and FUNC_TEXT[int] both make a plain GetProperty throw
    # AmbiguousMatchException; the generated code must use the guarded lookup.
    live.live_set_function_text(name="+X-K1", text="hi")
    cs = capture["script"]
    assert "DeclaredOnly" in cs
    assert "Type.EmptyTypes" in cs
    assert 'GetPropInfo(props.GetType(), "FUNC_TEXT")' in cs


# ---------------------------------------------------------------------------
# discovery.list_layers reaches the DataModel through the same reflection
# scaffold. Emitting `using Eplan.EplApi.DataModel;` is CS0234, which means the
# script never compiles, never writes its result file, and the tool can only
# ever time out - so guard the using-directive absence here too.
# ---------------------------------------------------------------------------

def test_list_layers_uses_reflection_not_using_directive(monkeypatch):
    from api.actions import discovery

    captured = {}

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        captured["timeout"] = timeout
        return {"success": True, "results": {"stubbed": True}}

    monkeypatch.setattr(discovery, "_execute_script", fake_execute)
    discovery.list_layers()

    cs = captured["script"]
    for line in cs.splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line
    # goes through the shared reflection scaffold
    assert "AppDomain.CurrentDomain.GetAssemblies()" in cs
    assert 'FindType("Eplan.EplApi.DataModel.LockingStep")' in cs
    assert 'GetPropInfo(project.GetType(), "LayerTable")' in cs
    # a 457-layer table needs more headroom than the 30s default
    assert captured["timeout"] > 30.0


# ---------------------------------------------------------------------------
# live_set_connection_designations - connection point numbers (property 20022)
# ---------------------------------------------------------------------------

def test_conn_designations_writes_each_index_in_order(capture):
    live.live_set_connection_designations("+-TEST", ["Y11", "Y12"])
    cs = capture["script"]
    # one designation per index, in the order given
    assert 'string[] wanted = new string[] { "Y11", "Y12" };' in cs
    # and they are written by slot, not as one joined blob
    assert "int slot = i + 1;" in cs


def test_conn_designations_uses_indexed_property_lookup(capture):
    # FUNC_CONNECTIONDESIGNATION is declared both plain and [int]; the indexed
    # form is the one that addresses a single connection point. Using the
    # non-indexed lookup here would fetch the wrong declaration.
    live.live_set_connection_designations("+-TEST", ["Y11"])
    cs = capture["script"]
    assert 'GetPropInfoIdx(props.GetType(), "FUNC_CONNECTIONDESIGNATION")' in cs
    assert "new Type[] { typeof(int) }" in cs


def test_conn_designations_reads_back_each_slot(capture):
    # The reported value must come from a fresh fetch, not the local wrapper.
    live.live_set_connection_designations("+-TEST", ["Y11", "Y12"])
    cs = capture["script"]
    assert cs.count("cdIdx.GetValue(props, new object[] { slot })") >= 2


def test_conn_designations_rejects_joined_string(capture):
    # "Y11¶Y12" as one value would land entirely in index 1.
    result = live.live_set_connection_designations("+-TEST", "Y11" + live.PILCROW + "Y12")
    assert result["success"] is False
    assert "list of strings" in result["error"]
    assert "script" not in capture


def test_conn_designations_rejects_pilcrow_inside_an_element(capture):
    result = live.live_set_connection_designations("+-TEST", ["Y11" + live.PILCROW + "Y12"])
    assert result["success"] is False
    assert "pilcrow" in result["error"]
    assert "script" not in capture


@pytest.mark.parametrize("bad", [[], None, 42, {}])
def test_conn_designations_rejects_bad_container(capture, bad):
    result = live.live_set_connection_designations("+-TEST", bad)
    assert result["success"] is False
    assert "script" not in capture


def test_conn_designations_rejects_none_element(capture):
    result = live.live_set_connection_designations("+-TEST", ["Y11", None])
    assert result["success"] is False
    assert "None" in result["error"]
    assert "script" not in capture


def test_conn_designations_requires_name(capture):
    result = live.live_set_connection_designations("", ["Y11"])
    assert result["success"] is False
    assert "script" not in capture


def test_conn_designations_default_limit_is_one(capture):
    live.live_set_connection_designations("+-TEST", ["Y11"])
    assert "details.Count >= 1" in capture["script"]


def test_conn_designations_coerces_non_string_elements(capture):
    live.live_set_connection_designations("+-TEST", [11, 12])
    assert 'new string[] { "11", "12" };' in capture["script"]


def test_conn_designations_escapes_injection(capture):
    live.live_set_connection_designations("+-TEST", [INJECTION, "Y12"])
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert '"' + INJECTION not in cs


# ---------------------------------------------------------------------------
# live_read_check_messages - PrjMessagesCollection (Eplan.EplApi.EServices),
# the itemized store behind the "Message management" dialog. Reached the same
# way DataModel/HEServices are: never `using`, always FindType + reflection.
# ---------------------------------------------------------------------------

def test_read_check_messages_no_eservices_using_directive(capture):
    # EServices is a third namespace in the same CS0234 family as
    # DataModel/HEServices - must never appear as a `using` directive either.
    live.live_read_check_messages()
    for line in capture["script"].splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.EServices" not in line


def test_read_check_messages_resolves_collection_by_reflection(capture):
    live.live_read_check_messages()
    cs = capture["script"]
    assert 'FindType("Eplan.EplApi.EServices.PrjMessagesCollection")' in cs
    assert 'collType.GetMethod("GetPrjMsgEnumerator")' in cs
    assert 'itType.GetProperty("CurrentProjectMessage")' in cs


def test_read_check_messages_default_window(capture):
    live.live_read_check_messages()
    cs = capture["script"]
    assert "int startIdx = 1;" in cs
    assert "int endIdx = 50;" in cs


def test_read_check_messages_start_index_and_limit_set_the_window(capture):
    live.live_read_check_messages(start_index=1940, limit=1)
    cs = capture["script"]
    assert "int startIdx = 1940;" in cs
    assert "int endIdx = 1940;" in cs


def test_read_check_messages_limit_is_capped_at_500(capture):
    live.live_read_check_messages(start_index=1, limit=999999)
    cs = capture["script"]
    assert "int endIdx = 500;" in cs


def test_read_check_messages_rejects_start_index_below_one(capture):
    result = live.live_read_check_messages(start_index=0)
    assert result["success"] is False
    assert "script" not in capture


def test_read_check_messages_contains_stays_in_literal(capture):
    live.live_read_check_messages(contains=INJECTION)
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert '"' + INJECTION not in cs


def test_read_check_messages_default_contains_is_empty_string(capture):
    # Matches() treats an empty filter as "match everything" - confirm that is
    # what an omitted `contains` actually compiles to, not the string "None".
    live.live_read_check_messages()
    assert 'string filterText = "";' in capture["script"]


# ---------------------------------------------------------------------------
# live_plc_io_list: the Python-side shaping must not need EPLAN
# ---------------------------------------------------------------------------

def test_split_identifier_iec_parts():
    assert live._split_identifier("=ST1+CE-A1:DI a.0") == {
        "installation": "=ST1", "location": "+CE", "device": "-A1",
        "connectionPoint": "DI a.0"}
    assert live._split_identifier("=+CE-A2:0+")["installation"] == "="
    assert live._split_identifier("-X1:12") == {
        "installation": "", "location": "", "device": "-X1", "connectionPoint": "12"}


def test_split_multilingual_and_neutral_text():
    assert live._split_multilingual("es_ES@Marcha;en_US@Start;") == {"es_ES": "Marcha", "en_US": "Start"}
    assert live._split_multilingual("??_??@Presion;") == {"*": "Presion"}
    assert live._split_multilingual("") == {}


@pytest.mark.parametrize("address,dtype,cp,kind", [
    ("I0.0", "BOOL", "DI a.0", "DI"),
    ("Q0.1", "BOOL", "DQ a.1", "DO"),
    ("IW96", "WORD", "0+", "AI"),
    ("QW80", "INT", "0+", "AO"),
    ("", "", "L+", "supply"),
    ("", "", "DI a.7", "other"),
])
def test_plc_kind(address, dtype, cp, kind):
    assert live._plc_kind(address, dtype, cp) == kind


def test_shape_plc_io_groups_by_installation_and_picks_manual_over_automatic():
    raw = {
        "success": True, "matched": 2,
        "rawPoints": [
            {"name": "=ST1+CE-A1:DI a.0", "FUNC_FULLDEVICETAG": "=ST1+CE-A1",
             "FUNC_CONNECTIONDESIGNATION1": "DI a.0", "FUNC_PLCADDRESS": "I0.0",
             "FUNC_PLCDATATYPE": "BOOL", "FUNC_TEXT": "es_ES@Marcha;en_US@Start;",
             "FUNC_PLCSYMBOLICADDRESS_MANUAL": "ST1_Start",
             "FUNC_PLCSYMBOLICADDRESS_AUTOMATIC": "auto", "page": "=ST1+CE/2"},
            {"name": "=ST2+CE-A1:DI a.0", "FUNC_FULLDEVICETAG": "=ST2+CE-A1",
             "FUNC_CONNECTIONDESIGNATION1": "DI a.0", "FUNC_PLCADDRESS": "I1.0",
             "FUNC_PLCDATATYPE": "BOOL", "FUNC_TEXT": "", "page": ""},
        ],
        "rawBoxes": [
            {"name": "=ST1+CE-A1", "FUNC_FULLDEVICETAG": "=ST1+CE-A1", "FUNC_PLCCPU": "1",
             "FUNC_PLCRACK": "0", "FUNC_PLC_SUBSLOT": "1", "parts": ["SIE.X"],
             "FUNC_TEXT": "en_US@CPU;", "page": "=ST1+CE/2"},
        ],
    }
    out = live._shape_plc_io(raw)
    assert out["success"] and out["returned"] == 2 and out["matched"] == 2
    assert out["byInstallation"] == {"=ST1": 1, "=ST2": 1}
    p0 = out["points"][0]
    assert p0["installation"] == "=ST1" and p0["device"] == "-A1" and p0["kind"] == "DI"
    assert p0["symbolicAddress"] == "ST1_Start"
    assert p0["functionText"] == {"es_ES": "Marcha", "en_US": "Start"}
    m0 = out["modules"][0]
    assert m0["isCpu"] is True and m0["rack"] == "0" and m0["slot"] == "1" and m0["parts"] == ["SIE.X"]


def test_plc_io_list_filters_are_interpolated_safely(capture):
    live.live_plc_io_list(contains=INJECTION, include_unaddressed=True, limit="25")
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert "!true) continue;" in cs
    assert "points.Count >= 25" in cs


def test_plc_io_list_returns_raw_result_when_script_failed(monkeypatch):
    monkeypatch.setattr(live, "_execute_script", lambda s, timeout=0: {"success": False, "error": "boom"})
    out = live.live_plc_io_list()
    assert out == {"success": False, "error": "boom"}


# ---------------------------------------------------------------------------
# reports_live: generated C# shape and the S029153 hint
# ---------------------------------------------------------------------------

def test_create_report_script_shape(monkeypatch):
    from api.actions import reports_live
    captured = {}
    monkeypatch.setattr(reports_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True, "results": {"success": True}})
    reports_live.live_create_report("TerminalDiagram", form_name="F13_001")
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project, false" in cs
    assert '"TerminalDiagram"' in cs and '"F13_001"' in cs
    assert '{ block, "/1" }' in cs, "empty first-page name is refused by EPLAN (S029035)"
    assert "GenerateProject" in cs
    for line in cs.splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line and "Eplan.EplApi.HEServices" not in line


def test_create_report_without_generate_and_injection(monkeypatch):
    from api.actions import reports_live
    captured = {}
    monkeypatch.setattr(reports_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True, "results": {}})
    reports_live.live_create_report(INJECTION, form_name=INJECTION, page_name=INJECTION, generate=False)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "if (false)" in cs


def test_create_report_adds_hint_on_missing_form(monkeypatch):
    from api.actions import reports_live
    monkeypatch.setattr(reports_live, "_execute_script",
                        lambda s, timeout=0: {"success": False, "error": "Exception: S029153 El formulario no se ha encontrado"})
    out = reports_live.live_create_report("PartsList", form_name="F03_001")
    assert "F03_001" in out["hint"] and "Sincronizar" in out["hint"]


def test_report_types_script_is_read_only(monkeypatch):
    from api.actions import reports_live
    captured = {}
    monkeypatch.setattr(reports_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True})
    reports_live.live_report_types()
    assert "GuardScratch(project," not in captured["script"], "read-only tool must not run the write guard"
    assert "PAGE_FORMULAR" in captured["script"]


# ---------------------------------------------------------------------------
# structure_live: copy pages to another installation designation
# ---------------------------------------------------------------------------

def test_copy_pages_script_shape(monkeypatch):
    from api.actions import structure_live
    captured = {}
    monkeypatch.setattr(structure_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True})
    structure_live.live_copy_pages_to_structure(["+CE/2"], ["=ST2", "ST3"], keep_devices=["-A1"], location="+CE")
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project, false" in cs
    assert 'new string[] { "ST2", "ST3" }' in cs, "leading = must be stripped"
    assert 'string locOverride = "CE";' in cs, "leading + must be stripped"
    assert 'new string[] { "-A1" }' in cs
    assert 'Enum.Parse(nmT, "Ignore")' in cs
    assert 'GetWritable(pl.GetType(), "VisibleName")' in cs


def test_copy_pages_rejects_bad_lists():
    from api.actions import structure_live
    assert structure_live.live_copy_pages_to_structure([], ["ST2"])["success"] is False
    assert structure_live.live_copy_pages_to_structure(["+CE/2"], [])["success"] is False
    assert structure_live.live_copy_pages_to_structure("+CE/2", ["ST2"])["success"] is False


def test_copy_pages_injection_stays_in_literal(monkeypatch):
    from api.actions import structure_live
    captured = {}
    monkeypatch.setattr(structure_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True})
    structure_live.live_copy_pages_to_structure([INJECTION], [INJECTION], keep_devices=[INJECTION], location=INJECTION)
    assert _string_literals_balanced(captured["script"])


# ---------------------------------------------------------------------------
# panel_live: captions read / edit
# ---------------------------------------------------------------------------

def _capture_panel(monkeypatch):
    from api.actions import panel_live
    captured = {}
    monkeypatch.setattr(panel_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True})
    return panel_live, captured


def test_panel_captions_read_is_guard_free(monkeypatch):
    panel_live, captured = _capture_panel(monkeypatch)
    panel_live.live_panel_captions("+CE/0", ref=INJECTION)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project," not in cs
    assert "PropertyPlacements" in cs and "GetBoundingBox" in cs


def test_set_panel_captions_script_shape(monkeypatch):
    panel_live, captured = _capture_panel(monkeypatch)
    panel_live.live_set_panel_captions("+CE/0", "124/17/1409/0", hide=[20100, "PTIO-IN"], show=["20450"],
                                       positions={"20010": [386, 223]}, legend_position=9)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project, false" in cs
    assert '"UseLocalPropertyPlacements"' in cs, "edits must switch to the local arrangement first"
    assert 'new string[] { "20100", "PTIO-IN" }' in cs
    assert 'new string[] { "20450" }' in cs
    assert 'new string[] { "20010", "386.0", "223.0" }' in cs
    assert "op_Implicit" in cs and "new object[] { 9 }" in cs
    assert '"IsDocked"' in cs


def test_set_panel_captions_rejects_bad_positions():
    from api.actions import panel_live
    assert panel_live.live_set_panel_captions("+CE/0", "-X1", positions=[1, 2])["success"] is False
    assert panel_live.live_set_panel_captions("+CE/0", "-X1", positions={"20010": [1]})["success"] is False
    assert panel_live.live_set_panel_captions("+CE/0", "-X1", legend_position="x")["success"] is False


def test_set_panel_captions_without_legend_skips_indexer(monkeypatch):
    panel_live, captured = _capture_panel(monkeypatch)
    panel_live.live_set_panel_captions("+CE/0", "-X1", hide=[INJECTION], positions={INJECTION: [0, 0]})
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "if (false)" in cs


# ---------------------------------------------------------------------------
# terminals_live / cables_live / project_live
# ---------------------------------------------------------------------------

def _capture(monkeypatch, module):
    captured = {}
    monkeypatch.setattr(module, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True})
    return captured


def test_terminal_strips_read_is_guard_free(monkeypatch):
    from api.actions import terminals_live
    captured = _capture(monkeypatch, terminals_live)
    terminals_live.live_terminal_strips(contains=INJECTION)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project," not in cs
    assert '"TerminalStrip"' in cs and '== "Terminal"' in cs, "PLC points must be filtered by category"


def test_set_terminal_strip_definition_script_shape(monkeypatch):
    from api.actions import terminals_live
    captured = _capture(monkeypatch, terminals_live)
    terminals_live.live_set_terminal_strip_definition("-X1", text=INJECTION, part="PXC.1", properties={"FUNC_SUPPLEMENTARYFIELD1": INJECTION})
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project, false" in cs
    assert '"TerminalDefText", (short)1, (short)1' in cs
    assert 'RequireMethod(tsT, "Create", new string[] { "Project", "FunctionDefinition" }' in cs
    assert "propsIn[\"FUNC_SUPPLEMENTARYFIELD1\"]" in cs


def test_set_terminal_strip_definition_placed_uses_create_page(monkeypatch):
    from api.actions import terminals_live
    captured = _capture(monkeypatch, terminals_live)
    terminals_live.live_set_terminal_strip_definition("-X1", page="+CE/2", x=300, y=200)
    cs = captured["script"]
    assert 'RequireMethod(tsT, "Create", new string[] { "Page" }' in cs
    assert "300.0, 200.0" in cs
    assert terminals_live.live_set_terminal_strip_definition("-X1", page="+CE/2")["success"] is False


def test_cables_read_is_guard_free(monkeypatch):
    from api.actions import cables_live
    captured = _capture(monkeypatch, cables_live)
    cables_live.live_cables(contains=INJECTION)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project," not in cs
    assert '"CableConnections"' in cs and '"CONNECTION_DESIGNATION"' in cs


def test_place_cable_definition_script_shape(monkeypatch):
    from api.actions import cables_live
    captured = _capture(monkeypatch, cables_live)
    cables_live.live_place_cable_definition("+CE/2", "-W1", 70, 112, 220, 112, text=INJECTION, generate=False)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project, false" in cs
    assert 'MakeVariantT(project, "SPECIAL", "CABDL", 0)' in cs
    assert "MakePoint(pt, 70.0, 112.0), MakePoint(pt, 220.0, 112.0)" in cs
    assert '"DESIGNATION_LOCATION"' in cs, "a bare -W1 must take the page structure"
    assert cables_live.live_place_cable_definition("+CE/2", "-W1", "a", 1, 2, 3)["success"] is False


def test_assign_cable_connections_script_shape(monkeypatch):
    from api.actions import cables_live
    captured = _capture(monkeypatch, cables_live)
    cables_live.live_assign_cable_connections("+CE/2", INJECTION, generate=False)
    cs = captured["script"]
    assert _string_literals_balanced(cs)
    assert "GuardScratch(project, false" in cs
    assert '"CableNameParts"' in cs and '"CableDefinitionLine"' in cs
    assert '"StartSymbolConnPoint"' in cs, "pin offsets are added to the device location"


def test_create_project_refuses_outside_scratch(tmp_path, monkeypatch):
    from api.actions import project_live
    tpl = tmp_path / "t.zw9"
    tpl.write_text("x")
    r = project_live.live_create_project(r"C:\Projects\Real.elk", str(tpl))
    assert r["success"] is False and "scratch" in r["error"]
    r = project_live.live_create_project(str(tmp_path / "p.elk"), str(tmp_path / "missing.zw9"))
    assert r["success"] is False and "Template not found" in r["error"]


def test_create_project_clears_target_for_the_call(tmp_path, monkeypatch):
    from api.actions import project_live, target
    monkeypatch.setattr(project_live, "SCRATCH_ROOT", str(tmp_path))
    tpl = tmp_path / "t.zw9"
    tpl.write_text("x")
    seen = {}

    def fake(script, timeout=0):
        seen["target_during"] = target.get()
        seen["script"] = script
        return {"success": True, "results": {"success": True, "project": "P"}}
    monkeypatch.setattr(project_live, "_execute_script", fake)
    target.set_target(r"D:\old.elk")
    r = project_live.live_create_project(str(tmp_path / "new" / "P.elk"), str(tpl))
    assert seen["target_during"] == ""
    assert "CreateProject" in seen["script"] and _string_literals_balanced(seen["script"])
    assert target.get().lower().endswith("p.elk")
    target.set_target("")


def test_project_templates_lists_zw9(tmp_path):
    from api.actions import project_live
    (tmp_path / "a.zw9").write_text("x")
    (tmp_path / "b.ept").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    r = project_live.live_project_templates(str(tmp_path))
    assert r["success"] and r["count"] == 2
    assert {t["kind"] for t in r["templates"]} == {"basic project", "template"}


def test_assign_cable_connections_reassign_runs_after_conductors_exist(monkeypatch):
    from api.actions import cables_live, generate
    scripts = []

    def fake_exec(script, timeout=0):
        scripts.append(script)
        return {"success": True, "results": {"success": True, "handle": "h", "cable": "=+CE-W1",
                                             "crossed": [{"designation": "201", "assigned": "now"}],
                                             "reassignedFromPart": "if (true)" in script}}
    monkeypatch.setattr(cables_live, "_execute_script", fake_exec)
    monkeypatch.setattr(generate, "generate_connections", lambda **kw: {"success": True})
    monkeypatch.setattr(cables_live, "live_cables",
                        lambda **kw: {"results": {"cables": [{"handle": "h", "conductors": [{"designation": "201"}]}]}})
    r = cables_live.live_assign_cable_connections("+CE/2", "-W1", generate=True)
    assert len(scripts) == 1 and "if (false)" in scripts[0]
    scripts.clear()
    r = cables_live.live_assign_cable_connections("+CE/2", "-W1", generate=True, reassign_from_part=True)
    assert len(scripts) == 2 and "if (false)" in scripts[0] and "if (true)" in scripts[1]
    assert "DoReassignWires" in scripts[1] and _string_literals_balanced(scripts[1])
    assert r["results"]["reassignedFromPart"] is True and r["results"]["connectionsGenerated"] == 2


def test_copy_pages_keeps_subcounter(monkeypatch):
    from api.actions import structure_live
    captured = {}
    monkeypatch.setattr(structure_live, "_execute_script",
                        lambda s, timeout=0: captured.setdefault("script", s) and {"success": True})
    structure_live.live_copy_pages_to_structure(["+CE/2.a"], ["ST2"])
    cs = captured["script"]
    assert '"PAGE_SUBCOUNTER"' in cs and 'SetProp(ppl, "PAGE_SUBCOUNTER", sub)' in cs
