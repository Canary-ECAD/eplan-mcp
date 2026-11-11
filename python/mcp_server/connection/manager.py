"""EPLANConnectionManager: the Remote Client connection, composed from the
connection package's mixins."""

import re
import threading
import time

from connection.action_scaffold import ScaffoldMixin
from connection.clr_bootstrap import ClrBootstrapMixin
from connection.dialogs import DialogMixin
from connection.logs import LogMixin, logger
from connection.processes import (
    _STATE_WORDS,
    _blocking_dialogs,
    eplan_listening_ports,
    eplan_state,
    PID_SETTLE_S,
    pid_alive,
)
from connection.runner import RunnerMixin, call_with_timeout
from connection.shaping import ShapingMixin


class EPLANConnectionManager(ClrBootstrapMixin, RunnerMixin, DialogMixin,
                             ScaffoldMixin, ShapingMixin, LogMixin):
    """Manages the connection to EPLAN via Remote Client API."""

    DEFAULT_PORT = "49152"
    DEFAULT_HOST = "localhost"
    TIMEOUT_SECONDS = 10

    # Hosts treated as "this workstation". EPLAN remoting has no authentication,
    # so connecting anywhere else is a trust decision, not a configuration
    # detail: whoever runs that EPLAN sees every project this session touches
    # and every action it runs. Kept as a set so get_status() and the action
    # trace can both label the target.
    LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})

    def __init__(self, target_version: str = None):
        # target_version: EPLAN major version like "2026".
        # None = auto-detect (newest installed version).
        self.target_version = str(target_version) if target_version else None
        self.client = None
        self.connected = False
        self.pid = None         # EPLAN.exe behind the connection, when local
        # The connected EPLAN's own version, as server enumeration reported it
        # (e.g. "2027.0.3"), else the local listener's EPLAN.exe file version.
        # None when neither is known; target_version (the loaded DLLs) is the
        # fallback then.
        self.server_version = None
        self._inflight = None   # action string of a call still stuck in EPLAN
        self._inflight_since = 0.0
        self._not_responding_s = 0.0   # seen Not Responding during the last call
        self._recorded = set()  # (hwnd, title) of dialogs already in dialogs.jsonl
        # Tools run on worker threads, so two calls can overlap; this keeps the
        # in-flight check-and-set atomic and sends EPLAN one call at a time.
        # Waited on only briefly: a caller behind a long action gets EplanBusy.
        self._exec_lock = threading.Lock()
        self.host = self.DEFAULT_HOST
        self.port = self.DEFAULT_PORT
        self.last_error = ""
        # Lazy: DLLs load on first use so tools like eplan_versions can run
        # without committing this process to one version's .NET runtime.
        self._clr_initialized = False

    def get_active_servers(self) -> list:
        """Get active EPLAN servers on the local machine."""
        if not self._clr_initialized:
            self._clr_initialized = self._setup_api()
        if not self._clr_initialized:
            return []

        try:
            from Eplan.EplApi.RemoteClient import EplanRemoteClient, EplanServerData
            from System.Collections.Generic import List as NetList

            temp = EplanRemoteClient()
            # out parameter in pythonnet
            servers = NetList[EplanServerData]()
            _, timed_out, err = call_with_timeout(
                temp.GetActiveEplanServersOnLocalMachine, 10, servers)
            if err is not None:
                raise err
            if timed_out:
                raise TimeoutError("server enumeration did not answer within 10s")

            result = []
            for s in servers:
                result.append({
                    "version": str(s.EplanVersion),
                    "variant": str(s.EplanVariant),
                    "port": str(s.ServerPort)
                })
                logger.info(f"Found: EPLAN {s.EplanVersion} on port {s.ServerPort}")

            temp.Dispose()
            return result

        except Exception as e:
            self.last_error = f"Error getting servers: {e}"
            logger.error(self.last_error)
            return []

    def connect(self, host: str = None, port: str = None) -> dict:
        """Connect to an EPLAN instance."""
        if not self._clr_initialized:
            self._clr_initialized = self._setup_api()
        if not self._clr_initialized:
            return {"success": False, "message": self.last_error}

        host = host or self.DEFAULT_HOST

        try:
            from Eplan.EplApi.RemoteClient import EplanRemoteClient
            import System

            # Auto-detect port(s) if not specified. Server enumeration first;
            # if it comes back empty (it is unreliable right after EPLAN
            # starts), fall back to EPLAN.exe's actual listening ports from
            # Windows' TCP table, then the historical default as a last resort.
            # Each candidate is tried until one answers a Ping.
            server_version = None
            if port:
                candidates = [str(port)]
            else:
                servers = self.get_active_servers()
                if servers:
                    candidates = [servers[-1]["port"]]
                    server_version = servers[-1].get("version")
                    logger.info(f"Auto-detected port: {candidates[0]}")
                else:
                    candidates = (eplan_listening_ports() if host in ("localhost", "127.0.0.1")
                                  else []) or [self.DEFAULT_PORT]
                    logger.info(f"Server enumeration empty; trying ports: {candidates}")

            timeout = System.TimeSpan.FromSeconds(self.TIMEOUT_SECONDS)
            last_exc = None
            for candidate in candidates:
                # `client` is disposed on EVERY path except the one where it is
                # handed to self.client. Previously Dispose() ran only when
                # Connect succeeded AND Ping returned False, so the ordinary
                # wrong-port case - Connect throwing - dropped a CLR remoting
                # client (and its gRPC channel) undisposed. Across the reconnect
                # retries the docstrings encourage and repeated app_launch
                # cycles, those accumulate for the life of the MCP process.
                client = None
                keep = False
                try:
                    logger.info(f"Connecting to {host}:{candidate}...")
                    client = EplanRemoteClient()
                    client.Connect(host, candidate, timeout)
                    alive, timed_out, err = call_with_timeout(client.Ping, self.TIMEOUT_SECONDS)
                    if err is not None:
                        raise err
                    if timed_out:
                        raise TimeoutError(f"Ping on port {candidate} did not answer "
                                           f"within {self.TIMEOUT_SECONDS}s")
                    if alive:
                        self.client = client
                        self.host = host
                        self.port = candidate
                        self.connected = True
                        self._inflight = None
                        self.pid = None
                        self.server_version = server_version
                        if host in self.LOCAL_HOSTS:
                            try:
                                from process_control import _listener_pid, eplan_version
                                self.pid = _listener_pid(candidate)
                                # Enumeration was empty or the port was given:
                                # take the version from the listener's EPLAN.exe.
                                if not self.server_version:
                                    self.server_version = eplan_version(self.pid)
                            except Exception:
                                pass
                        keep = True
                        logger.info(f"Connected to EPLAN at {host}:{candidate}")
                        return {
                            "success": True,
                            "message": f"Connected to EPLAN at {host}:{candidate}",
                            "host": host,
                            "port": candidate
                        }
                except Exception as exc:
                    last_exc = exc
                finally:
                    if client is not None and not keep:
                        # Bounded: a client whose Ping hung can hang here too.
                        call_with_timeout(client.Dispose, 10)
            if last_exc is not None:
                raise last_exc
            return {"success": False, "message": "Connected but ping failed"}

        except Exception as e:
            self.last_error = f"Connection failed: {e}"
            logger.error(self.last_error)
            self.connected = False
            return {"success": False, "message": self.last_error}

    def ping(self, timeout_seconds: float = 15.0) -> dict:
        """
        Check if EPLAN is responding.

        Bounded on purpose. TIMEOUT_SECONDS applies to Connect() only - every
        other remoting call is an unbounded synchronous CLR call, so a wedged
        EPLAN turns the health check itself into a hang, and the one tool whose
        job is to answer "is it alive?" must always answer.
        """
        if not self.connected or not self.client:
            return {"alive": False, "message": "Not connected"}

        # A call still stuck in EPLAN: answer from Windows instead of adding a
        # Ping thread that would only queue behind it. A stuck Ping counts too.
        if self._inflight:
            busy = self._busy_failure("Ping")
            busy.pop("action", None)
            return dict(busy, alive=False)

        client = self.client

        def ping():
            try:
                return client.Ping()
            finally:
                if self.client is client and self._inflight == "Ping":
                    self._inflight = None

        alive, timed_out, error = call_with_timeout(ping, timeout_seconds)
        if timed_out:
            if not self._inflight:
                self._inflight, self._inflight_since = "Ping", time.monotonic()
            # Not marked disconnected: the client may still be valid and EPLAN
            # merely busy (a modal dialog, a long redraw). Saying so is more
            # useful than guessing either way.
            result = {"alive": False, "timed_out": True,
                      "message": f"EPLAN did not answer Ping within {timeout_seconds}s - "
                                 "it is running but not servicing remoting calls "
                                 "(a modal dialog or a long operation will do this)"}
            pids = self._watch_pids()
            dialogs = _blocking_dialogs(pids) if pids else []
            result["process_alive"] = pid_alive(self.pid) if self.pid else None
            result["eplan_state"] = eplan_state(pids)
            if not dialogs:
                result["message"] += _STATE_WORDS.get(result["eplan_state"], "")
            if result["process_alive"] is False:
                result["next_step"] = "EPLAN is no longer running: call eplan_app_launch."
            elif dialogs:
                result["dialogs"] = dialogs
                result["next_step"] = self._dialog_next_step(dialogs[0])
            elif self._inflight:
                result["next_step"] = self._stuck_next_step()
            else:
                result["next_step"] = ("Wait a few seconds and call eplan_ping again; if it "
                                       "stays silent, check eplan_list_dialogs.")
            if self._inflight:
                result["in_flight_action"] = self._inflight
            return result
        if error is not None:
            self.connected = False
            return {"alive": False, "message": f"Ping failed: {error}"}
        # A killed EPLAN answers Ping with a plain False, not an error.
        if not alive and self.pid and self.host in self.LOCAL_HOSTS and pid_alive(self.pid, PID_SETTLE_S) is False:
            self.connected = False
            return {"alive": False, "process_alive": False,
                    "message": f"EPLAN (pid {self.pid}) is no longer running",
                    "next_step": "EPLAN is no longer running: call eplan_app_launch."}
        return {
            "alive": bool(alive),
            "message": "EPLAN responding" if alive else "No response"
        }

    def eplan_major(self):
        """Major version of the EPLAN this server talks to (2027, 2026, 2 for
        2.9), or None when it cannot be told. The connected EPLAN's own
        version when known, else the loaded DLLs' version."""
        for raw in (self.server_version, self.target_version):
            m = re.match(r"\s*(\d+)", str(raw or ""))
            if m:
                return int(m.group(1))
        return None

    def disconnect(self) -> dict:
        """Disconnect from EPLAN."""
        try:
            if self.client:
                for name in ("Disconnect", "Dispose"):
                    _, timed_out, err = call_with_timeout(getattr(self.client, name), 10)
                    if err is not None:
                        raise err
                    if timed_out:
                        raise TimeoutError(f"EPLAN did not answer {name} within 10s")
            logger.info("Disconnected")
            return {"success": True, "message": "Disconnected"}
        except Exception as e:
            return {"success": False,
                    "message": f"Disconnect failed: {e}. The client was dropped anyway; "
                               "call eplan_connect to reconnect."}
        finally:
            # Always forget the client: a half-closed one is no use to anyone.
            self.client = None
            self.connected = False
            self.pid = None
            self.server_version = None
            self._inflight = None

    def get_status(self) -> dict:
        """
        Get current connection status.

        "host" is reported because EPLAN remoting is UNAUTHENTICATED and this
        manager is a process-wide singleton: once something retargets it at
        another machine, every later action runs there. Without the host in the
        status (and in the action trace) neither the user nor a post-incident
        reviewer could tell a session had left the workstation.
        """
        return {
            "connected": self.connected,
            "api_loaded": self._clr_initialized,
            "target_version": self.target_version,
            "server_version": self.server_version if self.connected else None,
            "host": self.host if self.connected else None,
            "is_local": (self.host in self.LOCAL_HOSTS) if self.connected else None,
            "port": self.port if self.connected else None,
            "last_error": self.last_error
        }
