"""Offline tests for the script host release install (scripthost.ensure_host): a local HTTP server
plays the GitHub release, the install root is a temp folder."""

import functools
import hashlib
import http.server
import io
import os
import threading
import zipfile

import pytest

from api.actions import scripthost

V = scripthost.HOST_VERSION


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def release(tmp_path, monkeypatch):
    """Serves <root>/repo/releases/download/v<V>/ and records every request path."""
    folder = tmp_path / "www" / "repo" / "releases" / "download" / ("v" + V)
    folder.mkdir(parents=True)
    requests = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path / "www")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("EPLAN_MCP_RELEASE_URL", "http://127.0.0.1:%d/repo" % server.server_port)
    monkeypatch.setattr(scripthost, "INSTALL_ROOT", str(tmp_path / "installed"))

    def publish(addon=None, offline=None, sums=None):
        addon = addon or _zip({f"EplanMcp/{V}/BIN/eplanmcp-version.txt": V,
                               f"EplanMcp/{V}/CFG/install.xml": "<Settings/>"})
        offline = offline or _zip({"EplanMcp.Host.Offline.exe": "exe"})
        files = {f"EplanMcp-{V}-addon.zip": addon, f"EplanMcp-{V}-offline.zip": offline}
        for name, data in files.items():
            (folder / name).write_bytes(data)
        if sums is None:
            sums = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        # pack-release.ps1 writes "<lowercase hex>  <name>" lines; Windows line ends.
        (folder / "SHA256SUMS.txt").write_bytes(
            "".join("%s  %s\r\n" % (h, n) for n, h in sums.items()).encode("ascii"))

    yield publish, requests, tmp_path / "installed"
    server.shutdown()


def _leftovers(root):
    return [n for n in os.listdir(root) if n.startswith(".download-")] if os.path.isdir(root) else []


def test_good_release_installs_and_a_second_call_is_a_no_op(release):
    publish, requests, root = release
    publish()
    out = scripthost.script_host_install()
    assert out["success"] is True and out["installed"] is True, out
    assert open(os.path.join(out["host_dir"], "eplanmcp-version.txt")).read() == V
    assert os.path.isfile(os.path.join(out["offline_dir"], "EplanMcp.Host.Offline.exe"))
    assert os.path.isfile(out["install_file"])
    assert not _leftovers(root)

    requests.clear()
    again = scripthost.script_host_install()
    assert again["success"] is True and again["installed"] is False
    assert requests == []


def test_bad_checksum_is_refused_and_leaves_nothing(release):
    publish, _, root = release
    publish(sums={f"EplanMcp-{V}-addon.zip": "0" * 64, f"EplanMcp-{V}-offline.zip": "0" * 64})
    out = scripthost.script_host_install()
    assert out["success"] is False and "SHA-256" in out["error"]
    assert not os.path.exists(root / V) and not _leftovers(root)


def test_missing_checksum_line_is_refused(release):
    publish, _, root = release
    publish(sums={})
    out = scripthost.script_host_install()
    assert out["success"] is False and "no checksum" in out["error"]
    assert not os.path.exists(root / V)


def test_zip_slip_entry_is_refused(release, tmp_path):
    publish, _, root = release
    publish(offline=_zip({"EplanMcp.Host.Offline.exe": "exe", "../../evil.txt": "x"}))
    out = scripthost.script_host_install()
    assert out["success"] is False and "outside the install folder" in out["error"]
    assert not os.path.exists(root / V) and not _leftovers(root)
    assert not any(p.name == "evil.txt" for p in tmp_path.rglob("evil.txt"))


def test_bad_version_never_reaches_the_network(release):
    _, requests, _ = release
    out = scripthost.script_host_install(version="../0.2.0")
    assert out["success"] is False and requests == []


def test_auto_install_runs_only_for_the_default_install_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(scripthost, "INSTALL_ROOT", str(tmp_path / "installed"))
    calls = []
    monkeypatch.setattr(scripthost, "ensure_host", lambda *a: calls.append(a))
    scripthost._auto_install(str(tmp_path / "some-override"))
    assert calls == []
    scripthost._auto_install(scripthost._installed_dirs()[1])
    assert len(calls) == 1


def test_dropped_download_is_reported_not_raised(tmp_path, monkeypatch):
    import http.client
    monkeypatch.setattr(scripthost, "INSTALL_ROOT", str(tmp_path / "installed"))

    def broken(url, timeout=None):
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(scripthost.urllib.request, "urlopen", broken)
    out = scripthost.script_host_install()
    assert out["success"] is False and not _leftovers(tmp_path / "installed")
