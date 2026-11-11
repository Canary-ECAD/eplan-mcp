"""Offline tests for api/actions/graphics.py (live_scale_text).

The generated reflection C# must stay well-formed and injection-free, and the
value checks must run BEFORE a script is built - factor and min_height are
interpolated outside any string literal, so a non-number there is code.
_execute_script is stubbed, so no EPLAN is needed."""

import pytest

from api.actions import graphics


@pytest.fixture
def capture(monkeypatch):
    """Stub _execute_script; captures the generated C# instead of running it."""
    captured = {}

    def fake_execute(script, timeout=30.0):
        captured["script"] = script
        captured["timeout"] = timeout
        return {"success": True, "results": {"stubbed": True}}

    monkeypatch.setattr(graphics, "_execute_script", fake_execute)
    return captured


INJECTION = '"; System.Environment.Exit(0); string y = "'


def _string_literals_balanced(cs: str) -> bool:
    stripped = cs.replace("\\\\", "").replace('\\"', "")
    return all(line.count('"') % 2 == 0 for line in stripped.splitlines())


# ---------------------------------------------------------------------------
# The scaffold contract, same as live.py's tools
# ---------------------------------------------------------------------------

def test_no_datamodel_using_directive(capture):
    graphics.live_scale_text(factor=0.25)
    for line in capture["script"].splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line


def test_locking_step_taken_and_disposed(capture):
    graphics.live_scale_text(factor=0.25)
    cs = capture["script"]
    assert 'FindType("Eplan.EplApi.DataModel.LockingStep")' in cs
    assert 'lsType.GetMethod("Dispose")' in cs


def test_result_path_placeholder_present(capture):
    graphics.live_scale_text(factor=0.25)
    assert "{{RESULT_PATH}}" in capture["script"]


def test_no_dictionary_index_initializers(capture):
    graphics.live_scale_text(factor=0.25)
    assert '{ ["' not in capture["script"]


# ---------------------------------------------------------------------------
# factor / min_height are CODE, not data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [INJECTION, "abc", None, float("nan"), float("inf")])
def test_rejects_non_numeric_factor(capture, bad):
    result = graphics.live_scale_text(factor=bad)
    assert result["success"] is False
    assert "script" not in capture, "a malicious factor must never reach the script"


@pytest.mark.parametrize("bad", [0, -1, -0.25])
def test_rejects_non_positive_factor(capture, bad):
    result = graphics.live_scale_text(factor=bad)
    assert result["success"] is False
    assert "factor" in result["error"].lower()
    assert "script" not in capture


def test_rejects_non_positive_min_height(capture):
    result = graphics.live_scale_text(factor=0.25, min_height=0)
    assert result["success"] is False
    assert "script" not in capture


def test_numeric_string_factor_is_accepted(capture):
    # Models routinely send "0.25"; cs_double accepts it and renders a C# double.
    graphics.live_scale_text(factor="0.25")
    assert "double factor = 0.25;" in capture["script"]


# ---------------------------------------------------------------------------
# scope / page contract
# ---------------------------------------------------------------------------

def test_unknown_scope_is_refused(capture):
    result = graphics.live_scale_text(factor=0.25, scope="everything")
    assert result["success"] is False
    assert "scope" in result["error"].lower()
    assert "script" not in capture


def test_page_scope_requires_a_page(capture):
    result = graphics.live_scale_text(factor=0.25, scope="page")
    assert result["success"] is False
    assert "script" not in capture


def test_page_with_selection_scope_is_refused(capture):
    # Silently ignoring it would scale the wrong thing.
    result = graphics.live_scale_text(factor=0.25, scope="selection", page="/1")
    assert result["success"] is False
    assert "script" not in capture


def test_page_name_injection_stays_in_literal(capture):
    graphics.live_scale_text(factor=0.25, scope="page", page=INJECTION)
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert '"' + INJECTION not in cs


def test_page_name_containing_a_token_is_not_corrupted(capture):
    # _fill is one-pass with word boundaries; chained .replace() would rewrite
    # a page literally named after a placeholder.
    graphics.live_scale_text(factor=0.25, scope="page", page="FACTOR")
    assert 'FindPage(project, "FACTOR")' in capture["script"]


# ---------------------------------------------------------------------------
# Write guards
# ---------------------------------------------------------------------------

def test_dry_run_is_the_default_and_writes_nothing(capture):
    graphics.live_scale_text(factor=0.25)
    cs = capture["script"]
    assert "bool dryRun = true;" in cs
    # The scratch guard is a write guard; a dry run has nothing to guard.
    assert "GuardScratch" not in cs.split("[Start]")[1]


def test_real_run_is_scratch_guarded(capture):
    graphics.live_scale_text(factor=0.25, dry_run=False)
    cs = capture["script"]
    assert "bool dryRun = false;" in cs
    assert "GuardScratch(project, false," in cs


def test_allow_real_project_waives_the_scratch_guard(capture):
    graphics.live_scale_text(factor=0.25, dry_run=False, allow_real_project=True)
    assert "GuardScratch(project, true," in capture["script"]


def test_shared_property_placements_are_off_by_default(capture):
    graphics.live_scale_text(factor=0.25)
    assert "bool allowShared = false;" in capture["script"]


def test_from_layer_sentinel_is_skipped(capture):
    graphics.live_scale_text(factor=0.25)
    # -16002 is a flag, not a size: scaling it would write negative text height.
    assert "-16002.0" in capture["script"]


# ---------------------------------------------------------------------------
# live_set_layer
# ---------------------------------------------------------------------------

def test_layer_dry_run_is_the_default(capture):
    graphics.live_set_layer()
    cs = capture["script"]
    assert "bool dryRun = true;" in cs
    assert "GuardScratch" not in cs.split("[Start]")[1]


def test_layer_real_run_is_scratch_guarded(capture):
    graphics.live_set_layer(dry_run=False)
    assert "GuardScratch(project, false," in capture["script"]


def test_layer_default_target_is_eplan100(capture):
    graphics.live_set_layer()
    assert '"EPLAN100"' in capture["script"]


def test_layer_color_and_width_default_to_from_layer(capture):
    graphics.live_set_layer()
    cs = capture["script"]
    assert "bool doColor = true;" in cs
    assert "bool doWidth = true;" in cs
    # Line style carries meaning the layer does not, so it stays put by default.
    assert "bool doStyle = false;" in cs


def test_layer_pen_is_reassigned_not_mutated_in_place(capture):
    # Pen is a value handed out by the object: mutating it changes nothing.
    graphics.live_set_layer()
    assert "penPi.SetValue(pl, pen, null)" in capture["script"]


def test_layer_name_injection_stays_in_literal(capture):
    graphics.live_set_layer(layer=INJECTION)
    cs = capture["script"]
    assert _string_literals_balanced(cs)
    assert '"' + INJECTION not in cs


def test_layer_page_scope_requires_a_page(capture):
    result = graphics.live_set_layer(scope="page")
    assert result["success"] is False
    assert "script" not in capture


def test_layer_unknown_scope_is_refused(capture):
    result = graphics.live_set_layer(scope="project")
    assert result["success"] is False
    assert "script" not in capture


def test_layer_page_named_after_a_token_is_not_corrupted(capture):
    graphics.live_set_layer(scope="page", page="LAYERNAME")
    assert 'FindPage(project, "LAYERNAME")' in capture["script"]


def test_layer_shared_property_placements_are_off_by_default(capture):
    graphics.live_set_layer()
    assert "bool allowShared = false;" in capture["script"]


def test_layer_no_datamodel_using_directive(capture):
    graphics.live_set_layer()
    for line in capture["script"].splitlines():
        if line.strip().startswith("using "):
            assert "Eplan.EplApi.DataModel" not in line
            assert "Eplan.EplApi.HEServices" not in line
