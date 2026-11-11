"""Logging setup and the actions.jsonl trace."""

import json
import logging
import os
import time

from connection.shaping import LOGGED_RESULT_KEYS


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EPLAN")


def _log_dir() -> str:
    """Directory for actions.jsonl.

    EPLAN_MCP_LOG_DIR overrides the default, matching the EPLAN_MCP_MODE /
    EPLAN_MCP_EXTENSIONS convention. Read per call rather than cached at
    import, so a test fixture can point it at a tmp_path.
    """
    override = os.environ.get("EPLAN_MCP_LOG_DIR")
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


class LogMixin:
    _log_dir = staticmethod(_log_dir)

    def _log_action(self, action: str, result: dict, started: float) -> None:
        """Append one JSON line per executed action to actions.jsonl.

        Persistent trace of what the LLM did in EPLAN (Audit/TODO.md item 2):
        survives the conversation and lets failures be correlated with what
        the user saw on screen. Never raises.

        Note that LOGGED_RESULT_KEYS is a filter, not documentation: a
        diagnostic field added to the result but not to that tuple is absent
        from the trace, and so cannot be measured in a later audit.
        """
        try:
            log_dir = self._log_dir()
            os.makedirs(log_dir, exist_ok=True)
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                # WHERE the action ran. Without this the trace for an action
                # against a remote, unauthenticated EPLAN is byte-identical to
                # one against localhost, so a reviewer cannot tell the session
                # ever left this workstation. Only recorded, never used to
                # decide anything.
                "host": self.host,
                "port": self.port,
                "action": action,
                "duration_s": round(time.time() - started, 3),
                "success": result.get("success"),
            }
            for key in LOGGED_RESULT_KEYS:
                if result.get(key):
                    entry[key] = result[key]
            with open(os.path.join(log_dir, "actions.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
