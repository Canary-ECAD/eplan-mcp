"""Running one EPLAN call with a deadline and a blocking-dialog fail-fast."""

import os
import time

from connection.dialogs import _button_texts
from connection.logs import logger
from connection.processes import (
    _STATE_WORDS,
    _blocking_dialogs,
    _eplan_hwnds,
    _eplan_windows,
    _responding,
    eplan_pids,
    eplan_state,
    PID_SETTLE_S,
    pid_alive,
)


# Upper bound on one ExecuteAction call. Unlike the wait above, this one does
# bound a hang: a modal dialog or a wedged EPLAN otherwise blocks the call, and
# the server with it, forever. Generous because full-project exports are slow.
# Override with EPLAN_MCP_ACTION_TIMEOUT (seconds), read per call.
ACTION_TIMEOUT_S = 600.0

# errorType values for an EPLAN call that did not complete. Blocked, timed out
# and busy calls were abandoned, not failed: EPLAN may still finish them, so
# their result is unknown. EplanNotRunning: EPLAN died under the call.
TYPED_FAILURES = ("EplanBlockedByDialog", "EplanActionTimeout", "EplanBusy", "EplanNotRunning")


def _env_seconds(name, default):
    """A positive number of seconds from the environment, else `default`.

    A typo in a client config must never stop the server from starting, so a
    bad value is logged (to stderr) and ignored rather than raised.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
        if value > 0:
            return value
    except ValueError:
        pass
    logger.warning(f"{name}={raw!r} is not a positive number of seconds; using {default}")
    return default


def action_timeout_s() -> float:
    """EPLAN_MCP_ACTION_TIMEOUT, read per call so it can change at runtime."""
    return _env_seconds("EPLAN_MCP_ACTION_TIMEOUT", ACTION_TIMEOUT_S)

# How often a running action is checked for a blocking dialog. Two hits in a
# row end the wait, so a dialog that flashes up and closes does not.
DIALOG_CHECK_S = 2.0


def _dialog_failfast() -> bool:
    """EPLAN_MCP_DIALOG_FAILFAST=0 turns the dialog abort off (the deadline
    stays). For harnesses that block on a modal on purpose while their own
    watcher clicks it through. Read per call so it can change at runtime."""
    return os.environ.get("EPLAN_MCP_DIALOG_FAILFAST", "1").strip().lower() not in ("0", "false", "no", "off")


def call_with_timeout(func, timeout_seconds, *args, abort_check=None, check_every=2.0, **kwargs):
    """
    Run a blocking call with a deadline. Returns (result, timed_out, error).

    Every EplanRemoteClient call except Connect() is an unbounded synchronous
    call into the CLR. When EPLAN cannot service it - a human mid-edit, a modal
    dialog, a project that will not close - the call never returns, and with it
    goes the tool that made it AND this server's ability to answer anything
    else. Measured 2026-09-11: StopEplan() blocked for 8m44s while a human had
    a project open, and the session's only recovery was restarting the server.

    The worker is a daemon thread and is deliberately NOT joined after the
    timeout: it is stuck in native code and cannot be interrupted. Letting it
    leak is the lesser evil - the alternative is hanging forever, which is the
    bug being fixed. It ends when the process does.

    abort_check, if given, is polled every check_every seconds while the call
    runs; the first truthy value it returns ends the wait early as
    (that_value, True, None). A plain timeout still returns (None, True, None).
    """
    import threading

    box = {}

    def run():
        try:
            box["value"] = func(*args, **kwargs)
        except BaseException as e:      # noqa: BLE001 - reported, not swallowed
            box["error"] = e

    worker = threading.Thread(target=run, daemon=True,
                              name=f"eplan-call-{getattr(func, '__name__', 'anon')}")
    worker.start()
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        worker.join(max(0, min(check_every, remaining) if abort_check else remaining))
        if not worker.is_alive():
            return box.get("value"), False, box.get("error")
        if remaining <= check_every or not abort_check:
            return None, True, None
        hit = abort_check()
        if hit:
            return hit, True, None


class RunnerMixin:
    def _watch_pids(self):
        """PIDs to scan for dialogs: the connected EPLAN, else every local one."""
        # A stale pid (EPLAN closed outside the MCP, PID since reused) must not
        # aim a dialog scan or click at another program.
        if self.pid and pid_alive(self.pid) is not False:
            return {self.pid}
        if self.host in self.LOCAL_HOSTS:
            return set(eplan_pids())
        return set()

    def _stuck_next_step(self) -> str:
        """next_step for a call still in flight with no dialog on screen."""
        if not self._inflight:
            return "Wait a few seconds, then retry: another call to EPLAN is finishing."
        age = time.monotonic() - self._inflight_since
        limit = action_timeout_s()
        if age >= limit:
            return (f"EPLAN has been stuck on '{self._inflight}' for {age:.0f}s with no "
                    "dialog found. After confirming with the user, call "
                    "eplan_app_restart(force=True); eplan_connect alone does not unstick EPLAN.")
        return (f"EPLAN is still running '{self._inflight}': wait, then retry. If "
                "eplan_list_dialogs shows nothing and it is still stuck after "
                f"{limit:g}s, ask the user before calling "
                "eplan_app_restart(force=True).")

    def _busy_failure(self, action: str) -> dict:
        """EplanBusy: another call still holds EPLAN, so this one was not sent."""
        running = self._inflight
        pids = self._watch_pids()
        dialogs = _blocking_dialogs(pids) if pids else []
        self._note_dialogs(dialogs, "busy", running or action)
        st = eplan_state(pids)
        what = (f"EPLAN is still running '{running}' from an earlier call" if running
                else "Another call to EPLAN is still in progress")
        return self._typed_failure(
            "EplanBusy", action,
            what + ", so this call was not sent." + ("" if dialogs else _STATE_WORDS.get(st, "")),
            self._dialog_next_step(dialogs[0]) if dialogs else self._stuck_next_step(),
            dialogs=dialogs, eplan_state=st, in_flight_action=running)

    def _bounded_execute(self, action: str, label: str = None, timeout: float = None):
        """(_bounded_execute_locked's result, seconds EPLAN was seen Not Responding).
        The seconds are read under the lock, so an overlapping call cannot swap them."""
        if not self._exec_lock.acquire(timeout=DIALOG_CHECK_S):
            return self._busy_failure(action), 0.0
        try:
            return (self._bounded_execute_locked(action, label or action, timeout),
                    self._not_responding_s)
        finally:
            self._exec_lock.release()

    def _bounded_execute_locked(self, action: str, label: str, timeout: float = None):
        """Run client.ExecuteAction(action) with a deadline.

        Returns None when EPLAN completed the call, a typed failure dict when it
        did not, and re-raises an exception from a live EPLAN for the caller's
        existing handler. A call abandoned on timeout keeps running inside
        EPLAN; self._inflight stays set until it returns, and refuses new calls
        meanwhile, since EPLAN would only queue them behind it.
        """
        self._not_responding_s = 0.0
        failfast = _dialog_failfast()
        if self._inflight:
            return self._busy_failure(action)

        # Pre-flight: a dialog already up would only swallow this call too.
        # Only with a known pid, so it never costs a tasklist spawn.
        pids = self._watch_pids() if self.pid else None
        if pids and failfast:
            # Only a true modal (EPLAN's main window disabled behind it) refuses
            # a call unsent: a modeless #32770 tool window does not block EPLAN.
            def modal():
                return [d for d in _blocking_dialogs(pids) if d.get("modal")]
            found = modal()
            if found:
                # Looked at twice, like the in-call check: the previous call's
                # dialog (back-to-back script plumbing) may still be closing.
                time.sleep(min(0.5, DIALOG_CHECK_S))
                found = modal()
            if found:
                self._note_dialogs(found, "preflight", label)
                d = found[0]
                buttons = ", ".join(_button_texts(d.get("buttons"))) or "none found"
                return self._typed_failure(
                    "EplanBlockedByDialog", action,
                    f"EPLAN already has dialog '{d.get('title', '')}' open (buttons: "
                    f"{buttons}); this call was not sent.",
                    self._dialog_next_step(d, sent=False), dialogs=found)

        client = self.client
        state = {"pids": pids, "prev": False, "hung_s": 0.0, "tick": time.monotonic(),
                 "last": [], "start": time.monotonic(), "new": {}, "decided": set(),
                 "full": {},
                 # Windows open before the call cannot be what it waits on.
                 "before": _eplan_hwnds(pids) if pids else None}

        def dialog_check():
            # PIDs resolved on the first check only, so a fast action never
            # pays for a tasklist spawn.
            if state["pids"] is None:
                state["pids"] = self._watch_pids()
            # Not Responding is sampled, never acted on: heavy computations
            # set it legitimately. It only ends up in the result.
            now = time.monotonic()
            if state["pids"] and _responding(state["pids"]) is False:
                state["hung_s"] += now - state["tick"]
                self._not_responding_s = state["hung_s"]
            state["tick"] = now
            found = learned = suspected = []
            if state["pids"]:
                # One enumeration per tick. A standard dialog that opened during
                # the call blocks it even when it disables nothing (an ownerless
                # MessageBox from a script).
                windows = (_eplan_windows(state["pids"], new_since=state["before"])
                           if state["before"] is not None else _eplan_windows(state["pids"]))
                found = _blocking_dialogs(state["pids"], windows)
                learned, suspected = self._new_windows(state, windows, found, now, label)
            found = found + learned
            # Reported as blocking once: never reported again as a suspect.
            state["decided"].update(d.get("hwnd") for d in found)
            self._note_dialogs(found, "during", label)
            state["last"] = found
            # With failfast off the loop still runs to sample and record;
            # it just never aborts. A suspect already waited out its grace.
            hit = found if (found and state["prev"] and failfast) else None
            hit = hit or (suspected if failfast else None)
            state["prev"] = bool(found)
            return hit

        def run():
            try:
                client.ExecuteAction(action)
            finally:
                # A call leaked past a reconnect must not clear the marker
                # of a call made on the new client.
                if self.client is client:
                    self._inflight = None

        self._inflight, self._inflight_since = label, time.monotonic()
        # A caller's own longer budget (e.g. a script's timeout_seconds) wins
        # over the default; it never shortens it.
        limit = max(action_timeout_s(), timeout or 0)
        dialogs, timed_out, error = call_with_timeout(
            run, limit, abort_check=dialog_check, check_every=DIALOG_CHECK_S)
        # With failfast off a dialog never aborts, but one still up at the
        # deadline is why the call did not finish.
        if timed_out and not dialogs:
            dialogs = state["last"]
        if timed_out and dialogs and dialogs[0].get("suspected"):
            d = dialogs[0]
            buttons = ", ".join(_button_texts(d.get("buttons"))) or "none found"
            return self._typed_failure(
                "EplanBlockedByDialog", action,
                f"A new EPLAN window '{d.get('title', '')}' (buttons: {buttons}) appeared "
                f"{d['appeared_s']}s into the action and is still open; EPLAN has not "
                "finished, so it is probably waiting on it.",
                self._dialog_next_step(d) + " If this window is expected to stay open "
                "(a tool window), tell the user; set EPLAN_MCP_NEW_WINDOW_GRACE higher "
                "to wait longer.", dialogs=dialogs, timed_out=True)
        if timed_out and dialogs:
            d = dialogs[0]
            buttons = ", ".join(_button_texts(d.get("buttons"))) or "none found"
            return self._typed_failure(
                "EplanBlockedByDialog", action,
                f"EPLAN is waiting on dialog '{d.get('title', '')}' (buttons: {buttons}); "
                "the action has not finished.",
                self._dialog_next_step(d), dialogs=dialogs, timed_out=True)
        if timed_out:
            st = eplan_state(state["pids"])
            return self._typed_failure(
                "EplanActionTimeout", action,
                f"EPLAN did not finish the action within {limit:g}s and no "
                "blocking dialog is open; it may still be running."
                + _STATE_WORDS.get(st, ""),
                "Call eplan_ping until it answers, then verify state. If this action "
                "legitimately takes longer, set EPLAN_MCP_ACTION_TIMEOUT (seconds; "
                "read per call). If EPLAN never answers and "
                "eplan_list_dialogs shows nothing, ask the user before calling "
                "eplan_app_restart(force=True).",
                timed_out=True, eplan_state=st, in_flight_action=self._inflight)
        # Checked even when the call returned cleanly: measured on EPLAN 2027,
        # ExecuteAction returns without raising when EPLAN is killed under it.
        if self.pid and self.host in self.LOCAL_HOSTS and pid_alive(self.pid, PID_SETTLE_S) is False:
            self.connected = False
            how = f"failed with: {error}" if error is not None else "did not complete"
            return self._typed_failure(
                "EplanNotRunning", action,
                f"EPLAN (pid {self.pid}) is no longer running; the call {how}",
                "eplan_app_launch")
        if error is not None:
            raise error
        return None
