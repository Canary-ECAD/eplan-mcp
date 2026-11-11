"""
Release notes from two tools.json files: which tools were added, removed or
re-annotated between the previous release and this one.

    python tools/release_notes.py OLD.json NEW.json > notes.md

OLD.json may be missing (the first release, or a previous tag without the
file). A tool that used to change something and is now read-only gets its own
warning line: a client that trusts the annotations stops asking before it.
"""

import json
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return {tool["name"]: tool for tool in data.get("tools", [])}


def changes_something(tool):
    facts = tool.get("facts") or {}
    read_only = (tool.get("annotations") or {}).get("readOnlyHint") is True
    return not read_only or any(facts.get(k) for k in ("changesProject", "runsCode", "changesEplan"))


def _describe(tool):
    annotations = tool.get("annotations") or {}
    facts = tool.get("facts") or {}
    words = [k for k, v in annotations.items() if v is True]
    words += [k for k in ("changesProject", "runsCode", "changesEplan") if facts.get(k)]
    if facts.get("projectArgument"):
        words.append(f"projectArgument={facts['projectArgument']}")
    return ", ".join(words) or "no hints"


def _diff(old, new):
    out = []
    for group in ("annotations", "facts"):
        before, after = old.get(group) or {}, new.get(group) or {}
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                out.append(f"{key} {json.dumps(before.get(key))} → {json.dumps(after.get(key))}")
    return "; ".join(out)


def notes(old, new):
    lines = []
    if old is None:
        lines += [f"Tool contract: {len(new)} tools, each with MCP annotations and EPLAN facts "
                  "(see tools.json and llm.md).", ""]
        return "\n".join(lines)

    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(n for n in set(old) & set(new)
                     if (old[n].get("annotations"), old[n].get("facts"))
                     != (new[n].get("annotations"), new[n].get("facts")))
    now_read_only = [n for n in changed if changes_something(old[n]) and not changes_something(new[n])]

    lines.append(f"Tools: {len(new)} ({len(added)} added, {len(removed)} removed, "
                 f"{len(changed)} re-annotated).")
    lines.append("")
    for name in now_read_only:
        lines.append(f"> **Warning:** `{name}` used to change something and is now read-only.")
    for name in removed:
        # Skills, docs and other repos call tools by name: a rename is a removal.
        lines.append(f"> **Warning:** `{name}` was removed or renamed; callers that use it break.")
    if now_read_only or removed:
        lines.append("")
    if added:
        lines += ["### Added", ""] + [f"- `{n}` ({_describe(new[n])})" for n in added] + [""]
    if removed:
        lines += ["### Removed", ""] + [f"- `{n}`" for n in removed] + [""]
    if changed:
        lines += ["### Re-annotated", ""] + [f"- `{n}`: {_diff(old[n], new[n])}" for n in changed] + [""]
    if not (added or removed or changed):
        lines += ["No tool was added, removed or re-annotated.", ""]
    return "\n".join(lines)


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    new = load(argv[1])
    if new is None:
        print(f"Cannot read {argv[1]}.", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(notes(load(argv[0]), new))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
