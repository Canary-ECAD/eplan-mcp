"""Identify and control one local Windows EPLAN process without PID-reuse races.

Processes and listening ports are read from the Windows API, not from the text of
tasklist / netstat. Those tools print in the console's language and code page:
"Dirección local" in Spanish, "ABHÖREN" instead of LISTENING in German, and other
words and code pages in Japanese, Korean, Russian... Parsing that text found nothing
on non-English Windows, and decoding it raised UnicodeDecodeError when Python ran in
UTF-8 mode (PYTHONUTF8=1), as it does when an app embeds this server.
"""

import ctypes
import ntpath
import socket
from ctypes import wintypes

_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_AF_INET = 2
_AF_INET6 = 23
_TCP_TABLE_OWNER_PID_LISTENER = 3
_ERROR_INSUFFICIENT_BUFFER = 122


class _ProcessEntry(ctypes.Structure):
    """PROCESSENTRY32W."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def process_ids(image_name):
    """PIDs of the running processes whose executable is `image_name` (any case)."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        fn = getattr(api, name)
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        fn.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = api.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        pids = []
        more = api.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.lower() == image_name.lower():
                pids.append(entry.th32ProcessID)
            more = api.Process32NextW(snapshot, ctypes.byref(entry))
        return pids
    finally:
        api.CloseHandle(snapshot)


def parse_tcp_table(raw, family):
    """(address, port, pid) rows of a MIB_TCPTABLE_OWNER_PID (IPv4) or
    MIB_TCP6TABLE_OWNER_PID (IPv6) buffer, as GetExtendedTcpTable fills it.

    IPv4 rows are 24 bytes: state, local address, local port, remote address,
    remote port, owning PID. IPv6 rows are 56: local address (16), scope id,
    local port, remote address (16), scope id, remote port, state, owning PID.
    Ports are in network byte order in the low two bytes; the rest is native.
    """
    if family == _AF_INET:
        size, address, port_at, pid_at, af = 24, slice(4, 8), 8, 20, socket.AF_INET
    else:
        size, address, port_at, pid_at, af = 56, slice(0, 16), 20, 52, socket.AF_INET6
    count = int.from_bytes(raw[:4], "little")
    rows = []
    for i in range(count):
        row = raw[4 + i * size:4 + (i + 1) * size]
        rows.append((
            socket.inet_ntop(af, row[address]),
            int.from_bytes(row[port_at:port_at + 2], "big"),
            int.from_bytes(row[pid_at:pid_at + 4], "little"),
        ))
    return rows


def tcp_listeners():
    """(address, port, pid) of every listening TCP socket, IPv4 rows first."""
    api = ctypes.WinDLL("iphlpapi")
    get_table = api.GetExtendedTcpTable
    get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                          wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    get_table.restype = wintypes.DWORD
    listeners = []
    for family in (_AF_INET, _AF_INET6):
        size = wintypes.DWORD(0)
        # The first call reports the size; the table can grow before the next.
        for _ in range(5):
            buffer = ctypes.create_string_buffer(max(size.value, 4))
            status = get_table(buffer, ctypes.byref(size), False, family,
                               _TCP_TABLE_OWNER_PID_LISTENER, 0)
            if status != _ERROR_INSUFFICIENT_BUFFER:
                break
        if status != 0:
            raise ctypes.WinError(status)
        listeners.extend(parse_tcp_table(buffer.raw, family))
    return listeners


def _listener_pid(port):
    port = int(port)
    owners = {pid for _address, listening, pid in tcp_listeners() if listening == port}
    if len(owners) != 1:
        raise RuntimeError(f"Cannot identify a unique local process listening on port {port}.")
    return owners.pop()


class WindowsProcess:
    """A retained kernel handle identifies the process even after its PID is reused."""

    def __init__(self, pid, allow_terminate=False):
        self.pid = pid
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "QueryFullProcessImageNameW": ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, returns) in signatures.items():
            fn = getattr(self._api, name)
            fn.argtypes, fn.restype = args, returns
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, plus termination
        # rights only when explicitly requested by the caller.
        access = 0x00100000 | 0x1000 | (0x0001 if allow_terminate else 0)
        self._handle = self._api.OpenProcess(access, False, pid)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if not self._api.QueryFullProcessImageNameW(self._handle, 0, path, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            if ntpath.basename(path.value).lower() != "eplan.exe":
                raise RuntimeError("The listening process is not EPLAN.exe.")
            if self.wait(0):
                raise RuntimeError("The target process has already exited.")
        except Exception:
            self.close()
            raise

    def wait(self, seconds):
        status = self._api.WaitForSingleObject(self._handle, min(int(seconds * 1000), 0xFFFFFFFE))
        if status == 0:
            return True
        if status == 258:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self):
        if not self._api.TerminateProcess(self._handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self._handle:
            self._api.CloseHandle(self._handle)
            self._handle = None


def connected_process(host, port, allow_terminate=False):
    if str(host).lower() not in {"localhost", "127.0.0.1", "::1", ""}:
        raise RuntimeError("Remote process identity cannot be verified locally.")
    pid = _listener_pid(port)
    process = WindowsProcess(pid, allow_terminate=allow_terminate)
    try:
        if _listener_pid(port) != pid or process.wait(0):
            raise RuntimeError("Port owner changed while identifying the target process.")
    except Exception:
        process.close()
        raise
    return process
