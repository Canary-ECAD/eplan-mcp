"""EPLAN Remote Client connection, split by concern.

Import through the eplan_connection shim, which re-exports every name and
forwards monkeypatches to the module that reads them:

    logs            logging setup, actions.jsonl
    versions        installed EPLAN versions
    clr_bootstrap   pythonnet runtime choice and EPLAN DLL loading
    processes       EPLAN.exe processes, ports and windows
    runner          call_with_timeout and the bounded ExecuteAction
    dialogs         dialogs.jsonl history and dismissal advice
    shaping         the action-result contract and message shaping
    action_scaffold the generated quiet-mode C# action wrapper
    manager         EPLANConnectionManager, composed from the mixins above
"""
