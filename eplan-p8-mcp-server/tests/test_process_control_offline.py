"""Windows process ownership/handle tests; never opens or terminates a real process."""
import ctypes
import os
import socket
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import process_control as control


@pytest.mark.parametrize("listeners,expected", [
    ([("0.0.0.0", 49152, 123)], 123),
    ([("::", 49152, 123), ("0.0.0.0", 49152, 123)], 123),
    ([("0.0.0.0", 49153, 123)], None),
    ([], None),
    ([("127.0.0.1", 49152, 123), ("::1", 49152, 456)], None),
])
def test_listener_requires_unique_owner(monkeypatch, listeners, expected):
    monkeypatch.setattr(control, "tcp_listeners", Mock(return_value=listeners))
    if expected is None:
        with pytest.raises(RuntimeError):
            control._listener_pid("49152")
    else:
        assert control._listener_pid("49152") == expected


def test_listener_query_failure_is_not_empty_success(monkeypatch):
    monkeypatch.setattr(control, "tcp_listeners", Mock(side_effect=OSError("query failed")))
    with pytest.raises(OSError):
        control._listener_pid(49152)


def _row4(state, local, port, pid):
    return (state.to_bytes(4, "little") + socket.inet_aton(local) + port.to_bytes(2, "big")
            + b"\0\0" + socket.inet_aton("0.0.0.0") + b"\0" * 4 + pid.to_bytes(4, "little"))


def _row6(local, port, pid):
    return (socket.inet_pton(socket.AF_INET6, local) + b"\0" * 4 + port.to_bytes(2, "big")
            + b"\0\0" + b"\0" * 16 + b"\0" * 8 + (2).to_bytes(4, "little") + pid.to_bytes(4, "little"))


def test_parse_tcp_table_ipv4_rows():
    raw = (2).to_bytes(4, "little") + _row4(2, "0.0.0.0", 49152, 45472) + _row4(2, "127.0.0.1", 135, 7)
    assert control.parse_tcp_table(raw, control._AF_INET) == [
        ("0.0.0.0", 49152, 45472), ("127.0.0.1", 135, 7)]


def test_parse_tcp_table_ipv6_rows():
    raw = (1).to_bytes(4, "little") + _row6("::1", 49153, 45472)
    assert control.parse_tcp_table(raw, control._AF_INET6) == [("::1", 49153, 45472)]


@pytest.mark.skipif(os.name != "nt", reason="reads the real Windows TCP table")
@pytest.mark.parametrize("family,host", [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")])
def test_tcp_listeners_sees_a_real_listening_socket(family, host):
    with socket.socket(family, socket.SOCK_STREAM) as server:
        server.bind((host, 0))
        server.listen()
        port = server.getsockname()[1]
        assert (host, port, os.getpid()) in control.tcp_listeners()
    assert not any(p == port and pid == os.getpid() for _a, p, pid in control.tcp_listeners())


@pytest.mark.skipif(os.name != "nt", reason="reads the real Windows process list")
def test_process_ids_finds_this_python():
    import sys
    name = os.path.basename(sys.executable)
    assert os.getpid() in control.process_ids(name.upper())
    assert control.process_ids("no-such-program-here.exe") == []


def test_remote_target_never_looks_at_local_processes(monkeypatch):
    lookup = Mock(side_effect=AssertionError("local lookup"))
    monkeypatch.setattr(control, "_listener_pid", lookup)
    with pytest.raises(RuntimeError, match="Remote"):
        control.connected_process("remote-workstation", 49152, True)
    lookup.assert_not_called()


def test_changed_owner_releases_handle(monkeypatch):
    process = SimpleNamespace(wait=Mock(return_value=False), close=Mock())
    monkeypatch.setattr(control, "_listener_pid", Mock(side_effect=[123, 456]))
    monkeypatch.setattr(control, "WindowsProcess", Mock(return_value=process))
    with pytest.raises(RuntimeError, match="changed"):
        control.connected_process("localhost", 49152)
    process.close.assert_called_once()


@pytest.fixture
def api(monkeypatch):
    def image_name(handle, flags, path, size):
        path.value = "C:/EPLAN/EPLAN.exe"
        return True
    api = SimpleNamespace(OpenProcess=Mock(return_value=98765),
                          QueryFullProcessImageNameW=Mock(side_effect=image_name),
                          WaitForSingleObject=Mock(return_value=258),
                          TerminateProcess=Mock(return_value=True), CloseHandle=Mock(return_value=True))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: api, raising=False)
    return api


@pytest.mark.parametrize("force", [False, True])
def test_rights_and_operations_are_bound_to_original_handle(api, force):
    process = control.WindowsProcess(123, allow_terminate=force)
    assert api.OpenProcess.call_args.args == (0x101000 | int(force), False, 123)
    assert not process.wait(0)
    api.WaitForSingleObject.return_value = 0
    assert process.wait(1)
    if force:
        process.terminate()
        api.TerminateProcess.assert_called_once_with(98765, 1)
    process.close()
    process.close()
    api.CloseHandle.assert_called_once_with(98765)
    assert all(call.args[0] == 98765 for call in api.WaitForSingleObject.call_args_list)


def test_non_eplan_owner_is_rejected_and_handle_closed(api):
    def wrong_image(handle, flags, path, size):
        path.value = "C:/other.exe"
        return True
    api.QueryFullProcessImageNameW.side_effect = wrong_image
    with pytest.raises(RuntimeError, match="not EPLAN"):
        control.WindowsProcess(123, True)
    api.CloseHandle.assert_called_once_with(98765)
    api.TerminateProcess.assert_not_called()


def test_already_exited_process_is_rejected(api):
    api.WaitForSingleObject.return_value = 0
    with pytest.raises(RuntimeError, match="already exited"):
        control.WindowsProcess(123)
    api.CloseHandle.assert_called_once_with(98765)
