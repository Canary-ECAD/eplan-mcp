"""Tests for reading the exception and messages off the ActionCallingContext.

Measured on EPLAN 2027.0.1, 2026-09-03, four executors x two actions:

  executor        action                              GetException()   SysMessages
  Action.Execute  projectmanagement/READPROJECTINFO   the real text    1
  Action.Execute  SetProjectLanguage/NOT_A_LANGUAGE   null             0
  CLI()           projectmanagement                   the real text    1
  CLI(true)       projectmanagement                   the real text    1
  CLI(true,true)  projectmanagement                   the real text    1

Two conclusions drive this change. The exception behind a silent
success:false is already in the context on the executor path every wrapper
already takes - so item 1's hard-exception case closes with no opt-in and no
control-flow change. And acc.SysMessages is populated on the Action.Execute
path WITHOUT CommandLineInterpreter's bCollectSysMessages flag, which is
undocumented; it is merged as a second message source rather than replacing
the bookmark slice, because it has been compared on two actions only.

Offline: the generated C# is inspected as text, and _shape_messages is driven
with hand-built results. Nothing here talks to EPLAN.
"""

import pytest

import eplan_connection
from eplan_connection import LOGGED_RESULT_KEYS, EPLANConnectionManager

shape = EPLANConnectionManager._shape_messages


def _generated_cs(action="someAction /A:1"):
    mgr = EPLANConnectionManager()
    mgr.connected = True
    captured = {}

    class _Client:
        SynchronousMode = True

        def ExecuteAction(self, act):
            path = act.split('"')[1]
            with open(path, encoding="utf-8") as f:
                captured["cs"] = f.read()
            raise RuntimeError("stop - the script text is what matters")

    mgr.client = _Client()
    mgr.execute_action(action, quiet_mode=True)
    return captured["cs"]


def _raw(*pairs):
    return [{"text": t, "level": lvl} for t, lvl in pairs]


# ---------------------------------------------------------------------------
# the generated C#
# ---------------------------------------------------------------------------

def test_the_context_exception_is_read_after_execution():
    cs = _generated_cs()
    assert "acc.GetException()" in cs
    assert 'results["errorFrom"] = "context"' in cs
    # Read after the single execution, never by re-running: success:false does
    # not mean nothing happened, so a retry could repeat a side effect.
    assert cs.index("success = eplanAction.Execute(acc)") < cs.index("acc.GetException()")


def test_it_is_read_for_the_cli_fallback_branch_too():
    """
    One read covers both branches.

    The GetException call sits after the if/else that picks an executor, so
    the fallback path gets it without a second copy - measured populated on
    the parameterless CLI as well.
    """
    cs = _generated_cs()
    assert cs.count("acc.GetException()") == 1
    assert cs.index('results["executor"] = "cli-fallback"') < cs.index("acc.GetException()")


def test_the_thrown_path_is_labelled_separately():
    """
    Provenance, because errorType was absent from all 1,463 logged actions
    before this change. When it starts appearing we need to know which channel
    produced it, or the next census cannot tell the two apart.
    """
    cs = _generated_cs()
    assert 'results["errorFrom"] = "throw"' in cs
    assert 'results["errorFrom"] = "context"' in cs


def test_the_per_call_message_collection_is_collected():
    cs = _generated_cs()
    assert "acc.SysMessages" in cs
    assert 'results["eplanContextMessagesRaw"]' in cs
    # Same safe accessor as the bookmark slice.
    assert "cm.MessageLevel.ToString()" in cs
    assert "cit.Current as BaseException" in cs


def test_the_context_read_cannot_take_the_action_down():
    """Each probe sits in its own try/catch - a diagnostics read must never
    turn a working action into a failure."""
    cs = _generated_cs()
    head = cs.index("acc.GetException()")
    tail = cs.index('var returnParams')
    region = cs[head:tail]
    assert region.count("catch {}") >= 2


# ---------------------------------------------------------------------------
# merging the two message sources
# ---------------------------------------------------------------------------

def test_context_messages_alone_still_produce_output():
    """If the bookmark slice found nothing, the context collection carries it."""
    out = shape({"success": False,
                 "eplanContextMessagesRaw": _raw(("only the context saw this", "Error"))})
    assert out["eplanMessages"] == ["only the context saw this"]
    assert out["eplanMessagesFromContextOnly"] == 1


def test_duplicates_across_the_two_sources_are_collapsed():
    """
    On both measured actions the two sources agreed exactly, so the common
    case must not double every message.
    """
    same = _raw(("No file found. (Parameter 'FILENAME')", "Error"))
    out = shape({"success": False,
                 "eplanMessagesRaw": list(same),
                 "eplanMessagesScanned": 1,
                 "eplanContextMessagesRaw": list(same)})
    assert out["eplanMessages"] == ["No file found. (Parameter 'FILENAME')"]
    assert "eplanMessagesFromContextOnly" not in out
    assert out["eplanMessagesTotal"] == 1


def test_the_bookmark_slice_keeps_its_chronology():
    """Bookmark entries first, so the order EPLAN produced them survives."""
    out = shape({"success": False,
                 "eplanMessagesRaw": _raw(("first", "Message"), ("second", "Message")),
                 "eplanMessagesScanned": 2,
                 "eplanContextMessagesRaw": _raw(("third", "Message"))})
    assert out["eplanMessages"] == ["first", "second", "third"]
    assert out["eplanMessagesFromContextOnly"] == 1


def test_context_only_additions_are_counted_into_the_total():
    """
    Count belongs to the bookmark collection and knows nothing about the
    context one, so anything only the context supplied has to be added or the
    total under-reports what we are holding.
    """
    out = shape({"success": False,
                 "eplanMessagesRaw": _raw(("a", "Message")),
                 "eplanMessagesTrueTotal": 1,
                 "eplanContextMessagesRaw": _raw(("b", "Message"), ("c", "Message"))})
    assert out["eplanMessagesTotal"] == 3
    assert out["eplanMessagesFromContextOnly"] == 2


def test_severity_ranking_applies_across_both_sources():
    out = shape({"success": False,
                 "eplanMessagesRaw": _raw(("chatter", "Message")),
                 "eplanMessagesScanned": 1,
                 "eplanContextMessagesRaw": _raw(("the real error", "Error"))})
    assert out["eplanMessages"][0] == "the real error"


def test_the_raw_context_field_is_consumed_not_leaked():
    out = shape({"success": False,
                 "eplanContextMessagesRaw": _raw(("x", "Error"))})
    assert "eplanContextMessagesRaw" not in out


def test_a_result_with_neither_source_is_untouched():
    original = {"success": True, "executor": "action", "parameters": {"A": "1"}}
    assert shape(dict(original)) == original


@pytest.mark.parametrize("bad", [None, "nope", 7, {}])
def test_a_malformed_context_field_never_raises(bad):
    out = shape({"success": False, "eplanContextMessagesRaw": bad,
                 "eplanMessagesRaw": _raw(("still here", "Error")),
                 "eplanMessagesScanned": 1})
    assert out["eplanMessages"] == ["still here"]


def test_context_only_field_is_absent_on_the_healthy_path():
    """Every new field has to cost nothing when it has nothing to say."""
    out = shape({"success": False, "eplanMessagesRaw": _raw(("x", "Message")),
                 "eplanMessagesScanned": 1})
    assert "eplanMessagesFromContextOnly" not in out


# ---------------------------------------------------------------------------
# the trace
# ---------------------------------------------------------------------------

def test_the_new_fields_reach_the_trace():
    for field in ("errorFrom", "eplanMessagesFromContextOnly"):
        assert field in LOGGED_RESULT_KEYS, (
            "%s must be in LOGGED_RESULT_KEYS or it never reaches "
            "actions.jsonl, and the next census cannot measure whether the "
            "context channel is pulling its weight." % field
        )


# ---------------------------------------------------------------------------
# the leak that only live testing found
# ---------------------------------------------------------------------------

def test_internal_hints_do_not_leak_when_there_are_no_messages():
    """
    The regression that offline tests missed and live EPLAN caught.

    The C# emits eplanMessagesBounded and eplanMessagesTrueTotal whenever it
    managed to take a bookmark - which is on every action, including the many
    that produce no messages at all. The early return for "nothing to shape"
    originally ran before those were drained, so two internal fields leaked
    into the response of most actions. Every offline test happened to supply
    messages, so none of them exercised the path.

    Measured shape of the leak, from SetProjectLanguage /DISPLAY:NOT_A_LANGUAGE
    against EPLAN 2027.0.1:
        {"executor": "action", "success": false, "parameters": {...},
         "eplanMessagesBounded": true, "eplanMessagesTrueTotal": 0}
    """
    out = shape({
        "executor": "action",
        "success": False,
        "parameters": {"DISPLAY": "NOT_A_LANGUAGE"},
        "eplanMessagesBounded": True,
        "eplanMessagesTrueTotal": 0,
    })
    assert out == {
        "executor": "action",
        "success": False,
        "parameters": {"DISPLAY": "NOT_A_LANGUAGE"},
    }, "internal hint fields must never survive into the response"


@pytest.mark.parametrize("hint", [
    "eplanMessagesRaw", "eplanContextMessagesRaw", "eplanMessagesScanned",
    "eplanMessagesTrueTotal", "eplanMessagesBounded",
])
def test_each_internal_hint_is_drained_even_alone(hint):
    """No single hint may survive on its own, whatever the C# emitted."""
    out = shape({"success": True, hint: 0 if "Total" in hint or "Scanned" in hint else []})
    assert hint not in out


def test_the_live_success_payload_round_trips_to_the_documented_shape():
    """
    The exact payload the real template produced against EPLAN 2027.0.1 for
    projectmanagement /TYPE:READPROJECTINFO with PROJECTNAME omitted, shaped.

    Pins the end-to-end contract: the error text and its provenance survive,
    the two message sources collapse to one because they agreed, the level
    list appears because Error outranks Message, and every internal field is
    gone. Nothing else is added.
    """
    live = {
        "executor": "action",
        "success": False,
        "error": "No file found. (Parameter 'FILENAME')",
        "errorType": "Eplan.EplApi.Base.BaseException",
        "errorFrom": "context",
        "eplanContextMessagesRaw": [
            {"text": "No file found. (Parameter 'FILENAME')", "level": "Error"}],
        "parameters": {"TYPE": "READPROJECTINFO"},
        "eplanMessagesBounded": True,
        "eplanMessagesTrueTotal": 1,
        "eplanMessagesRaw": [
            {"text": "No file found. (Parameter 'FILENAME')", "level": "Error"}],
        "eplanMessagesScanned": 1,
    }
    assert shape(live) == {
        "executor": "action",
        "success": False,
        "error": "No file found. (Parameter 'FILENAME')",
        "errorType": "Eplan.EplApi.Base.BaseException",
        "errorFrom": "context",
        "parameters": {"TYPE": "READPROJECTINFO"},
        "eplanMessages": ["No file found. (Parameter 'FILENAME')"],
        "eplanMessagesTotal": 1,
        "eplanMessagesLevels": ["Error"],
    }
