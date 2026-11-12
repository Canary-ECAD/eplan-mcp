"""direct=True skips the quiet-mode script wrapper.

.NET 8 (CoreCLR-hosted) add-in actions started inside the generated C# script
fail every lock with S511176; through the Remote Client's own ExecuteAction
they lock normally (measured live on EPLAN 2027.0.3). Pins that the default
stays wrapped and direct=True reaches execute_action with quiet_mode=False.
"""
from api.actions import _base, addons, catalog


class _Mgr:
    connected = True

    def __init__(self):
        self.calls = []

    def execute_action(self, action, quiet_mode=False, **kw):
        self.calls.append((action, quiet_mode))
        return {"success": True}


def _patch(monkeypatch, module):
    mgr = _Mgr()
    monkeypatch.setattr(module, "_get_connected_manager",
                        lambda: (_base.QuietManagerWrapper(mgr), None))
    return mgr


def test_raw_action_is_wrapped_by_default_and_direct_opts_out(monkeypatch):
    mgr = _patch(monkeypatch, addons)
    addons.execute_raw_action("SomeAddinAction")
    addons.execute_raw_action("SomeAddinAction", direct=True)
    assert mgr.calls == [("SomeAddinAction", True), ("SomeAddinAction", False)]


def test_action_run_direct_opts_out(monkeypatch):
    mgr = _patch(monkeypatch, catalog)
    name = next(iter(catalog._load_registry()[0]))
    assert catalog.action_run(name)["success"] is True
    assert catalog.action_run(name, direct=True)["success"] is True
    assert [q for _, q in mgr.calls] == [True, False]
