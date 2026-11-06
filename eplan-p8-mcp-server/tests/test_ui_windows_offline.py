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


def test_reads_never_raise_and_return_nothing_without_pids():
    assert uw.list_windows(set()) == []
    assert uw.list_windows({0}) == [] or isinstance(uw.list_windows({0}), list)
    assert isinstance(uw.top_hwnds({0}), set)


def test_click_refuses_a_window_that_is_not_there():
    result = uw.click_button(1, "OK", "Nope", {0})
    assert result["success"] is False
    assert result["errorType"] == "DialogNotFound"
    assert "eplan_list_dialogs" in result["next_step"]
