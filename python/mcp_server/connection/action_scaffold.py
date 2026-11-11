"""The generated quiet-mode C# wrapper that runs an action and reports back."""

import json
import os
import re
import time
import uuid
from typing import Optional

from cs_json import prepare_script
from connection.logs import logger
from connection.shaping import MESSAGE_SCAN_CAP, carry_hang_note


def cs_escape(value) -> str:
    """Escape a value for safe embedding inside a C# regular string literal ("...").

    Handles backslash, double-quote, newlines/tabs and other control
    characters. This is the single defense against C# injection and against
    uncompilable scripts when action parameters, part numbers, setting
    paths, or supplier-supplied values contain quotes/backslashes/newlines.
    Returns the inner content only (no surrounding quotes).
    """
    if value is None:
        return ""
    out = []
    for ch in str(value):
        codepoint = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif codepoint < 0x20 or codepoint in (0x85, 0x2028, 0x2029):
            # Control chars, plus NEL/LS/PS which C# treats as line
            # terminators even inside a regular string literal.
            out.append("\\u%04x" % codepoint)
        else:
            out.append(ch)
    return "".join(out)


# How long to wait for a generated script's result file before declaring that
# the action did not run. EPLAN's ExecuteScript is synchronous on this path, so
# a slow action still writes its result before returning - meaning this
# expiring points at the script never having run (usually a compile error),
# not at a slow action. A module constant so tests can shorten it without
# patching the clock: eplan_connection.time is the shared time module, and
# monkeypatching its sleep/time affects pytest itself.
SCRIPT_RESULT_TIMEOUT_S = 30.0


class ScaffoldMixin:
    def execute_action(self, action: str, quiet_mode: bool = False, label: str = None,
                       timeout: float = None) -> dict:
        """
        Execute an EPLAN action.

        Args:
            action: The action string to execute
            quiet_mode: If True, suppresses all EPLAN dialogs during execution using a C# script.
            timeout: Seconds to allow the remote call when longer than
                ACTION_TIMEOUT_S (direct calls only).
        """
        if not self.connected or not self.client:
            return {"success": False, "message": "Not connected"}

        started = time.time()
        try:
            # Parse the action name (first word before any space or '/')
            action_name_match = re.match(r'^([^\s/]+)', action)
            action_name = action_name_match.group(1) if action_name_match else action
            action_name_lower = action_name.lower()

            # RegisterScript, ExecuteScript, and UnregisterScript MUST run directly
            # to avoid infinite recursion. Also run directly if quiet_mode is False.
            if action_name_lower in ("registerscript", "executescript", "unregisterscript") or not quiet_mode:
                logger.info(f"Executing directly: {action}")
                self.client.SynchronousMode = True
                result, hung_s = self._bounded_execute(action, label, timeout)
                if result is None:
                    result = self._with_hang_note(
                        {"success": True, "message": f"Executed directly: {action}", "action": action},
                        hung_s)
                # Script plumbing (register/execute/unregister) is logged only
                # as part of the wrapped action, not as separate entries.
                if action_name_lower not in ("registerscript", "executescript", "unregisterscript"):
                    self._log_action(action, result, started)
                return result

            # Parse parameters
            params = {}
            matches = re.finditer(r'/([a-zA-Z0-9_]+):(?:("([^"]*)"|([^\s]*)))', action)
            for m in matches:
                key = m.group(1)
                val = m.group(3) if m.group(2).startswith('"') else m.group(4)
                params[key] = val

            # Generate directories
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script_dir = os.path.join(base_dir, "scripts", "generated")
            results_dir = os.path.join(base_dir, "scripts", "results")
            os.makedirs(script_dir, exist_ok=True)
            os.makedirs(results_dir, exist_ok=True)

            exec_id = str(uuid.uuid4())[:8]
            script_path = os.path.join(script_dir, f"exec_action_{exec_id}.cs")
            result_path = os.path.join(results_dir, f"exec_result_{exec_id}.json")

            # C# parameters generation. Keys are constrained to
            # [a-zA-Z0-9_]+ by the parse regex above; values are cs_escape'd
            # to prevent injection / uncompilable scripts.
            acc_parameters_code = ""
            check_keys = ["PROJECT", "PROJECTS", "PAGES", "LAYOUTSPACES", "PropertyValue", "value", "Value", "Result", "Output", "Success", "Count", "Error", "Message"]
            for key, val in params.items():
                acc_parameters_code += f'\n                acc.AddParameter("{key}", "{cs_escape(val)}");'
                if key not in check_keys:
                    check_keys.append(key)

            check_keys_code = ", ".join([f'"{k}"' for k in check_keys])
            escaped_result_path = result_path.replace("\\", "\\\\")
            escaped_action_name = cs_escape(action_name)
            raw_scan_cap = MESSAGE_SCAN_CAP

            # Escape hatch: EPLAN_MCP_LEGACY_CLI=1 emits the original
            # CommandLineInterpreter-only template (no FindAction, no message
            # capture) as a known-good fallback in case the enhanced template
            # fails to compile on some EPLAN version.
            if os.environ.get("EPLAN_MCP_LEGACY_CLI") == "1":
                script_content = self._legacy_script_content(
                    exec_id, acc_parameters_code, check_keys_code,
                    escaped_result_path, escaped_action_name,
                )
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(prepare_script(script_content, self.target_version))
                return self._run_generated_script(action, script_path, result_path, started)

            # C# Script Content.
            # Executor strategy (Audit/TODO.md item 1): resolve the action via
            # ActionManager.FindAction and run Action.Execute, which lets real
            # EPLAN exceptions propagate to our catch block — unlike
            # CommandLineInterpreter.Execute, which swallows them and returns
            # only false. CLI remains as fallback for unresolvable actions.
            # A message-tree bookmark taken before execution captures the
            # warnings/errors EPLAN emitted during the call even when no
            # exception is thrown (covers unreliable success:false results).
            script_content = f"""using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.Base;
using Eplan.EplApi.Scripting;

public class QuietExecute_{exec_id}
{{
    private static string ExceptionChain(Exception ex)
    {{
        var parts = new List<string>();
        while (ex != null)
        {{
            parts.Add(ex.Message);
            ex = ex.InnerException;
        }}
        return string.Join(" <- ", parts);
    }}

    [Start]
    public void Run()
    {{
        var results = new Dictionary<string, object>();
        int bookmark = 0;
        try
        {{
            using (var marker = new BaseException("MCP bookmark", MessageLevel.Message))
            {{
                bookmark = marker.GetBookmarkID();
            }}
        }}
        catch {{}}
        try
        {{
            using (var qm = new QuietModeStep(QuietModes.ShowNoDialogs))
            {{
                var acc = new ActionCallingContext();
                {acc_parameters_code}

                bool success;
                Eplan.EplApi.ApplicationFramework.Action eplanAction = null;
                try {{ eplanAction = new ActionManager().FindAction("{escaped_action_name}"); }}
                catch {{}}
                if (eplanAction != null)
                {{
                    results["executor"] = "action";
                    success = eplanAction.Execute(acc);
                }}
                else
                {{
                    results["executor"] = "cli-fallback";
                    var cli = new CommandLineInterpreter();
                    success = cli.Execute("{escaped_action_name}", acc);
                }}
                results["success"] = success;

                // The exception behind a silent success:false is already in
                // the context we are holding. The Action docs say exceptions
                // occurring during execution can be retrieved from the
                // ActionCallingContext via GetException(). Measured
                // 2026-09-03 on EPLAN 2027.0.1: after Action.Execute of
                // projectmanagement /TYPE:READPROJECTINFO with PROJECTNAME
                // omitted, this returns EPLAN's own no-file-found text
                // naming the FILENAME parameter, as a BaseException.
                //
                // Read AFTER the single execution and never by re-running the
                // action: success:false does not mean nothing happened
                // (restore_masterdata overwrote a folder and took sibling
                // files with it while reporting false), so harvesting a
                // message by retrying could repeat a side effect.
                try
                {{
                    var ctxEx = acc.GetException();
                    if (ctxEx != null)
                    {{
                        results["error"] = ctxEx.Message;
                        results["errorType"] = ctxEx.GetType().FullName;
                        results["errorFrom"] = "context";
                    }}
                }}
                catch {{}}

                // ActionCallingContext.SysMessages is a per-call collection,
                // scoped by construction rather than by bookmarking the global
                // tree. Measured populated on the Action.Execute path WITHOUT
                // CommandLineInterpreter's bCollectSysMessages flag, which is
                // undocumented. Collected as a second source and merged with
                // the bookmark slice below rather than replacing it: it has
                // been compared on two actions only, so this widens coverage
                // without betting the existing channel on a small sample.
                try
                {{
                    var ctxMsgs = acc.SysMessages;
                    if (ctxMsgs != null)
                    {{
                        var craw = new List<Dictionary<string, string>>();
                        var cit = ctxMsgs.GetSysMsgEnumerator();
                        int cscanned = 0;
                        while (cit.MoveNext() && cscanned < {raw_scan_cap})
                        {{
                            var cm = cit.Current as BaseException;
                            if (cm != null && !string.IsNullOrEmpty(cm.Message))
                            {{
                                var crec = new Dictionary<string, string>();
                                crec["text"] = cm.Message;
                                try {{ crec["level"] = cm.MessageLevel.ToString(); }}
                                catch {{ crec["level"] = ""; }}
                                craw.Add(crec);
                                cscanned++;
                            }}
                        }}
                        if (craw.Count > 0)
                        {{
                            results["eplanContextMessagesRaw"] = craw;
                        }}
                    }}
                }}
                catch {{}}

                var returnParams = new Dictionary<string, string>();
                string[] checkKeys = new string[] {{ {check_keys_code} }};
                foreach (var key in checkKeys)
                {{
                    try
                    {{
                        string val = "";
                        acc.GetParameter(key, ref val);
                        if (!string.IsNullOrEmpty(val))
                        {{
                            returnParams[key] = val;
                        }}
                    }}
                    catch {{}}
                }}
                results["parameters"] = returnParams;
            }}
        }}
        catch (Exception ex)
        {{
            results["success"] = false;
            results["error"] = ExceptionChain(ex);
            results["errorType"] = ex.GetType().FullName;
            // Provenance matters for auditing: errorType was absent from all
            // 1,463 logged actions before this change, so when it starts
            // appearing we need to know which channel produced it.
            results["errorFrom"] = "throw";
        }}

        // Close the slice at the top. With only a start bookmark the
        // collection is open-ended, so anything EPLAN emits after this action
        // - including from a later action in the same session - lands in it.
        int bookmarkEnd = 0;
        try
        {{
            using (var endMarker = new BaseException("MCP bookmark end", MessageLevel.Message))
            {{
                bookmarkEnd = endMarker.GetBookmarkID();
            }}
        }}
        catch {{}}

        // Collect system messages emitted during this action (bounded slice
        // only - never the whole historical tree).
        if (bookmark > 0)
        {{
            try
            {{
                // Collect text AND severity, and count everything seen. The
                // ranking and the cap are applied on the Python side, so the
                // policy is unit-testable without string-matching generated
                // C# - in the one file where a typo mutes all ~180 tools.
                var raw = new List<Dictionary<string, string>>();
                // Three-arg ctor (start, end, level) bounds the slice at both
                // ends; fall back to the open-ended two-arg one only if the
                // end bookmark could not be taken.
                SysMessagesCollection col;
                if (bookmarkEnd > bookmark)
                {{
                    col = new SysMessagesCollection(bookmark, bookmarkEnd, MessageLevel.Message);
                    results["eplanMessagesBounded"] = true;
                }}
                else
                {{
                    col = new SysMessagesCollection(bookmark, MessageLevel.Message);
                    results["eplanMessagesBounded"] = false;
                }}
                // Count is the collection's OWN total, so truncation is
                // reported exactly rather than inferred from how many entries
                // we managed to walk.
                try {{ results["eplanMessagesTrueTotal"] = col.Count; }} catch {{}}
                var it = col.GetSysMsgEnumerator();
                int scanned = 0;
                while (it.MoveNext() && scanned < {raw_scan_cap})
                {{
                    // SysMessagesEnumerator.Current is typed object - it must
                    // be cast before .Message is reachable, or the generated
                    // script fails to compile and every action breaks.
                    var m = it.Current as BaseException;
                    if (m != null && !string.IsNullOrEmpty(m.Message)
                        && m.Message != "MCP bookmark"
                        && m.Message != "MCP bookmark end")
                    {{
                        var rec = new Dictionary<string, string>();
                        rec["text"] = m.Message;
                        // Use MessageLevel. The shorter "Level" property does
                        // not exist and raises CS1061, which breaks every
                        // action - verified live 2026-09-01. ToString() rather
                        // than an enum member, so a renamed member cannot
                        // become a CS0117 at generation time. (Written without
                        // the forbidden spelling on purpose: a test greps the
                        // generated source for it.)
                        try {{ rec["level"] = m.MessageLevel.ToString(); }}
                        catch {{ rec["level"] = ""; }}
                        raw.Add(rec);
                        scanned++;
                    }}
                }}
                if (raw.Count > 0)
                {{
                    results["eplanMessagesRaw"] = raw;
                    results["eplanMessagesScanned"] = raw.Count;
                }}
            }}
            catch {{}}
        }}

        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results);
        File.WriteAllText("{escaped_result_path}", json);
    }}
}}
"""
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(prepare_script(script_content, self.target_version))
            return self._run_generated_script(action, script_path, result_path, started)

        except Exception as e:
            self.last_error = f"Scripted execution failed: {e}"
            logger.error(self.last_error)
            result = {"success": False, "message": self.last_error, "action": action}
            self._log_action(action, result, started)
            return result

    def _legacy_script_content(self, exec_id, acc_parameters_code, check_keys_code,
                               escaped_result_path, escaped_action_name) -> str:
        """Original CommandLineInterpreter-only template (EPLAN_MCP_LEGACY_CLI=1).

        Known-good fallback: no FindAction, no message-tree capture, so it
        cannot be broken by a message-API mismatch on some EPLAN version.
        It swallows EPLAN exceptions (returns only a bool) - the trade-off
        the escape hatch accepts for maximum compatibility.
        """
        return f"""using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.Scripting;

public class QuietExecute_{exec_id}
{{
    [Start]
    public void Run()
    {{
        var results = new Dictionary<string, object>();
        try
        {{
            using (var qm = new QuietModeStep(QuietModes.ShowNoDialogs))
            {{
                var acc = new ActionCallingContext();
                {acc_parameters_code}

                results["executor"] = "cli-legacy";
                var cli = new CommandLineInterpreter();
                bool success = cli.Execute("{escaped_action_name}", acc);
                results["success"] = success;

                var returnParams = new Dictionary<string, string>();
                string[] checkKeys = new string[] {{ {check_keys_code} }};
                foreach (var key in checkKeys)
                {{
                    try
                    {{
                        string val = "";
                        acc.GetParameter(key, ref val);
                        if (!string.IsNullOrEmpty(val))
                        {{
                            returnParams[key] = val;
                        }}
                    }}
                    catch {{}}
                }}
                results["parameters"] = returnParams;
            }}
        }}
        catch (Exception ex)
        {{
            results["success"] = false;
            results["error"] = ex.Message;
        }}

        string json = Newtonsoft.Json.JsonConvert.SerializeObject(results);
        File.WriteAllText("{escaped_result_path}", json);
    }}
}}
"""

    def _preserve_failed_script(self, script_path: str) -> Optional[str]:
        """Copy a generated script aside before the cleanup deletes it.

        When no result file appears the generated C# is the only evidence of
        why, and the `finally` below removes it - which is what made commit
        21d10d4d6 (a CS1061 that broke every wrapped action) expensive to
        diagnose. Returns the preserved path, or None if it could not be kept;
        never raises, because this runs on an error path.
        """
        try:
            dest_dir = os.path.join(self._log_dir(), "failed_scripts")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(script_path))
            with open(script_path, "r", encoding="utf-8") as src:
                content = src.read()
            with open(dest, "w", encoding="utf-8") as out:
                out.write(content)
            return dest
        except Exception:
            return None

    def _script_failure(self, action, script_path, started, error_type, error, message):
        """Build, log and return a 'the action did not run' result.

        The three no-result paths below all used to return a bare `message`,
        which reads to a caller exactly like a slow action that eventually
        worked. Each now carries errorType plus executor="none", so the model
        can tell "EPLAN ran this and it failed" from "this never reached
        EPLAN", and stop retrying in the second case.
        """
        result = {
            "success": False,
            "executor": "none",
            "errorType": error_type,
            "error": error,
            "message": message,
            "action": action,
        }
        preserved = self._preserve_failed_script(script_path)
        if preserved:
            result["failedScriptPath"] = preserved
        self._log_action(action, result, started)
        return result

    def _run_generated_script(self, action, script_path, result_path, started) -> dict:
        """Execute a generated [Start] script, await the result file, clean up."""
        try:
            logger.info(f"Wrapping action via script: {action} (script={os.path.basename(script_path)})")
            # Execute only - deliberately NOT RegisterScript first. The wrapper
            # script generated above has only a [Start] method; RegisterScript is
            # for persistent [DeclareAction]/[DeclareEventHandler]/[DeclareMenu]
            # hooks, and ExecuteScript compiles and runs [Start] on its own.
            # Registering it only makes EPLAN report "The script does not
            # contain attributes for loading." (in its UI, not in the API
            # result) and costs two extra round-trips per action. Under
            # QuietMode - the whole point of this path - that is an error the
            # caller cannot even see. See scripted.py.
            # label: a later EplanBusy names the real action, not the temp script.
            exec_result = self.execute_action(f'ExecuteScript /ScriptFile:"{script_path}"',
                                              quiet_mode=False, label=action)
            if str(exec_result.get("errorType", "")).startswith("Eplan"):
                # A typed EPLAN failure (dialog, timeout, busy, dead) is not a
                # plumbing fault; pass it through so its next_step survives.
                exec_result["action"] = action
                self._log_action(action, exec_result, started)
                return exec_result
            if not exec_result.get("success"):
                return self._script_failure(
                    action, script_path, started,
                    "McpScriptExecuteFailed",
                    "EPLAN refused to run the generated wrapper script, so the "
                    "action did NOT execute. This is a fault in this MCP "
                    "server's script plumbing, not in the action or its "
                    "parameters - do not retry with different parameters. "
                    "Underlying ExecuteScript result: %s"
                    % exec_result.get("message"),
                    "Failed to execute action via script: %s"
                    % exec_result.get("message"),
                )

            # Wait for result file
            timeout = SCRIPT_RESULT_TIMEOUT_S
            start_time = time.time()
            while not os.path.exists(result_path):
                if time.time() - start_time > timeout:
                    return self._script_failure(
                        action, script_path, started,
                        "McpScriptNoResult",
                        "The action did NOT run: the generated wrapper script "
                        "produced no result file within %gs. This is NOT a "
                        "timeout on a slow action - EPLAN's ExecuteScript is "
                        "synchronous here, so a slow action would still have "
                        "written its result before returning. The usual cause "
                        "is that the generated C# failed to compile, which "
                        "affects every wrapped action equally rather than just "
                        "this one. The script has been preserved at "
                        "failedScriptPath; check eplan_get_system_messages for "
                        "a compiler error." % timeout,
                        "Timeout waiting for scripted action execution result",
                    )
                time.sleep(0.1)

            # Read results, tolerating a partially-written file (the C# writer
            # is not atomic vs our existence probe).
            res_data = None
            for attempt in range(10):
                if attempt:
                    time.sleep(0.05)
                try:
                    with open(result_path, "r", encoding="utf-8") as f:
                        res_data = json.load(f)
                    break
                except (json.JSONDecodeError, ValueError):
                    continue
            if res_data is None:
                return self._script_failure(
                    action, script_path, started,
                    "McpScriptBadResult",
                    "The action may or may not have run: a result file appeared "
                    "but never became valid JSON. Unlike McpScriptNoResult the "
                    "script did reach its write, so treat any side effect of "
                    "this action as possibly applied and verify before "
                    "retrying. The script has been preserved at "
                    "failedScriptPath.",
                    "Could not parse action result file",
                )

            # The hang seen by the inner ExecuteScript call belongs to this action.
            res_data = carry_hang_note(exec_result, self._shape_messages(res_data))
            self._log_action(action, res_data, started)
            return res_data

        except Exception as e:
            self.last_error = f"Scripted execution failed: {e}"
            logger.error(self.last_error)
            result = {"success": False, "message": self.last_error, "action": action}
            self._log_action(action, result, started)
            return result

        finally:
            try:
                if os.path.exists(script_path):
                    # No UnregisterScript - nothing was registered (see above).
                    os.remove(script_path)
            except Exception:
                pass
            try:
                if os.path.exists(result_path):
                    os.remove(result_path)
            except Exception:
                pass
