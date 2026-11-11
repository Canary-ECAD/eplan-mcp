"""
EPLAN's top-level windows, read and clicked from outside EPLAN (Win32, ctypes).

A modal dialog blocks every remoting call, so nothing here goes through the
EPLAN API: windows are found by the PID that owns them, and a control's text
is read with a bounded window message, so a hung EPLAN cannot hang this
module. Nothing here raises: on any error, or off Windows, a list comes back
empty and a click comes back as a failure dict.

Safe buttons are recognised by their standard Win32 control ID first, so they
work whatever language EPLAN and Windows run in, with a caption list in the
README's languages as the fallback for WinForms dialogs, whose buttons carry
no standard ID.

Covers Win32 #32770 dialogs and WinForms dialogs (every control is an HWND).
A WPF dialog shows its title only: its buttons are not windows.
"""

import ctypes
import time
import unicodedata
from ctypes import wintypes

WM_GETTEXT, WM_GETTEXTLENGTH, BM_CLICK = 0x000D, 0x000E, 0x00F5
SMTO_ABORTIFHUNG, GW_OWNER = 0x0002, 4
MAX_TEXT_LINES, MAX_TEXT_CHARS = 20, 500

# Standard dialog control IDs (winuser.h). A MessageBox gives its buttons
# these IDs in every language, so this is the reliable way to tell a safe
# button from an unsafe one: the caption is translated, the ID is not.
IDOK, IDCANCEL, IDABORT, IDRETRY, IDIGNORE, IDYES, IDNO, IDCLOSE = 1, 2, 3, 4, 5, 6, 7, 8
SAFE_BUTTON_IDS = frozenset({IDOK, IDCANCEL, IDNO, IDCLOSE})

# Fallback for buttons without a standard ID (WinForms). Lower-case, without
# the '&' mnemonic. OK, Cancel, Close, No and Skip in the languages the README
# ships in (en, de, es, ko, pl, ru, tr, zh-CN), plus fr, it and pt.
SAFE_BUTTON_CAPTIONS = frozenset({
    # en
    "ok", "cancel", "close", "no", "skip",
    # de
    "abbrechen", "schließen", "schliessen", "nein", "überspringen",
    # es
    "aceptar", "cancelar", "cerrar", "omitir",
    # fr
    "annuler", "fermer", "non", "ignorer",
    # it
    "annulla", "chiudi", "salta",
    # pt
    "fechar", "não", "nao", "ignorar",
    # pl
    "anuluj", "zamknij", "nie", "pomiń", "pomin",
    # ru
    "отмена", "закрыть", "нет", "пропустить",
    # tr
    "tamam", "iptal", "kapat", "hayır", "hayir", "atla",
    # zh-CN
    "确定", "取消", "关闭", "否", "跳过",
    # ko
    "확인", "취소", "닫기", "아니요", "아니오", "건너뛰기",
})

# Least committal first: used to suggest which button to press.
_SUGGEST_ORDER_IDS = (IDCANCEL, IDNO, IDCLOSE, IDOK)

# Known prompts whose safe answer is not the generic first choice (see
# eplan_click_dialog_button): Cancel would abort the open outright.
KNOWN_SAFE_BUTTON = {"Project master data": "No"}

# Buttons a progress box may carry. A window with a progress bar whose only
# buttons are these is EPLAN working, not EPLAN asking.
_PROGRESS_IDS = frozenset({IDOK, IDCANCEL, IDABORT, IDCLOSE})

# WINFUNCTYPE exists only on Windows; CFUNCTYPE keeps the import working
# elsewhere, where WinDLL then fails inside the guarded calls.
_WNDENUMPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_u32 = None


def _user32():
    global _u32
    if _u32 is None:
        api = ctypes.WinDLL("user32", use_last_error=True)
        signatures = {
            "EnumWindows": ([_WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
            "EnumChildWindows": ([wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
                                         wintypes.DWORD),
            "IsWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsHungAppWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "IsWindowEnabled": ([wintypes.HWND], wintypes.BOOL),
            "GetForegroundWindow": ([], wintypes.HWND),
            "GetWindow": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetDlgCtrlID": ([wintypes.HWND], ctypes.c_int),
            "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "SendMessageTimeoutW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_size_t)], wintypes.LPARAM),
            "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
                             wintypes.BOOL),
        }
        for name, (args, returns) in signatures.items():
            fn = getattr(api, name)
            fn.argtypes, fn.restype = args, returns
        _u32 = api
    return _u32


# ---------------------------------------------------------------------------
# Pure helpers (tested offline)
# ---------------------------------------------------------------------------

def norm_caption(text):
    """'&No' -> 'No'; '&&' stays a literal '&'. Surrounding space dropped."""
    return (text or "").replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def control_kind(cls):
    """'button', 'text', 'progress' or '' for a child window class (Win32 or WinForms)."""
    # WinForms wraps the Win32 class: "WindowsForms10.BUTTON.app.0.2bf8098_r6_ad1".
    base = cls.split(".")[1] if cls.startswith("WindowsForms") and "." in cls else cls
    base = base.upper()
    if base == "BUTTON":
        return "button"
    if base in ("STATIC", "EDIT") or base.startswith("RICHEDIT"):
        return "text"
    if "PROGRESS" in base:
        return "progress"
    return ""


def caption_key(text):
    """Comparison key for a caption: no mnemonic, case-folded, accents dropped.

    str.lower() is not enough: Turkish "İptal".lower() is "i" + a combining
    dot + "ptal", which matches nothing. Case-folding then stripping combining
    marks makes "İptal", "iptal", "Schließen" and "schliessen" compare equal.
    """
    folded = unicodedata.normalize("NFKD", norm_caption(text).casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def is_safe_button(caption, control_id=None):
    """Safe to press without asking: OK, Cancel, Close, No or Skip, in any language."""
    if control_id in SAFE_BUTTON_IDS:
        return True
    return caption_key(caption) in _SAFE_KEYS


def is_progress_box(buttons, has_progress):
    """A progress bar alone does not make a progress box (the Explorer file
    dialog has one in its address bar). Only a window whose buttons are all
    stop/acknowledge buttons is one."""
    if not has_progress:
        return False
    for b in buttons:
        if b.get("id") in _PROGRESS_IDS:
            continue
        if b.get("text") and not is_safe_button(b["text"]):
            return False
    return True


def is_blocking(window, new=False):
    """Is EPLAN waiting on this window?

    A modal window disables its owner (or EPLAN's main window). A MessageBox
    shown by a script with no owner disables nothing, so a standard dialog
    (#32770) that opened during the call counts too: `new` says it did.
    Progress boxes never count.
    """
    if window.get("is_main") or not window.get("enabled"):
        return False
    if is_progress_box(window.get("buttons") or [], window.get("has_progress")):
        return False
    if window.get("owner_disabled") or window.get("main_disabled"):
        return True
    return bool(new) and window.get("class") == "#32770"


def suggest_button(window):
    """The least committal safe button on `window`, or None."""
    buttons = window.get("buttons") or []
    known = KNOWN_SAFE_BUTTON.get(window.get("title"))
    if any(b.get("safe") and b.get("text") == known for b in buttons):
        return known
    by_id = {b.get("id"): b for b in buttons}
    for control_id in _SUGGEST_ORDER_IDS:
        if control_id in by_id:
            return by_id[control_id]["text"]
    for wanted in ("cancel", "no", "close", "ok", "skip"):
        for b in buttons:
            if b.get("safe") and _caption_meaning(b["text"]) == wanted:
                return b["text"]
    return next((b["text"] for b in buttons if b.get("safe")), None)


_MEANING = {
    "cancel": {"cancel", "abbrechen", "cancelar", "annuler", "annulla", "anuluj",
               "отмена", "iptal", "取消", "취소"},
    "no": {"no", "nein", "non", "não", "nao", "nie", "нет", "hayır", "hayir", "否",
           "아니요", "아니오"},
    "close": {"close", "schließen", "schliessen", "cerrar", "fermer", "chiudi", "fechar",
              "zamknij", "закрыть", "kapat", "关闭", "닫기"},
    "ok": {"ok", "aceptar", "tamam", "确定", "확인"},
}


def _caption_meaning(caption):
    key = caption_key(caption)
    return next((m for m, words in _MEANING_KEYS.items() if key in words), "skip")


_SAFE_KEYS = frozenset(caption_key(c) for c in SAFE_BUTTON_CAPTIONS)
_MEANING_KEYS = {m: frozenset(caption_key(w) for w in words) for m, words in _MEANING.items()}


# ---------------------------------------------------------------------------
# Win32 reads
# ---------------------------------------------------------------------------

def _class(u, hwnd):
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def _title(u, hwnd):
    # GetWindowTextW reads a top-level caption without messaging the owner,
    # so a hung EPLAN cannot hang this call.
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def _child_text(u, hwnd, ms):
    # Control text in another process is only reachable by WM_GETTEXT; the
    # timeout plus SMTO_ABORTIFHUNG keeps a hung dialog from hanging us.
    n = ctypes.c_size_t()
    if not u.SendMessageTimeoutW(hwnd, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, ms,
                                 ctypes.byref(n)):
        return ""
    buf = ctypes.create_unicode_buffer(min(n.value, 4096) + 1)
    if not u.SendMessageTimeoutW(hwnd, WM_GETTEXT, len(buf), ctypes.addressof(buf),
                                 SMTO_ABORTIFHUNG, ms, ctypes.byref(n)):
        return ""
    return buf.value


def _top(u, pids):
    """(hwnd, pid) of every visible top-level window owned by one of `pids`."""
    pids = {int(p) for p in pids}
    found = []

    def visit(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(hwnd):
            found.append((hwnd, pid.value))
        return True

    u.EnumWindows(_WNDENUMPROC(visit), 0)
    return found


def top_hwnds(pids):
    """hwnds of every visible top-level window of `pids`; set() on any error."""
    try:
        return {h for h, _ in _top(_user32(), pids)}
    except Exception:
        return set()


def _owner_disabled(owner, enabled):
    """Is `owner` a disabled window? Looked up in `enabled` (visible windows),
    else asked directly: a hidden owner frame is not in that map. Both only
    read a flag, so a hung EPLAN cannot hang them.

    The owner is not always the main window: "Open project" was seen owned by
    a floating BCGPMiniFrame, which it disabled, while the main window stayed
    enabled."""
    if not owner:
        return False
    if owner in enabled:
        return not enabled[owner]
    try:
        u = _user32()
        return bool(u.IsWindow(owner)) and not u.IsWindowEnabled(owner)
    except Exception:
        return False


def _foreground():
    try:
        return _user32().GetForegroundWindow() or 0
    except Exception:
        return 0


def _enum(pids, max_controls=100, text_timeout_ms=200, skip_main=True, candidates_only=False):
    """Raw facts about every visible top-level window of `pids`: hwnd, pid,
    title, class, owner, enabled, children [(hwnd, class, text, control id)].

    Reading a control's text costs one cross-process message, up to
    text_timeout_ms each while EPLAN is busy, so: skip_main leaves the main
    (Afx) window's children unread, and candidates_only leaves unread every
    window that cannot be blocking (the per-tick dialog check)."""
    u = _user32()
    tops = [(h, pid, _class(u, h), bool(u.IsWindowEnabled(h))) for h, pid in _top(u, pids)]
    # EPLAN's main window is an MFC frame ("Afx:..."); disabled while modal.
    main_disabled = {pid for _, pid, cls, en in tops if cls.startswith("Afx") and not en}
    enabled_map = {h: en for h, _, _, en in tops}
    out = []
    for hwnd, pid, cls, enabled in tops:
        is_main = cls.startswith("Afx")
        owner = u.GetWindow(hwnd, GW_OWNER) or 0
        candidate = (not is_main and enabled
                     and (cls == "#32770" or pid in main_disabled
                          or _owner_disabled(owner, enabled_map)))
        children = []
        if not ((skip_main and is_main) or (candidates_only and not candidate)):
            def child(h, _):
                children.append(h)
                return len(children) < max_controls
            u.EnumChildWindows(hwnd, _WNDENUMPROC(child), 0)
        kids = []
        for h in children:
            if not u.IsWindowVisible(h):
                continue
            c = _class(u, h)
            kind = control_kind(c)
            text = _child_text(u, h, text_timeout_ms) if kind in ("button", "text") else ""
            kids.append((h, c, text, u.GetDlgCtrlID(h) if kind == "button" else None))
        out.append({"hwnd": int(hwnd), "pid": pid, "title": _title(u, hwnd), "class": cls,
                    "owner": int(owner), "enabled": enabled, "children": kids})
    return out


def _shape(raw, include_main=False, new_since=None):
    """Window dicts from _enum's raw facts. Buttons keep their own hwnd under
    the private key "_hwnd" (see _public)."""
    windows = []
    for w in raw:
        buttons, text, has_progress = [], [], False
        for kid in w["children"]:
            h, c, value = kid[0], kid[1], kid[2]
            control_id = kid[3] if len(kid) > 3 else None
            kind = control_kind(c)
            if kind == "progress":
                has_progress = True
            elif kind == "button":
                caption = norm_caption(value)
                buttons.append({"text": caption, "id": control_id,
                                "safe": is_safe_button(caption, control_id), "_hwnd": h})
            elif kind == "text" and value.strip() and len(text) < MAX_TEXT_LINES:
                text.append(value[:MAX_TEXT_CHARS])
        windows.append({
            "hwnd": w["hwnd"], "pid": w["pid"], "title": w["title"], "class": w["class"],
            "owner": w.get("owner", 0), "enabled": w["enabled"],
            "is_main": w["class"].startswith("Afx"),
            "buttons": buttons, "text": text, "has_progress": has_progress,
        })
    main_disabled = {w["pid"] for w in windows if w["is_main"] and not w["enabled"]}
    enabled = {w["hwnd"]: w["enabled"] for w in windows}
    foreground = _foreground()
    out = []
    for w in windows:
        w["main_disabled"] = w["pid"] in main_disabled
        w["owner_disabled"] = _owner_disabled(w["owner"], enabled)
        w["foreground"] = bool(foreground) and w["hwnd"] == foreground
        new = new_since is not None and w["hwnd"] not in new_since
        w["blocking"] = is_blocking(w, new=new)
        # A true modal disables its owner or the main window; a #32770 that
        # only opened during the call blocks it without disabling anything.
        w["modal"] = w["blocking"] and (w["main_disabled"] or w["owner_disabled"])
        w["suggested_button"] = suggest_button(w) if w["blocking"] else None
        if include_main or not w["is_main"]:
            out.append(w)
    return out


def _public(window):
    """A window dict without the private button hwnds, for callers and JSON."""
    w = dict(window)
    w["buttons"] = [{k: v for k, v in b.items() if not k.startswith("_")}
                    for b in window.get("buttons") or []]
    return w


def list_windows(pids, include_main=False, new_since=None, max_controls=100,
                 text_timeout_ms=200, blocking_only=False):
    """One dict per visible top-level window of `pids`, [] on any error.

    Each: hwnd, pid, title, class, owner, enabled, is_main, owner_disabled,
    main_disabled, foreground, buttons [{text, id, safe}], text (message
    lines), has_progress, blocking, modal (blocking with its owner or EPLAN's
    main window disabled) and suggested_button.
    new_since: hwnds that existed before a call; windows not in it count as
    opened during the call (see is_blocking).
    blocking_only: read controls only on windows that can be blocking (the
    per-tick dialog check); the others come back with no buttons or text.
    """
    if not pids:
        return []
    try:
        raw = _enum(pids, max_controls, text_timeout_ms, not include_main, blocking_only)
        return [_public(w) for w in _shape(raw, include_main, new_since)]
    except Exception:
        return []


def responding(pids):
    """False when Windows flags EPLAN's main window Not Responding, True when
    not, None when it cannot be told. IsHungAppWindow only reads a flag."""
    try:
        u = _user32()
        mains = [h for h, _ in _top(u, pids) if _class(u, h).startswith("Afx")]
        return (not any(u.IsHungAppWindow(h) for h in mains)) if mains else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Click
# ---------------------------------------------------------------------------

def _post_click(button_hwnd):
    # Posted, not sent: the dialog's own modal loop handles it, so this never
    # blocks on a window busy unwinding the call it interrupted.
    return bool(_user32().PostMessageW(button_hwnd, BM_CLICK, 0, 0))


def _is_window(hwnd):
    return bool(_user32().IsWindow(hwnd))


def _fail(error_type, error, next_step):
    return {"success": False, "errorType": error_type, "error": error, "next_step": next_step}


def click_button(hwnd, button, title, pids, allow_any=False, wait_s=2.0):
    """Click `button` on window `hwnd`, after checking it is still EPLAN's
    window with that title. Only safe buttons unless allow_any."""
    caption = norm_caption(button)
    try:
        hwnd = int(hwnd)
        pids = {int(p) for p in pids or ()}
        windows = _shape(_enum(pids), include_main=False) if pids else []
    except Exception as e:
        return _fail("DialogNotFound", "Could not read EPLAN's windows: %s" % e,
                     "Call eplan_list_dialogs to see whether the window is still there.")
    match = next((w for w in windows if w["hwnd"] == hwnd and w["pid"] in pids), None)
    if match is None or match["title"] != title:
        return _fail("DialogNotFound",
                     "No EPLAN window %s titled %r is open any more; it may have "
                     "closed or been replaced." % (hwnd, title),
                     "Call eplan_list_dialogs and use the hwnd and title it returns now.")
    target = next((b for b in match["buttons"]
                   if caption_key(b["text"]) == caption_key(caption)), None)
    if target is None:
        return _fail("ButtonNotFound",
                     "Window %r has no button %r (buttons: %s)."
                     % (title, caption, ", ".join(b["text"] for b in match["buttons"]) or "none"),
                     "Use one of the listed buttons, spelled as shown.")
    if not allow_any and not target["safe"]:
        return _fail("ButtonNotAllowed",
                     "%r is not a safe button (OK, Cancel, Close, No or Skip in any "
                     "language), so it was not clicked." % caption,
                     "Click a safe button instead, or pass allow_any_button=True only "
                     "if the user asked for this button.")
    try:
        posted = _post_click(target["_hwnd"])
    except Exception:
        posted = False
    if not posted:
        return _fail("ButtonNotFound",
                     "Windows refused the click on %r; the window may have just closed." % caption,
                     "Call eplan_list_dialogs to see whether the window is still there.")
    deadline = time.monotonic() + wait_s
    closed = False
    while time.monotonic() < deadline:
        try:
            closed = not _is_window(hwnd)
        except Exception:
            break
        if closed:
            break
        time.sleep(0.1)
    return {"success": True, "hwnd": hwnd, "title": match["title"], "class": match["class"],
            "button": target["text"], "closed": closed}
