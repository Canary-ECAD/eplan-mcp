"""EPLAN.exe processes, their listening ports and their windows.

The window probes are module functions so tests can replace them."""


EPLAN_EXE_NAME = "EPLAN.exe"


def eplan_pids() -> list:
    """PIDs of running EPLAN.exe processes (empty list on any error).

    Read from the Windows API, not tasklist, whose output is localized: see
    process_control."""
    try:
        from process_control import process_ids
        return process_ids(EPLAN_EXE_NAME)
    except Exception:
        return []


def pid_alive(pid):
    """True if `pid` is a running EPLAN.exe, False if it is not (exited, or the
    PID now belongs to another program), None if that cannot be told. Checked
    by process handle, not tasklist, whose failure would read as 'not running'."""
    try:
        from process_control import WindowsProcess
        WindowsProcess(pid).close()
        return True
    except RuntimeError:            # not EPLAN.exe, or already exited
        return False
    except OSError as e:            # 87: no such process
        if getattr(e, "winerror", None) == 87:
            return False
        # A just-killed EPLAN still held open elsewhere answers "access denied"
        # (5) or WinError 31; the process snapshot already leaves it out.
        try:
            from process_control import process_ids
            return False if pid not in process_ids(EPLAN_EXE_NAME) else None
        except Exception:
            return None
    except Exception:
        return None


def _blocking_dialogs(pids, windows=None, new_since=None) -> list:
    """Blocking windows owned by `pids` (or among `windows`, an _eplan_windows
    result already in hand); [] when none, or when ui_windows is missing or
    fails. new_since: hwnds open before the call (see ui_windows.is_blocking).
    Never raises. A module function so tests can replace it."""
    try:
        if windows is None:
            import ui_windows
            windows = ui_windows.list_windows(pids, new_since=new_since, blocking_only=True)
        return [w for w in windows if w["blocking"]]
    except Exception:
        return []


def _eplan_windows(pids, full=False, new_since=None) -> list:
    """Every non-main window owned by `pids`. Cheap by default: only windows
    that can be blocking have their controls read; full reads them all.
    [] on any failure. Never raises. A module function so tests can replace it."""
    try:
        import ui_windows
        return ui_windows.list_windows(pids, new_since=new_since, blocking_only=not full)
    except Exception:
        return []


def _eplan_hwnds(pids) -> set:
    """hwnds of every visible top-level window of `pids`, no control read.
    set() on any failure. Never raises. A module function so tests can replace it."""
    try:
        import ui_windows
        return ui_windows.top_hwnds(pids)
    except Exception:
        return set()


# Upstream's names for the two reads above, kept for callers outside the
# package (dataportal.py). Never raise.
def _top_hwnds(pids) -> set:
    return _eplan_hwnds(pids)


def _list_windows(pids, new_since=None) -> list:
    try:
        import ui_windows
        return ui_windows.list_windows(pids, new_since=new_since)
    except Exception:
        return []


def _responding(pids):
    """ui_windows.responding(pids); None when it cannot be told. Never raises.
    A module function so tests can replace it."""
    try:
        import ui_windows
        return ui_windows.responding(pids)
    except Exception:
        return None


def eplan_state(pids) -> str:
    """'responding', 'not_responding' (Windows' Not Responding flag) or 'unknown'."""
    r = _responding(pids) if pids else None
    return "unknown" if r is None else ("responding" if r else "not_responding")


# Said when EPLAN is silent and no dialog explains it. Not Responding is not a
# failure: heavy computations set it too, and usually clear it again.
_STATE_WORDS = {
    "not_responding": " EPLAN is frozen or computing heavily (Windows reports Not "
                      "Responding); a long operation may still finish.",
    "responding": " EPLAN is responsive but still working.",
}


def eplan_listening_ports(only_pids=None, pids=None) -> list:
    """TCP ports EPLAN.exe processes are listening on (Windows API, not netstat).

    Fallback discovery: GetActiveEplanServersOnLocalMachine is unreliable
    right after EPLAN (re)starts - it can return empty while the remoting
    port is already up and accepting connections (observed live 2026-08-20:
    fresh EPLAN 2027 listening on 49153, server enumeration empty). The
    remoting port is dynamic (49152 is only the usual first choice), so
    never assume the default - discover.

    Args:
        only_pids: If given, restrict results to ports owned by one of these
            PIDs (any iterable, coerced to a set). Used by app_launch to tell
            the instance it just started apart from one that was already
            running - see Audit #42 item 12.
        pids: Already-computed result of eplan_pids(). If given, skips the
            internal process snapshot.
    """
    pids = set(eplan_pids() if pids is None else pids)
    if not pids:
        return []
    if only_pids is not None:
        pids &= set(only_pids)
        if not pids:
            return []
    ports = []
    try:
        from process_control import tcp_listeners
        for _address, port, pid in tcp_listeners():
            if pid in pids and str(port) not in ports:
                ports.append(str(port))
    except Exception:
        pass
    return ports
