"""Blocking dialogs: dialogs.jsonl history and how to dismiss one."""

import json
import os
import re
import threading
import time
from collections import Counter

from connection.logs import _log_dir
from connection.processes import _eplan_windows


# A window that opened during a call and is still open this long, while the
# call has not finished, is presumed to be what EPLAN waits on - this catches
# prompts the class heuristic misses (WinForms pickers). Read per call.
NEW_WINDOW_GRACE_S = 20.0


def _new_window_grace() -> float:
    try:
        return float(os.environ.get("EPLAN_MCP_NEW_WINDOW_GRACE", NEW_WINDOW_GRACE_S))
    except ValueError:
        return NEW_WINDOW_GRACE_S


# Button order tried when suggesting how to dismiss a dialog whose buttons
# carry no safe flag (an older or hand-made window dict): least committal
# first. ui_windows.suggest_button does the same in any language.
_SAFEST_BUTTONS = ("Cancel", "No", "Close", "OK", "Skip")

# Known prompts whose safe answer is not the generic first choice; one table,
# so every window dict (list_dialogs, a blocked call's dialogs) agrees.
from ui_windows import KNOWN_SAFE_BUTTON as _KNOWN_SAFE_BUTTON  # noqa: E402

# Windows a tool knows it made EPLAN open, with what to do about them:
# (hwnd, title) -> next_step. A call blocked by such a window gets that
# instruction instead of the generic "which button?". Set and cleared by the
# tool that opened the window (dataportal.py, for EPLAN 2025's Data Portal
# window); the title is part of the key because Windows reuses hwnds.
WINDOW_HINTS = {}


def _button_texts(buttons) -> list:
    """Captions of a window's buttons: ui_windows gives {text, id, safe}
    dicts; plain strings are accepted too."""
    return [b.get("text", "") if isinstance(b, dict) else str(b) for b in buttons or []]


def _safe_texts(buttons) -> list:
    """Captions of the buttons safe to press without asking, in any language."""
    import ui_windows
    out = []
    for b in buttons or []:
        if isinstance(b, dict):
            safe = b.get("safe")
            if safe is None:
                safe = ui_windows.is_safe_button(b.get("text"), b.get("id"))
            if safe:
                out.append(b.get("text", ""))
        elif ui_windows.is_safe_button(b):
            out.append(str(b))
    return out


# Every blocking dialog a call ran into, and every click, one JSON line each,
# beside actions.jsonl. Read back by dialog_history to learn which prompts are
# expected and how they keep getting answered.
DIALOG_LOG = "dialogs.jsonl"
_history_cache = {"path": None, "offset": 0, "rows": {}, "titles": {}}
_history_lock = threading.Lock()


def dialog_history(log_dir=None) -> dict:
    """{title: summary} from dialogs.jsonl; {} when there is none. Never raises.

    learned_button is the button whose clicks closed the dialog most often,
    once it has at least 2 such clicks and 70% of them. The file is append-only,
    so only the bytes added since the last read are parsed.
    """
    try:
        path = os.path.join(log_dir or _log_dir(), DIALOG_LOG)
        size = os.path.getsize(path)
        with _history_lock:
            c = _history_cache
            if c["path"] != path or size < c["offset"]:     # other file, or truncated
                c.update(path=path, offset=0, rows={}, titles={})
            if size == c["offset"]:
                return c["titles"]
            with open(path, "rb") as f:
                f.seek(c["offset"])
                chunk = f.read(size - c["offset"])
            # A half-written last line waits for the next read.
            end = chunk.rfind(b"\n") + 1
            c["offset"] += end
            for line in chunk[:end].decode("utf-8", "replace").splitlines():
                try:
                    e = json.loads(line)
                    title = e["title"]
                except (ValueError, KeyError, TypeError):
                    continue
                r = c["rows"].setdefault(title, {"times_seen": 0, "last_seen": None,
                                                 "actions": Counter(), "clicks": Counter()})
                if e.get("event") == "seen":
                    r["times_seen"] += 1
                    r["last_seen"] = e.get("ts")
                    m = re.match(r'^([^\s/]+)', e.get("action") or "")
                    if m:
                        r["actions"][m.group(1)] += 1
                elif e.get("event") == "clicked" and e.get("success") and e.get("closed"):
                    # Only clicks that closed the dialog teach anything.
                    r["clicks"][e.get("button")] += 1
            titles = {}
            for title, r in c["rows"].items():
                button, n = (r["clicks"].most_common(1) or [(None, 0)])[0]
                learned = n >= 2 and n >= 0.7 * sum(r["clicks"].values())
                titles[title] = {"title": title, "times_seen": r["times_seen"],
                                 "last_seen": r["last_seen"],
                                 "triggered_by": dict(r["actions"].most_common(3)),
                                 "clicks": dict(r["clicks"]),
                                 "learned_button": button if learned else None}
            c["titles"] = titles
            return titles
    except Exception:
        return {}


def record_dialog(event: dict) -> None:
    """Append one event to dialogs.jsonl. Never raises: learning is a bonus."""
    try:
        log_dir = _log_dir()
        os.makedirs(log_dir, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
        with open(os.path.join(log_dir, DIALOG_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


class DialogMixin:
    @staticmethod
    def _dialog_next_step(dialog: dict, sent: bool = True) -> str:
        title = dialog.get("title", "")
        hint = WINDOW_HINTS.get((dialog.get("hwnd"), title))
        if hint:
            return hint
        buttons = _button_texts(dialog.get("buttons"))
        safe = _safe_texts(dialog.get("buttons"))
        then = ("verify state (e.g. eplan_get_current_project): the result of this "
                "action is unknown." if sent else "retry this call.")
        # What this exact prompt was answered with before (dialogs.jsonl).
        past = dialog_history().get(title) or {}
        learned = past.get("learned_button")
        learned = learned if learned in buttons else None
        known = _KNOWN_SAFE_BUTTON.get(title)
        suggested = dialog.get("suggested_button")
        button = (known if known in safe else
                  suggested if suggested in safe else
                  next((b for b in _SAFEST_BUTTONS if b in safe), None) or
                  next(iter(safe), None))
        # History is keyed by title alone and one title ("EPLAN") can cover
        # different prompts, so a learned answer is mentioned, never substituted.
        why = ""
        if learned and learned == button:
            why = f" (answered {learned!r} {past['clicks'][learned]} times before)"
        elif learned:
            why = (f" ({learned!r} answered it {past['clicks'][learned]} times before; "
                   "click it instead only after the user confirms"
                   + ("" if learned in safe else ", with allow_any_button=True")
                   + ")")
        if button is None:
            # Never name an unsafe button: the click would be refused, and the
            # override is the user's call, not the model's.
            how = ("ask which button to press; call eplan_click_dialog_button with "
                   "allow_any_button=True only for a button the user names"
                   if buttons else "ask the user to answer it in EPLAN")
            return (f"Show the user dialog {title!r} (eplan_list_dialogs has its text) "
                    f"and {how}{why}. Then {then}")
        return (f"eplan_click_dialog_button(hwnd={dialog.get('hwnd')}, button={button!r}, "
                f"window_title={title!r}){why}, then {then}")

    def _note_dialogs(self, dialogs, phase, action) -> None:
        """Record each blocking dialog as "seen" once while it stays open, keyed
        hwnd+title, so retries against the same dialog do not inflate times_seen."""
        recorded = self._recorded
        self._recorded = {(d.get("hwnd"), d.get("title")) for d in dialogs}  # forget closed ones
        for d in dialogs:
            if (d.get("hwnd"), d.get("title")) in recorded:
                continue
            record_dialog({"event": "seen", "phase": phase, "title": d.get("title", ""),
                                 "class": d.get("class", ""), "buttons": _button_texts(d.get("buttons")),
                                 "text": [t[:200] for t in (d.get("text") or [])[:3]],
                                 "action": action})

    def _new_windows(self, state, windows, found, now, label):
        """(learned, suspected): windows that opened after the call was sent and
        that the class heuristic did not flag. learned: titles a blocking dialog
        has had and dialogs.jsonl has a learned_button for, sent down the fast
        path. suspected: any other one that disabled its owner or is in the
        foreground (a status form does neither), open past the grace period.
        Either must have a title or a button and not be a progress box; each
        suspect is recorded and returned once."""
        if state["before"] is None:             # pid was unknown before sending
            # ponytail: taken one tick late, so a window that opened in the first
            # DIALOG_CHECK_S is missed unless it disabled its owner; no pid also
            # means every local EPLAN is watched. Both end in the plain timeout.
            state["before"] = {w["hwnd"] for w in windows if not w.get("owner_disabled")}
            return [], []
        flagged = {d.get("hwnd") for d in found}
        history, grace = dialog_history(), _new_window_grace()
        new, learned, due = {}, [], []
        for w in windows:
            h = w["hwnd"]
            if h in state["before"]:
                continue
            # First-seen survives a tick spent flagged or disabled.
            new[h] = first = state["new"].get(h, now)
            if h in flagged or w.get("blocking") or w.get("is_main") or not w.get("enabled"):
                continue
            title = w.get("title")
            past = (history.get(title) or {}) if title else {}
            if past.get("times_seen", 0) >= 1 and past.get("learned_button"):
                learned.append(h)
            elif (now - first >= grace and h not in state["decided"]
                  and (w.get("owner_disabled") or w.get("foreground"))):
                due.append(h)
        state["new"] = new          # a window that closed starts over if it returns
        if not (learned or due):
            return [], []
        # Controls are read only now, once something is worth naming, and once
        # per window: a learned window open for the whole call is not re-read.
        # ponytail: that one read still covers every non-main window; read only
        # the wanted hwnds if it ever shows up in a tick's cost.
        import ui_windows   # importable: _eplan_windows just returned windows
        cache = state["full"]
        if any(h not in cache for h in learned + due):
            fresh = {w["hwnd"]: w for w in _eplan_windows(state["pids"], full=True)}
            cache.update((h, fresh[h]) for h in learned + due if h in fresh)

        def worth(w):
            if not w or not (w.get("title") or w.get("buttons")):
                return False
            buttons = [b if isinstance(b, dict) else {"text": b} for b in w.get("buttons") or []]
            return not ui_windows.is_progress_box(buttons, w.get("has_progress"))
        suspected = []
        for h in due:
            state["decided"].add(h)
            w = cache.get(h)
            if not worth(w):
                continue
            w = {**w, "suspected": True, "appeared_s": round(new[h] - state["start"])}
            # Not "seen": a suspect must not teach the fast path (dialog_history).
            record_dialog({"event": "suspected", "phase": "new_window",
                           "title": w.get("title", ""),
                           "class": w.get("class", ""), "buttons": _button_texts(w.get("buttons")),
                           "text": [t[:200] for t in (w.get("text") or [])[:3]],
                           "action": label})
            suspected.append(w)
        return [cache[h] for h in learned if worth(cache.get(h))], suspected
