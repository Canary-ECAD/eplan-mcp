"""The pure half of ui_windows: which buttons are safe, which windows block.

The point of the rewrite: a safe button is recognised in any language. A
MessageBox gives its buttons the standard control IDs whatever language
Windows runs in; WinForms buttons have no such ID, so their captions are
matched against a list in the README's languages.
"""
import pytest

import ui_windows as uw


@pytest.mark.parametrize("caption, control_id", [
    ("OK", None), ("&Cancel", None), ("Abbrechen", None), ("&Nein", None),
    ("Cancelar", None), ("Cerrar", None), ("Anuluj", None), ("Отмена", None),
    ("İptal", None), ("iptal", None), ("取消", None), ("취소", None), ("아니요", None),
    # Unknown caption, but a MessageBox ID says what it is.
    ("Weiß nicht", uw.IDCANCEL), ("Whatever", uw.IDNO), ("x", uw.IDOK),
])
def test_safe_buttons_in_any_language(caption, control_id):
    assert uw.is_safe_button(caption, control_id)


@pytest.mark.parametrize("caption, control_id", [
    ("Yes", None), ("&Ja", None), ("Sí", None), ("Save", None), ("Speichern", None),
    ("Löschen", None), ("Delete", None), ("Да", uw.IDYES), ("Retry", uw.IDRETRY),
])
def test_unsafe_buttons(caption, control_id):
    assert not uw.is_safe_button(caption, control_id)


def test_norm_caption_drops_the_mnemonic_but_keeps_a_literal_ampersand():
    assert uw.norm_caption("&No") == "No"
    assert uw.norm_caption(" Save && Close ") == "Save & Close"


@pytest.mark.parametrize("cls, kind", [
    ("Button", "button"), ("WindowsForms10.BUTTON.app.0.2bf8098_r6_ad1", "button"),
    ("Static", "text"), ("RichEdit20W", "text"),
    ("msctls_progress32", "progress"), ("WindowsForms10.msctls_progress32.app.0.1", "progress"),
    ("SysListView32", ""),
])
def test_control_kind(cls, kind):
    assert uw.control_kind(cls) == kind


def _window(**kw):
    w = {"hwnd": 1, "class": "#32770", "enabled": True, "is_main": False,
         "owner_disabled": False, "main_disabled": False, "has_progress": False,
         "buttons": [{"text": "Yes", "id": uw.IDYES, "safe": False},
                     {"text": "No", "id": uw.IDNO, "safe": True}]}
    w.update(kw)
    return w


def test_a_modal_dialog_blocks():
    assert uw.is_blocking(_window(owner_disabled=True))
    assert uw.is_blocking(_window(**{"class": "x", "main_disabled": True}))


def test_an_ownerless_messagebox_blocks_only_when_it_opened_during_the_call():
    w = _window()
    assert uw.is_blocking(w, new=True)
    assert not uw.is_blocking(w, new=False), "a modeless dialog the user had open"


def test_a_winforms_window_that_disables_nothing_does_not_block():
    assert not uw.is_blocking(_window(**{"class": "WindowsForms10.Window.8.app"}), new=True)


def test_progress_boxes_and_the_main_window_never_block():
    progress = _window(owner_disabled=True, has_progress=True,
                       buttons=[{"text": "Abbrechen", "id": uw.IDCANCEL, "safe": True}])
    assert not uw.is_blocking(progress)
    assert not uw.is_blocking(_window(is_main=True, main_disabled=True))
    assert not uw.is_blocking(_window(owner_disabled=True, enabled=False))


def test_a_progress_bar_beside_real_choices_still_blocks():
    """The Explorer file dialog has a progress bar in its address bar."""
    w = _window(owner_disabled=True, has_progress=True,
                buttons=[{"text": "Öffnen", "id": uw.IDOK, "safe": True},
                         {"text": "Übernehmen", "id": 1001, "safe": False}])
    assert uw.is_blocking(w)


@pytest.mark.parametrize("buttons, expected", [
    # Least committal first: Cancel, then No, then Close, then OK.
    ([("Ja", uw.IDYES), ("Nein", uw.IDNO), ("Abbrechen", uw.IDCANCEL)], "Abbrechen"),
    ([("Sí", uw.IDYES), ("No", uw.IDNO)], "No"),
    ([("Aceptar", uw.IDOK)], "Aceptar"),
    # WinForms, no IDs: by caption meaning.
    ([("Speichern", 0), ("Schließen", 0)], "Schließen"),
    ([("Tak", 0), ("Nie", 0)], "Nie"),
    ([("Yes", uw.IDYES), ("Save", 0)], None),
])
def test_suggest_button(buttons, expected):
    window = {"buttons": [{"text": t, "id": i, "safe": uw.is_safe_button(t, i)}
                          for t, i in buttons]}
    assert uw.suggest_button(window) == expected


def test_suggest_button_known_prompt_wins_everywhere():
    # Every window dict (a blocked call's dialogs too) must say No, not Cancel.
    buttons = [{"text": t, "id": i, "safe": uw.is_safe_button(t, i)}
               for t, i in (("Yes", 6), ("No", 7), ("Cancel", 2))]
    assert uw.suggest_button({"title": "Project master data", "buttons": buttons}) == "No"
    assert uw.suggest_button({"title": "Other", "buttons": buttons}) == "Cancel"


def test_reads_never_raise_and_return_nothing_without_pids():
    assert uw.list_windows(set()) == []
    assert uw.list_windows({0}) == [] or isinstance(uw.list_windows({0}), list)
    assert isinstance(uw.top_hwnds({0}), set)


def test_click_refuses_a_window_that_is_not_there():
    result = uw.click_button(1, "OK", "Nope", {0})
    assert result["success"] is False
    assert result["errorType"] == "DialogNotFound"
    assert "eplan_list_dialogs" in result["next_step"]


# ---------------------------------------------------------------------------
# Reads and clicks with Win32 faked (_enum / _post_click / _is_window), and
# the dialog tools on top of them.
# ---------------------------------------------------------------------------

import os
import sys

from api.actions import dialogs

DLG = 0x1234


def _raw(hwnd=DLG, pid=42, title="Project master data", cls="#32770", enabled=True,
         owner=0, children=((1, "Button", "&Yes"), (2, "Button", "&No"), (3, "Static", "Sync?"))):
    return {"hwnd": hwnd, "pid": pid, "title": title, "class": cls, "owner": owner,
            "enabled": enabled, "children": list(children)}


@pytest.fixture
def fake(monkeypatch):
    state = {"windows": [_raw()], "clicked": []}
    monkeypatch.setattr(uw, "_enum", lambda pids, *a: state["windows"])
    monkeypatch.setattr(uw, "_foreground", lambda: 0)
    monkeypatch.setattr(uw, "_post_click", lambda h: state["clicked"].append(h) or True)
    monkeypatch.setattr(uw, "_is_window", lambda h: not state["clicked"])
    return state


def test_list_windows_shapes_and_hides_main(fake):
    fake["windows"] = [_raw(hwnd=1, cls="Afx:400000:8", enabled=False, children=()),
                       _raw(cls="WindowsForms10.Window.8.app", children=(
                           (5, "WindowsForms10.BUTTON.app", "&OK"),
                           (6, "msctls_progress32", "")))]
    (w,) = uw.list_windows({42})
    assert w["hwnd"] == DLG and [b["text"] for b in w["buttons"]] == ["OK"]
    assert w["has_progress"] and w["blocking"] is False     # a progress box is not a prompt
    assert "_hwnd" not in w["buttons"][0]
    both = uw.list_windows({42}, include_main=True)
    assert both[0]["is_main"] and not both[0]["blocking"]


def test_a_message_box_that_opened_during_the_call_blocks(fake):
    (w,) = uw.list_windows({42}, new_since=set())
    assert w["blocking"] and w["modal"] is False
    assert [b["text"] for b in w["buttons"]] == ["Yes", "No"] and w["text"] == ["Sync?"]
    assert w["suggested_button"] == "No"
    (w,) = uw.list_windows({42})
    assert not w["blocking"], "open before the call and disabling nothing: modeless"


@pytest.mark.parametrize("main_enabled, modal", [(True, False), (False, True)])
def test_modal_only_behind_a_disabled_main(fake, main_enabled, modal):
    fake["windows"] = [_raw(hwnd=1, cls="Afx:400000:8", enabled=main_enabled, children=()),
                       _raw()]
    (w,) = uw.list_windows({42}, new_since={1})
    assert w["blocking"] and w["modal"] is modal


def test_a_disabled_owner_that_is_not_the_main_window_makes_it_modal(fake):
    # "Open project" seen owned by a floating BCGPMiniFrame it disabled, while
    # the main window stayed enabled.
    fake["windows"] = [_raw(hwnd=1, cls="AfxMDIFrame140u", enabled=True, children=()),
                       _raw(hwnd=7, cls="BCGPMiniFrame:400000:8", enabled=False, children=()),
                       _raw(owner=7, title="Open project",
                            children=((5, "Button", "&Open"), (6, "Button", "Cancel")))]
    (w,) = [w for w in uw.list_windows({42}) if w["class"] == "#32770"]
    assert w["owner_disabled"] and w["blocking"] and w["modal"]


def test_a_hidden_disabled_owner_is_asked_directly(fake, monkeypatch):
    class U:
        IsWindow = staticmethod(lambda h: h == 77)
        IsWindowEnabled = staticmethod(lambda h: False)
    monkeypatch.setattr(uw, "_user32", lambda: U)
    fake["windows"] = [_raw(owner=77)]
    (w,) = uw.list_windows({42})
    assert w["owner_disabled"] and w["modal"]


def test_foreground_is_reported(fake, monkeypatch):
    monkeypatch.setattr(uw, "_foreground", lambda: DLG)
    (w,) = uw.list_windows({42})
    assert w["foreground"] is True


def test_file_dialog_with_a_progress_control_still_blocks(fake):
    # EPLAN's "Open project" (#32770) carries msctls_progress32 in its Explorer
    # address bar; treating it as a progress box hid it for the whole timeout.
    fake["windows"] = [_raw(children=(
        (5, "Button", "&Open"), (6, "Button", "Cancel"), (7, "msctls_progress32", "")))]
    (w,) = uw.list_windows({42}, new_since=set())
    assert w["has_progress"] and w["blocking"] is True


def test_list_windows_never_raises(monkeypatch):
    def boom(*a):
        raise OSError("no user32")
    monkeypatch.setattr(uw, "_enum", boom)
    assert uw.list_windows({1}) == []


def test_click_safe_button(fake):
    res = uw.click_button(DLG, "No", "Project master data", {42}, wait_s=0.5)
    assert res == {"success": True, "hwnd": DLG, "title": "Project master data",
                   "class": "#32770", "button": "No", "closed": True}
    assert fake["clicked"] == [2]


def test_click_refuses_unsafe_button(fake):
    res = uw.click_button(DLG, "&Yes", "Project master data", {42})
    assert res["errorType"] == "ButtonNotAllowed" and res["next_step"]
    assert fake["clicked"] == []


def test_click_allow_any_permits_yes(fake):
    res = uw.click_button(DLG, "Yes", "Project master data", {42}, allow_any=True, wait_s=0.1)
    assert res["success"] and fake["clicked"] == [1]


@pytest.mark.parametrize("windows, title", [([_raw()], "Something else"), ([_raw(pid=99)], None)])
def test_click_refuses_another_window(fake, windows, title):
    fake["windows"] = windows
    res = uw.click_button(DLG, "No", title or "Project master data", {42})
    assert res["errorType"] == "DialogNotFound" and fake["clicked"] == []


def test_click_refuses_missing_button(fake):
    res = uw.click_button(DLG, "Cancel", "Project master data", {42})
    assert res["errorType"] == "ButtonNotFound" and "Yes, No" in res["error"]
    assert fake["clicked"] == []


class _Mgr:
    def __init__(self, connected=True, pids=frozenset({7})):
        self.connected, self._pids = connected, set(pids)

    def _watch_pids(self):
        return self._pids


def test_list_dialogs_scopes_to_the_connected_eplan(monkeypatch):
    seen = {}
    monkeypatch.setattr(dialogs, "get_manager", lambda: _Mgr())
    monkeypatch.setattr(dialogs, "eplan_pids", lambda: pytest.fail("must not scan"))
    monkeypatch.setattr(dialogs.ui_windows, "list_windows",
                        lambda pids, include_main: seen.setdefault("pids", pids) and
                        [{"blocking": True}])
    monkeypatch.setattr(dialogs, "eplan_state", lambda pids: "responding")
    res = dialogs.list_dialogs()
    assert seen["pids"] == {7}
    assert res == {"success": True, "count": 1, "windows": [{"blocking": True}],
                   "blocking_count": 1, "eplan_state": "responding"}


def test_list_dialogs_suggests_no_on_project_master_data(fake, monkeypatch):
    fake["windows"] = [_raw(children=((1, "Button", "&Yes"), (2, "Button", "&No"),
                                      (3, "Button", "Cancel")))]
    monkeypatch.setattr(dialogs, "get_manager", lambda: _Mgr(pids={42}))
    real = uw.list_windows
    monkeypatch.setattr(dialogs.ui_windows, "list_windows",
                        lambda pids, include_main: real(pids, include_main, new_since=set()))
    monkeypatch.setattr(dialogs, "eplan_state", lambda pids: "responding")
    (w,) = dialogs.list_dialogs()["windows"]
    assert w["suggested_button"] == "No", "Cancel would abort the open outright"


def test_list_dialogs_without_eplan_says_so(monkeypatch):
    monkeypatch.setattr(dialogs, "get_manager", lambda: _Mgr(connected=False))
    monkeypatch.setattr(dialogs, "eplan_pids", lambda: [])
    assert dialogs.list_dialogs()["errorType"] == "EplanNotFound"


def test_click_dialog_button_falls_back_to_all_eplan_pids(monkeypatch, tmp_path):
    monkeypatch.setenv("EPLAN_MCP_LOG_DIR", str(tmp_path))
    seen = {}
    monkeypatch.setattr(dialogs, "get_manager", lambda: _Mgr(connected=False))
    monkeypatch.setattr(dialogs, "eplan_pids", lambda: [3, 4])
    monkeypatch.setattr(dialogs.ui_windows, "click_button",
                        lambda h, b, t, pids, allow_any:
                        seen.update(pids=pids, any=allow_any, title=t) or {"success": True})
    dialogs.click_dialog_button(1, "OK", window_title="x", allow_any_button=True)
    assert seen == {"pids": {3, 4}, "any": True, "title": "x"}


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_enum_smoke_on_own_process():
    # _enum, not list_windows: list_windows swallows errors, so a broken ctypes
    # signature would pass silently there.
    assert isinstance(uw._enum({os.getpid()}), list)


def test_module_imports_without_winfunctype(monkeypatch):
    import ctypes
    import importlib
    monkeypatch.delattr(ctypes, "WINFUNCTYPE", raising=False)
    try:
        importlib.reload(uw)
    finally:
        monkeypatch.undo()
        importlib.reload(uw)
