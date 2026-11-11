"""The action-result contract and shaping EPLAN's messages into it."""


# Severity ranking for the message slice, most important first.
#
# Deliberately a hand-written list rather than MessageLevel's numeric order,
# which is NOT a severity order: Trace=0, Message=1, Warning=2, Assert=3,
# Error=4, FatalError=5, so a naive sort puts Assert - documented as "the
# lowest level of an error, which will not appear in GUI" - above Warning.
#
# Trace and Assert are omitted entirely: the SysMessagesCollection docs state
# neither is ever added to the collection, so listing them would imply a
# guarantee that does not exist. Anything unranked sorts last.
MESSAGE_LEVEL_RANK = ("FatalError", "Error", "Warning", "Message")

# Entries kept in eplanMessages after ranking. Half of all captures were
# already hitting the old cap of 20 (measured over 1,463 logged actions on
# 2026-09-03: 104 of the 206 entries carrying messages had exactly 20, and
# nothing exceeded it), so the cap stays where it is - the fix is that the most
# severe entries survive it, and that truncation is now reported, not that more
# text comes back.
MESSAGE_CAP = 20

# Upper bound on what the generated C# collects before Python ranks it. Guards
# against a pathological action pushing a huge payload through the result file,
# while leaving ranking enough to choose from.
MESSAGE_SCAN_CAP = 500


# The action-result contract, declared rather than implied.
#
# Written because not having it cost real money three times in one session: a
# field was added and silently never reached the trace; a docstring pointed the
# model at a field that did not exist; and a guard meant to catch the second
# could not be written because there was no vocabulary to check names against.
#
# Each entry is (name, when_present, meaning). "when_present" is part of the
# contract, not a note: a field that appears unconditionally is a tax on every
# happy-path response, so anything diagnostic must be able to say when it stays
# quiet. Keep this in sync when adding a field - the tests below fail if a
# producer emits something undeclared.
RESULT_FIELDS = (
    # --- always present on a completed action
    ("success", "always", "Whether EPLAN reported the action as succeeding. NOT proof of effect: several actions return true having done nothing, and at least one returned false after a completed overwrite."),
    ("action", "on failures raised by this server", "The action string as sent."),
    ("parameters", "when the action returned any", "Values read back out of the ActionCallingContext."),
    ("executor", "always on the scripted path", 'Which executor ran it: "action" (ActionManager.FindAction + Action.Execute), "cli-fallback" (the action name did not resolve), "cli-legacy" (EPLAN_MCP_LEGACY_CLI=1), or "none" (it never ran).'),

    # --- diagnostics
    ("error", "when a cause is known", "Human-readable cause. Sourced either from the thrown exception chain or from ActionCallingContext.GetException()."),
    ("errorType", "with error, when the cause was an exception", "The .NET type name, e.g. Eplan.EplApi.Base.BaseException."),
    ("errorFrom", "with error, on the scripted path", '"context" if read from GetException() after execution, "throw" if the exception propagated. Provenance matters: errorType appeared in 0 of 1,463 logged actions before the context read landed, so the two channels have to stay distinguishable in the trace.'),
    ("message", "on failures raised by this server", "Server-side explanation, kept verbatim for callers matching on the older strings."),
    ("failedScriptPath", "when a generated script failed", "Where the generated C# was preserved, since the cleanup deletes the original and it is the only evidence of a compile error."),

    # --- EPLAN's own messages
    ("eplanMessages", "when EPLAN emitted any", "EPLAN's own text, severity-ranked then capped at MESSAGE_CAP. A list of strings."),
    ("eplanMessagesTotal", "with eplanMessages", "How many EPLAN produced, from the collection's own Count plus anything only the per-call context supplied."),
    ("eplanMessagesTruncated", "only when entries were dropped", "True when the cap discarded lower-severity entries."),
    ("eplanMessagesLevels", "only when something outranks Message", "Per-entry severity, parallel to eplanMessages."),
    ("eplanMessagesUnbounded", "only when the slice could not be bounded", "True when no end bookmark could be taken, so entries from outside this action may be included and the total is an upper bound."),
    ("eplanMessagesFromContextOnly", "only when the context knew more", "How many messages came from ActionCallingContext.SysMessages but not the bookmark slice. Its presence is the evidence that would justify switching channels."),

    # --- typed EPLAN failures (EplanBlockedByDialog / EplanActionTimeout / EplanBusy / EplanNotRunning)
    ("next_step", "on typed failures", "One concrete tool call or instruction that moves the caller forward."),
    ("timed_out", "on EplanBlockedByDialog and EplanActionTimeout", "True: the call was abandoned while EPLAN was still running it, so its result is lost."),
    ("dialogs", "only when a blocking window was seen", "The blocking windows, as listed by eplan_list_dialogs."),
    ("in_flight_action", "on EplanBusy and a timed-out ping while an action is stuck", "The earlier call EPLAN is still busy with."),
    ("eplan_state", "on EplanActionTimeout, EplanBusy and a timed-out ping", "'not_responding' when Windows flags EPLAN's main window Not Responding (frozen, or a heavy computation that may still finish), 'responding', or 'unknown'."),

    # --- completed actions EPLAN hung during
    ("not_responding_s", "only when Windows saw EPLAN Not Responding during the action", "Seconds, rounded, EPLAN's main window was flagged Not Responding while the call ran; sampled every DIALOG_CHECK_S, so short hangs are missed."),
    ("hang_note", "with not_responding_s", "Plain-language reading of not_responding_s. Its own key, so a tool's 'note' cannot overwrite it."),
)

# Fields the generated C# emits for the Python side to consume. They are
# internal plumbing and must never survive into a response - a leak of exactly
# this kind reached every no-message action before it was caught by running the
# template against live EPLAN.
INTERNAL_RESULT_FIELDS = (
    "eplanMessagesRaw",
    "eplanContextMessagesRaw",
    "eplanMessagesScanned",
    "eplanMessagesTrueTotal",
    "eplanMessagesBounded",
)

RESULT_FIELD_NAMES = tuple(name for name, _, _ in RESULT_FIELDS)

# Result keys copied into each actions.jsonl entry, on top of the always-present
# ts / action / duration_s / success.
#
# Derived from RESULT_FIELDS rather than hand-maintained, which is the whole
# point: this tuple is a FILTER, and a field missing from it never reaches the
# trace and so cannot be measured in a later audit. Deriving it means adding a
# field to the contract cannot forget the trace. "action" and "success" are
# excluded because _log_action writes them itself; "parameters" because the
# trace records intent, not the full echo.
#
# next_step, dialogs and hang_note stay out too: errorType and error already
# carry the cause into the trace, and dialogs can be large. timed_out and
# in_flight_action are logged: they say whether the call's effect is unknown.
_NOT_LOGGED = ("success", "action", "parameters", "next_step", "dialogs", "hang_note")
LOGGED_RESULT_KEYS = tuple(n for n in RESULT_FIELD_NAMES if n not in _NOT_LOGGED)


def carry_hang_note(src: dict, dst: dict) -> dict:
    """Copy not_responding_s and hang_note from the inner ExecuteScript result
    onto the result the caller gets: the hang belongs to the wrapped action."""
    for key in ("not_responding_s", "hang_note"):
        if key in src:
            dst[key] = src[key]
    return dst


class ShapingMixin:
    @staticmethod
    def _typed_failure(error_type, action, error, next_step, dialogs=None, timed_out=False,
                       eplan_state=None, in_flight_action=None):
        """The shared failure shape for an EPLAN call that did not complete."""
        result = {"success": False, "errorType": error_type, "error": error,
                  "message": error, "next_step": next_step, "action": action}
        if timed_out:
            result["timed_out"] = True
        if dialogs:
            result["dialogs"] = dialogs
        if eplan_state:
            result["eplan_state"] = eplan_state
        if in_flight_action:
            result["in_flight_action"] = in_flight_action
        return result

    @staticmethod
    def _with_hang_note(result: dict, hung_s: float) -> dict:
        """Add not_responding_s and hang_note when Windows saw EPLAN hang during the call."""
        s = round(hung_s)
        if s > 0:
            result["not_responding_s"] = s
            result["hang_note"] = (f"EPLAN was not responding for ~{s}s during this action "
                              "(heavy computation or a hang that recovered).")
        return result

    @staticmethod
    def _shape_messages(result: dict) -> dict:
        """Turn eplanMessagesRaw into a ranked, capped, honest eplanMessages.

        Replaces a plain "first 20 in tree order" slice. In tree order the 20
        kept were whichever EPLAN happened to log first, which for a chatty
        action means twenty "Started opening database" lines while the actual
        per-project error falls off the end - measured on a real
        upgrade_projects call.

        eplanMessages keeps its existing shape, a list of strings, so this is
        additive rather than a contract break. Added alongside it:
          eplanMessagesTruncated  only when entries were dropped
          eplanMessagesTotal      how many EPLAN actually produced
          eplanMessagesLevels     only when something above Message is present

        The "only when" matters: on the healthy path this adds nothing to the
        payload at all.
        """
        # Drain every internal hint first. The C# emits eplanMessagesBounded
        # and eplanMessagesTrueTotal whenever it took a bookmark, which is on
        # every action - so returning early before popping them leaked two
        # internal fields into the response of every action that produced no
        # messages at all, i.e. most of them. Caught by running the real
        # template against live EPLAN; the offline tests all supplied messages.
        drained = {name: result.pop(name, None)
                   for name in INTERNAL_RESULT_FIELDS}
        raw = drained["eplanMessagesRaw"]
        ctx_raw = drained["eplanContextMessagesRaw"]
        scanned = drained["eplanMessagesScanned"]
        true_total = drained["eplanMessagesTrueTotal"]
        bounded = drained["eplanMessagesBounded"]

        if not isinstance(raw, list):
            raw = []
        if not isinstance(ctx_raw, list):
            ctx_raw = []
        if not raw and not ctx_raw:
            return result

        # Merge the per-call context collection with the bookmark slice,
        # de-duplicating on text. The bookmark slice goes first so its
        # chronology survives; anything only the context knew about is
        # appended and counted, which is how we find out whether that channel
        # is worth switching to. On the two actions measured so far the two
        # sources agreed exactly, so this is expected to add nothing most of
        # the time - eplanMessagesFromContextOnly appearing at all is the
        # signal that the bookmark slice has a gap.
        seen = set()
        merged = []
        for record in raw:
            if not isinstance(record, dict):
                continue
            text = record.get("text")
            if text and text not in seen:
                seen.add(text)
                merged.append(record)
        context_only = 0
        for record in ctx_raw:
            if not isinstance(record, dict):
                continue
            text = record.get("text")
            if text and text not in seen:
                seen.add(text)
                merged.append(record)
                context_only += 1
        raw = merged

        # Prefer the collection's own Count over how many entries we walked.
        # eplanMessagesScanned is bounded by MESSAGE_SCAN_CAP, so using it as
        # the total under-reports whenever the scan cap is what stopped us -
        # which is precisely the case where an accurate total matters.
        total = true_total
        if not isinstance(total, int) or total < 1:
            total = scanned
        if not isinstance(total, int):
            total = len(raw)
        # Count is the bookmark collection's own total and knows nothing about
        # the context collection, so anything only the context supplied has to
        # be added or the total under-reports what we are holding.
        total += context_only

        def rank(record):
            level = (record or {}).get("level") or ""
            try:
                return MESSAGE_LEVEL_RANK.index(level)
            except ValueError:
                return len(MESSAGE_LEVEL_RANK)

        # sorted() is stable, so chronological order is preserved inside each
        # severity bucket - a reader still sees the sequence EPLAN produced.
        ordered = sorted((r for r in raw if isinstance(r, dict)), key=rank)
        kept = ordered[:MESSAGE_CAP]


        texts = [r.get("text", "") for r in kept if r.get("text")]
        if not texts:
            return result

        result["eplanMessages"] = texts
        result["eplanMessagesTotal"] = total
        if total > len(texts):
            result["eplanMessagesTruncated"] = True

        levels = [r.get("level") for r in kept if r.get("level")]
        if any(lvl != "Message" for lvl in levels):
            result["eplanMessagesLevels"] = levels

        # Only surfaced when the slice could NOT be bounded, since that is the
        # case where entries from outside this action may have leaked in and
        # the total is therefore an upper bound rather than a fact.
        if bounded is False:
            result["eplanMessagesUnbounded"] = True
        # Only when the context collection knew something the bookmark slice
        # did not. Absent on the healthy path, and its presence is the
        # evidence that would justify switching channels.
        if context_only:
            result["eplanMessagesFromContextOnly"] = context_only
        return result
