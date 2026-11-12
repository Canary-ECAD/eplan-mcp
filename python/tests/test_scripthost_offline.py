"""Offline tests for api/actions/scripthost.py and the scratch marker. No EPLAN: a fake manager
plays the host by writing the result file the real host would write."""

import json
import os

import pytest

from api.actions import fixtures, scripthost


class FakeManager:
    """Answers the two host calls the way the add-in or the bootstrap would."""

    def __init__(self, addin=True, result=None):
        self.addin = addin
        self.result = result or {"protocol": 1, "ok": True, "phase": "done", "result": 42}
        self.calls = []

    def execute_action(self, action, quiet_mode=True, **kwargs):
        self.calls.append((action, quiet_mode))
        if action.startswith("EplanMcp_"):
            if not self.addin:
                return {"success": False, "message": "action not found"}
            result_path = action.split('/result:"')[1].rstrip('"')
            if action.startswith("EplanMcp_Hello"):
                payload = {"protocol": 1, "core_version": scripthost.HOST_VERSION, "runtime": "addin"}
            else:
                req = json.load(open(action.split('/request:"')[1].split('"')[0], encoding="utf-8"))
                payload = dict(self.result, run_id=req["run_id"], runtime="addin",
                               approval_hash="ab" * 32, args_seen=req["args_canonical"])
            json.dump(payload, open(result_path, "w", encoding="utf-8"))
            return {"success": True}
        if action.startswith("ExecuteScript"):
            script = action.split('/ScriptFile:"')[1].rstrip('"')
            text = open(script, encoding="utf-8").read()
            result_path = text.split('string resultPath = @"')[1].split('";')[0].replace('""', '"')
            json.dump({"protocol": 1, "core_version": scripthost.HOST_VERSION, "runtime": "bootstrap", "ok": True,
                       "phase": "done"}, open(result_path, "w", encoding="utf-8"))
            return {"success": True}
        raise AssertionError("unexpected action " + action)


@pytest.fixture(autouse=True)
def _eplan_2027(monkeypatch):
    """These tests play a .NET 8 EPLAN; the machine running them may have only 2026 installed."""
    monkeypatch.setattr(scripthost, "_unsupported_eplan", lambda: None)


@pytest.fixture
def host(tmp_path, monkeypatch):
    host_dir = tmp_path / "host"
    (host_dir / "Bootstrap").mkdir(parents=True)
    template = os.path.join(scripthost.DOTNET_DIR, "src", "EplanMcp.Scripting", "Bootstrap", "bootstrap.cs.template")
    (host_dir / "Bootstrap" / "bootstrap.cs.template").write_text(open(template, encoding="utf-8").read(), encoding="utf-8")
    (host_dir / "eplanmcp-version.txt").write_text(scripthost.HOST_VERSION)
    monkeypatch.setattr(scripthost, "HOST_DIR", str(host_dir))
    monkeypatch.setattr(scripthost, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(scripthost, "_addin_ok", None)
    monkeypatch.setattr(scripthost, "_offline_last_pid", None)
    scripthost._jobs.clear()
    return host_dir


def use(monkeypatch, manager):
    monkeypatch.setattr(scripthost, "_get_connected_manager", lambda: (manager, None))
    return manager


def test_run_uses_addin_on_the_direct_path(host, monkeypatch):
    m = use(monkeypatch, FakeManager(addin=True))
    out = scripthost.script_run(code="return 42;")
    assert out["success"] is True and out["state"] == "done" and out["result"] == 42
    run_calls = [c for c in m.calls if c[0].startswith("EplanMcp_RunScript")]
    assert run_calls and run_calls[0][1] is False      # quiet_mode False = direct path


def test_request_file_carries_the_contract(host, monkeypatch):
    use(monkeypatch, FakeManager())
    out = scripthost.script_run(code="return 1;", args={"page": "=A/1"}, project="x.elk", budget_seconds=5)
    req = json.load(open(os.path.join(os.path.dirname(out_path(out)), "request.json"), encoding="utf-8"))
    assert req["protocol"] == scripthost.PROTOCOL
    assert req["args"] == {"page": "=A/1"} and req["project"] == "x.elk" and req["budget_seconds"] == 5
    assert req["source_name"] == "snippet.cs" and req["script_path"] is None


def out_path(out):
    return scripthost._jobs[out["run_id"]]["result_path"]


@pytest.mark.parametrize("pinned, given, expected", [
    ("C:/scratch/target.elk", None, "C:/scratch/target.elk"),    # no project: the target
    ("C:/scratch/target.elk", "x.elk", "x.elk"),                  # an explicit project wins
    ("", None, None),                                             # no target: host picks
])
def test_a_run_without_a_project_goes_to_the_target_project(host, monkeypatch, pinned, given, expected):
    from api.actions import target
    monkeypatch.setattr(target, "_target", pinned)
    use(monkeypatch, FakeManager())
    out = scripthost.script_run(code="return 1;", project=given)
    req = json.load(open(os.path.join(os.path.dirname(out_path(out)), "request.json"), encoding="utf-8"))
    assert req["project"] == expected


def test_hello_names_the_target_project(host, monkeypatch):
    from api.actions import target
    use(monkeypatch, FakeManager())
    monkeypatch.setattr(target, "_target", "C:/scratch/target.elk")
    assert scripthost.script_hello("addin")["target_project"] == "C:/scratch/target.elk"
    monkeypatch.setattr(target, "_target", "")
    assert "target_project" not in scripthost.script_hello("addin")


def test_a_script_that_refuses_is_not_a_success(host, monkeypatch):
    use(monkeypatch, FakeManager(addin=True, result={
        "protocol": 1, "ok": True, "phase": "done",
        "result": {"matched": 9, "error": "9 lines and arcs match, more than limit=5. Nothing was written."}}))
    out = scripthost.script_run(code="return 1;")
    assert out["success"] is False and out["state"] == "done"
    assert "more than limit" in out["error"]
    use(monkeypatch, FakeManager(addin=True, result={
        "protocol": 1, "ok": True, "phase": "done", "result": {"error": None, "changed": 2}}))
    assert scripthost.script_run(code="return 1;")["success"] is True


def test_falls_back_to_bootstrap_when_addin_missing(host, monkeypatch):
    m = use(monkeypatch, FakeManager(addin=False))
    out = scripthost.script_run(code="return 1;")
    assert out["success"] is True and out["runtime"] == "bootstrap"
    script = [c[0] for c in m.calls if c[0].startswith("ExecuteScript")][0].split('"')[1]
    text = open(script, encoding="utf-8").read()
    assert "{{" not in text and str(host) in text


def test_bootstrap_escapes_quotes_in_paths(host, monkeypatch):
    folder = host / "run"
    folder.mkdir()
    path = scripthost._bootstrap_script(str(folder), "run", 'C:\\a"b\\req.json', 'C:\\a"b\\res.json')
    text = open(path, encoding="utf-8").read()
    assert '@"C:\\a""b\\req.json"' in text


def test_real_project_write_needs_saved_script_and_confirm(host, monkeypatch):
    use(monkeypatch, FakeManager())
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_DIRS", str(host))
    monkeypatch.setenv(scripthost.REAL_PROJECT_SWITCH, "1")
    out = scripthost.script_run(code="return 1;", allow_real_project=True)
    assert out["success"] is False and "saved script" in out["error"]

    script = host / "w.cs"
    script.write_text("// @writes true\nreturn 1;", encoding="utf-8")
    out = scripthost.script_run(script=str(script), allow_real_project=True, confirm="nope")
    assert out["success"] is False and "confirm" in out["error"]

    ok = scripthost.script_run(script=str(script), compile_only=True)
    assert len(ok["confirm_code"]) == 16
    assert ok["confirm_code"] == "ab" * 8
    out = scripthost.script_run(script=str(script), allow_real_project=True, confirm=ok["confirm_code"])
    assert out["success"] is True


def test_args_are_sent_canonically(host, monkeypatch):
    use(monkeypatch, FakeManager())
    out = scripthost.script_run(code="return 1;", args={"b": 1, "a": "x"})
    assert out["args_seen"] == '{"a":"x","b":1}'


def test_exactly_one_of_code_or_script(host, monkeypatch):
    use(monkeypatch, FakeManager())
    assert scripthost.script_run()["success"] is False
    assert scripthost.script_run(code="x", script="y")["success"] is False


def test_long_run_returns_run_id_then_status(host, monkeypatch):
    import threading
    gate = threading.Event()

    class Slow(FakeManager):
        def execute_action(self, action, quiet_mode=True, **kwargs):
            if action.startswith("EplanMcp_RunScript"):
                gate.wait(5)
            return super().execute_action(action, quiet_mode, **kwargs)

    use(monkeypatch, Slow())
    out = scripthost.script_run(code="return 1;", wait_seconds=0.1)
    assert out["state"] == "running"
    busy = scripthost.script_run(code="return 2;")
    assert busy["success"] is False and "still running" in busy["error"]
    assert scripthost.script_cancel(out["run_id"])["success"] is True
    gate.set()
    scripthost._jobs[out["run_id"]]["thread"].join(5)
    assert scripthost.script_status(out["run_id"])["state"] == "done"


def test_no_result_file_is_reported_plainly(host, monkeypatch):
    class Silent(FakeManager):
        def execute_action(self, action, quiet_mode=True, **kwargs):
            if action.startswith("EplanMcp_RunScript"):
                return {"success": True}     # EPLAN "succeeded" but nothing ran
            return super().execute_action(action, quiet_mode, **kwargs)

    use(monkeypatch, Silent())
    out = scripthost.script_run(code="return 1;")
    assert out["success"] is False and "wrote no result" in out["error"]


def test_script_list_reads_headers(host, monkeypatch, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "a.cs").write_text("// @tool  alpha\n// @desc  Does A.\n// @writes true\n// @arg x string\nreturn 1;")
    (lib / "_template.cs").write_text("// @tool skip_me\n")
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_DIRS", str(lib))
    listed = {s["tool"]: s for s in scripthost.script_list()["scripts"]}
    assert listed["alpha"]["writes"] is True and listed["alpha"]["desc"] == "Does A."
    assert "skip_me" not in listed
    assert "project_info" in listed            # the public library ships with the repo
    path, source = scripthost._resolve_script("alpha")
    assert path.endswith("a.cs")


def test_scratch_clone_gets_a_marker_naming_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(fixtures, "SCRATCH_ROOT", str(tmp_path / "scratch"))
    elk = tmp_path / "T.elk"
    elk.write_text("link")
    (tmp_path / "T.edb").mkdir()
    out = fixtures.scratch_project_create(str(elk), open_after=False)
    marker = json.load(open(out["project"] + fixtures.SCRATCH_MARKER_SUFFIX, encoding="utf-8"))
    assert marker["kind"] == fixtures.SCRATCH_MARKER_KIND
    assert os.path.normcase(marker["project_link"]) == os.path.normcase(os.path.abspath(out["project"]))
    assert len(marker["nonce"]) == 32
    gone = fixtures.scratch_project_discard(out["project"], close_first=False)
    assert gone["success"] is True
    assert not os.path.exists(out["project"] + fixtures.SCRATCH_MARKER_SUFFIX)


def _fake_offline_host(queue, stop_event):
    """Plays EplanMcp.Host.Offline: keeps status.json fresh and answers queued requests."""
    import threading
    import time as _t

    def loop():
        while not stop_event.is_set():
            tmp = os.path.join(queue, "status.json.tmp")     # atomic, like the real host
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"protocol": 1, "core_version": scripthost.HOST_VERSION, "runtime": "offline",
                           "process_id": os.getpid()}, f)
            os.replace(tmp, os.path.join(queue, "status.json"))
            for f in os.listdir(queue):
                if f.endswith(".json") and f != "status.json":
                    job = json.load(open(os.path.join(queue, f), encoding="utf-8"))
                    req = json.load(open(job["request"], encoding="utf-8"))
                    json.dump({"protocol": 1, "ok": True, "phase": "done", "runtime": "offline",
                               "run_id": req["run_id"], "result": req["project"]},
                              open(job["result"], "w", encoding="utf-8"))
                    os.remove(os.path.join(queue, f))
            _t.sleep(0.05)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def test_offline_runtime_queues_and_needs_no_eplan_connection(host, monkeypatch, tmp_path):
    import threading
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(scripthost, "OFFLINE_QUEUE", str(queue))
    monkeypatch.setattr(scripthost, "_get_connected_manager",
                        lambda: (None, {"success": False, "message": "Not connected"}))
    monkeypatch.setattr(scripthost, "_pid_alive", lambda pid: pid == os.getpid())
    monkeypatch.setattr(scripthost, "OFFLINE_DIR", str(tmp_path / "never-start-a-real-host"))
    stop = threading.Event()
    _fake_offline_host(str(queue), stop)
    import time as _t
    for _ in range(100):
        if (queue / "status.json").exists():
            break
        _t.sleep(0.02)
    try:
        hello = scripthost.script_hello(runtime="offline")
        assert hello["success"] is True, hello
        out = scripthost.script_run(code="// @needs offline\nreturn 1;", runtime="offline", project="C:/x/a.elk")
        assert out["success"] is True and out["runtime"] == "offline" and out["result"] == "C:/x/a.elk"
    finally:
        stop.set()


def test_offline_host_missing_is_reported_plainly(host, monkeypatch, tmp_path):
    monkeypatch.setattr(scripthost, "OFFLINE_QUEUE", str(tmp_path / "q"))
    monkeypatch.setattr(scripthost, "OFFLINE_DIR", str(tmp_path / "nothing"))
    out = scripthost.script_hello(runtime="offline")
    assert out["success"] is False and "not built" in out["error"]


def test_offline_stop_writes_the_stop_file(host, monkeypatch, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(scripthost, "OFFLINE_QUEUE", str(queue))
    monkeypatch.setattr(scripthost, "_pid_alive", lambda pid: True)
    with open(queue / "status.json", "w") as f:
        json.dump({"protocol": 1, "process_id": 4242}, f)
    assert scripthost.script_offline_stop()["success"] is True
    assert (queue / "stop").exists()


# --- review fixes ----------------------------------------------------------------------------

def _lib(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "good.cs").write_text("// @tool good\nreturn 1;", encoding="utf-8")
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_DIRS", str(lib))
    return lib


def test_script_paths_must_be_cs_files_inside_a_library_folder(host, monkeypatch, tmp_path):
    use(monkeypatch, FakeManager())
    lib = _lib(tmp_path, monkeypatch)
    outside = tmp_path / "evil.cs"
    outside.write_text("// @unsafe\nreturn 1;", encoding="utf-8")
    (lib / "notes.txt").write_text("x", encoding="utf-8")
    for bad in (str(outside), str(lib / "notes.txt"), str(lib / ".." / "evil.cs"), str(lib)):
        out = scripthost.script_run(script=bad)
        assert out["success"] is False and out["error"], bad
    assert "not inside a script library" in scripthost.script_run(script=str(outside))["error"]
    for bad_name in ("../evil", "a b", "x;y"):
        assert scripthost.script_run(script=bad_name)["success"] is False
    path, _ = scripthost._resolve_script(str(lib / "good.cs"))
    assert path.endswith("good.cs")
    assert scripthost._resolve_script("good")[0].endswith("good.cs")


def test_only_library_scripts_get_script_path(host, monkeypatch, tmp_path):
    use(monkeypatch, FakeManager())
    lib = _lib(tmp_path, monkeypatch)
    out = scripthost.script_run(script="good")
    assert out.get("run_id"), out
    req = json.load(open(os.path.join(os.path.dirname(out_path(out)), "request.json"), encoding="utf-8"))
    assert os.path.normcase(req["script_path"]) == os.path.normcase(str(lib / "good.cs"))
    stray = tmp_path / "helper.cs"
    stray.write_text("class H {}", encoding="utf-8")
    out = scripthost.script_run(script="good", helpers=[str(stray)])
    assert out["success"] is False and "helpers" in out["error"]


def test_non_utf8_script_is_a_clear_error(host, monkeypatch, tmp_path):
    use(monkeypatch, FakeManager())
    lib = _lib(tmp_path, monkeypatch)
    (lib / "bad.cs").write_bytes(b"// @tool bad\nreturn \xff\xfe;")
    out = scripthost.script_run(script="bad")
    assert out["success"] is False and "not UTF-8" in out["error"]
    assert scripthost._resolve_script("good")[0].endswith("good.cs")   # a bad neighbour is skipped
    listed = {s["tool"]: s for s in scripthost.script_list()["scripts"]}
    assert "not UTF-8" in listed["bad"]["error"]


def test_library_resource_refuses_outside_paths(host, monkeypatch, tmp_path):
    import script_tools
    _lib(tmp_path, monkeypatch)
    outside = tmp_path / "evil.cs"
    outside.write_text("secret", encoding="utf-8")

    class App:
        def __init__(self):
            self.res = {}

        def resource(self, uri, **kw):
            return lambda fn: self.res.setdefault(uri, fn)
    app = App()
    script_tools.register_resources(app)
    read = app.res["eplan-script://library/{name}"]
    assert read("good").startswith("// @tool good")
    with pytest.raises(ValueError):
        read(str(outside))


def test_real_project_writes_need_the_human_switch(host, monkeypatch):
    use(monkeypatch, FakeManager())
    monkeypatch.setenv("EPLAN_MCP_SCRIPT_DIRS", str(host))
    monkeypatch.delenv(scripthost.REAL_PROJECT_SWITCH, raising=False)
    script = host / "w.cs"
    script.write_text("// @writes true\nreturn 1;", encoding="utf-8")
    out = scripthost.script_run(script=str(script), allow_real_project=True, confirm="ab" * 8)
    assert out["success"] is False and scripthost.REAL_PROJECT_SWITCH in out["error"]
    monkeypatch.setenv(scripthost.REAL_PROJECT_SWITCH, "true")      # only exactly "1"
    assert scripthost.script_run(script=str(script), allow_real_project=True,
                                 confirm="ab" * 8)["success"] is False
    assert "confirm_code" in scripthost.script_run.__doc__ and "not a security boundary" in \
        " ".join(scripthost.script_run.__doc__.split())


def test_claim_is_released_when_the_start_fails(host, monkeypatch):
    use(monkeypatch, FakeManager())

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(scripthost, "_addin_ok", True)      # no hello: fail in the start itself
    monkeypatch.setattr(scripthost, "_new_run_folder", boom)
    with pytest.raises(OSError):
        scripthost.script_run(code="return 1;")
    assert not scripthost._jobs
    monkeypatch.undo()


def test_failed_addin_run_rechecks_the_addin(host, monkeypatch):
    class Gone(FakeManager):
        def execute_action(self, action, quiet_mode=True, **kwargs):
            if action.startswith("EplanMcp_RunScript"):
                return {"success": False, "message": "action not found"}
            return super().execute_action(action, quiet_mode, **kwargs)

    use(monkeypatch, Gone())
    out = scripthost.script_run(code="return 1;")
    assert out["success"] is False and scripthost._addin_ok is None
    monkeypatch.setattr(scripthost, "_addin_ok", True)
    use(monkeypatch, FakeManager())
    assert scripthost.script_run(code="return 1;")["success"] is True
    assert scripthost._addin_ok is True     # a run with a result keeps the add-in


def test_offline_timeout_removes_the_queue_file(host, monkeypatch, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(scripthost, "OFFLINE_QUEUE", str(queue))
    monkeypatch.setattr(scripthost, "_offline_ensure", lambda: {})
    out = scripthost._invoke_offline("r1", "req", str(tmp_path / "none.json"), timeout=0.3)
    assert out["success"] is False and not (queue / "r1.json").exists()


def _offline_env(monkeypatch, tmp_path, alive):
    import subprocess
    queue = tmp_path / "queue"
    queue.mkdir()
    exe_dir = tmp_path / "offline"
    exe_dir.mkdir()
    (exe_dir / "EplanMcp.Host.Offline.exe").write_text("x")
    monkeypatch.setattr(scripthost, "OFFLINE_QUEUE", str(queue))
    monkeypatch.setattr(scripthost, "OFFLINE_DIR", str(exe_dir))
    monkeypatch.setattr(scripthost, "_OFFLINE_STOP_WAIT_S", 0.5)
    monkeypatch.setattr(scripthost, "_pid_alive", lambda pid: alive["pid"] == pid)
    started = []

    def popen(cmd, **kw):
        started.append(cmd)
        alive["pid"] = 777
        with open(queue / "status.json", "w") as f:
            json.dump({"protocol": 1, "process_id": 777}, f)
    monkeypatch.setattr(subprocess, "Popen", popen)
    return queue, started


def test_a_long_run_with_a_stale_status_never_starts_a_second_host(host, monkeypatch, tmp_path):
    alive = {"pid": 555}
    queue, started = _offline_env(monkeypatch, tmp_path, alive)
    with open(queue / "status.json", "w") as f:
        json.dump({"protocol": 1, "process_id": 555}, f)
    os.utime(queue / "status.json", (1, 1))            # heartbeat far in the past
    assert scripthost._offline_ensure()["process_id"] == 555 and not started


def test_dead_host_and_leftover_stop_file_start_a_fresh_host(host, monkeypatch, tmp_path):
    alive = {"pid": None}
    queue, started = _offline_env(monkeypatch, tmp_path, alive)
    with open(queue / "status.json", "w") as f:
        json.dump({"protocol": 1, "process_id": 555}, f)
    (queue / "stop").write_text("stop")
    assert scripthost._offline_status() is None
    assert scripthost._offline_ensure(start_timeout=2)["process_id"] == 777
    assert len(started) == 1 and not (queue / "stop").exists()


def test_a_stopping_host_that_is_still_alive_is_not_doubled(host, monkeypatch, tmp_path):
    alive = {"pid": 555}
    queue, started = _offline_env(monkeypatch, tmp_path, alive)
    with open(queue / "status.json", "w") as f:
        json.dump({"protocol": 1, "process_id": 555}, f)
    (queue / "stop").write_text("stop")
    with pytest.raises(TimeoutError):
        scripthost._offline_ensure()
    assert not started and (queue / "stop").exists()


def test_pid_alive_knows_this_process_is_not_the_host():
    assert scripthost._pid_alive(os.getpid()) is False      # alive, but not EplanMcp.Host.Offline
    assert scripthost._pid_alive(999999) is False


def test_a_host_that_deleted_its_status_but_still_runs_is_not_doubled(host, monkeypatch, tmp_path):
    alive = {"pid": 555}
    queue, started = _offline_env(monkeypatch, tmp_path, alive)
    with open(queue / "status.json", "w") as f:
        json.dump({"protocol": 1, "process_id": 555}, f)
    assert scripthost._offline_ensure()["process_id"] == 555
    os.remove(queue / "status.json")              # idle exit / stop: file gone, process not yet
    with pytest.raises(TimeoutError):
        scripthost._offline_ensure()
    assert not started
    alive["pid"] = None                            # now it has exited
    assert scripthost._offline_ensure(start_timeout=2)["process_id"] == 777
    assert len(started) == 1


# --- host version ----------------------------------------------------------------------------

def test_hello_warns_on_a_host_version_mismatch_but_still_succeeds(host, monkeypatch):
    class OldHost(FakeManager):
        def execute_action(self, action, quiet_mode=True, **kwargs):
            out = super().execute_action(action, quiet_mode, **kwargs)
            result_path = action.split('/result:"')[1].rstrip('"')
            data = json.load(open(result_path, encoding="utf-8"))
            json.dump(dict(data, core_version="0.1.0"), open(result_path, "w", encoding="utf-8"))
            return out

    use(monkeypatch, OldHost(addin=True))
    hello = scripthost.script_hello(runtime="addin")
    assert hello["success"] is True
    assert "0.1.0" in hello["warning"] and scripthost.HOST_VERSION in hello["warning"]

    use(monkeypatch, FakeManager(addin=True))
    assert "warning" not in scripthost.script_hello(runtime="addin")


def test_host_version_matches_the_dotnet_build_version():
    import re
    props = open(os.path.join(scripthost.DOTNET_DIR, "Directory.Build.props"), encoding="utf-8").read()
    assert re.search(r"<Version>([^<]+)</Version>", props).group(1) == scripthost.HOST_VERSION


def test_eplan_dying_under_a_run_keeps_its_typed_failure(host, monkeypatch):
    class Dies(FakeManager):
        def execute_action(self, action, quiet_mode=True, **kwargs):
            if action.startswith("EplanMcp_RunScript"):
                return {"success": False, "errorType": "EplanNotRunning",
                        "error": "EPLAN (pid 7) is no longer running; the call did not complete",
                        "next_step": "eplan_app_launch"}
            return super().execute_action(action, quiet_mode, **kwargs)

    use(monkeypatch, Dies())
    out = scripthost.script_run(code="return 1;")
    assert out["success"] is False and out["errorType"] == "EplanNotRunning"
    assert out["next_step"] == "eplan_app_launch"
