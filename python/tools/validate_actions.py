"""
Cross-check the MCP action wrappers against the official EPLAN P8 2027 wiki.

For every function in mcp_server/api/actions/*.py it extracts:
  - the EPLAN action name declared in the docstring ("Action: <Name>")
  - the parameter keys passed to _build_action(...)

and then verifies each one against the remote 2027 wiki
(https://rag2027.covaga.xyz):

  1. Existence. Every documented EPLAN action has exactly one page at
     "API Reference/Actions/<Name>.md". The wiki serves whole pages over
     GET /file?path=<path>, which either returns the page (HTTP 200) or a
     clean 404. That is an exact yes/no signal, so this script no longer does
     the fuzzy title/content matching the old 2026 /search-only checker did.
  2. Parameters. Each /KEY passed to _build_action must appear in the FULL
     page text (not a truncated search snippet). The check is case-sensitive
     first, because _build_action forwards kwarg names verbatim as /KEY and
     EPLAN's casing is not uniform (PROJECTNAME but OpenMode, PartNr,
     ConfigScheme, register, registerModule). A key that matches only
     case-insensitively is reported separately as a case mismatch rather than
     folded into OK.

Actions with no wiki page are split in two:
  - listed in tools/data/official_actions_2027.json but with no page
    (a wiki index gap) - params are then cross-checked against that JSON;
  - not listed there either - a GUI-only / internal action that has never
    been part of the public API docs.

--completeness additionally answers "does the wiki contain any action we do
not know about?" by enumerating "API Reference/Actions/" pages with a
self-terminating prefix sweep and diffing against
tools/data/official_actions_2027.json.

The sweep is thousands of remote queries and takes tens of minutes, so it is
opt-in; --completeness-only runs it alone and writes no report.

Usage:
    python tools/validate_actions.py [--out report.md] [--rag-url URL]
                                     [--completeness | --completeness-only]
                                     [--workers 8] [--sweep-workers 4]
                                     [--max-depth 6] [--top-k 20]

No third-party dependencies (urllib only).
"""

import argparse
import ast
import json
import os
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_RAG_URL = "https://rag2027.covaga.xyz"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTIONS_DIR = os.path.join(REPO_ROOT, "mcp_server", "api", "actions")
OFFICIAL_JSON = os.path.join(REPO_ROOT, "tools", "data", "official_actions_2027.json")
ACTION_RE = re.compile(r"Action:\s*([A-Za-z0-9_]+)")

# Wiki layout: one page per documented action, named exactly like the action.
ACTION_DIR_PREFIX = "API Reference/Actions/"
ACTION_PAGE_RE = re.compile(r"^API Reference/Actions/([^/]+)\.md$")

# Parameter keys that are wrapper-internal or too generic to validate
IGNORED_PARAMS = {"TYPE"}

# Cloudflare rejects the default python-urllib User-Agent with a 403.
_HEADERS = {"User-Agent": "curl/8"}


# --------------------------------------------------------------------------
# wrapper parsing
# --------------------------------------------------------------------------

def extract_wrappers(actions_dir=ACTIONS_DIR):
    """Parse every action module and return [(module, func, action, params)]."""
    wrappers = []
    for fname in sorted(os.listdir(actions_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(actions_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or ""
            m = ACTION_RE.search(doc)
            action = m.group(1) if m else None

            params = set()
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "_build_action"
                ):
                    for kw in call.keywords:
                        if kw.arg and kw.arg not in IGNORED_PARAMS:
                            params.add(kw.arg)
            wrappers.append((fname[:-3], node.name, action, sorted(params)))
    return wrappers


# --------------------------------------------------------------------------
# wiki transport
# --------------------------------------------------------------------------

def normalise_rag_url(url):
    """Accept a bare base URL or one still pointing at the /search endpoint."""
    url = (url or DEFAULT_RAG_URL).rstrip("/")
    for suffix in ("/search", "/file"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def _open(req, timeout, retries):
    """urlopen with an exponential-backoff retry on 429/5xx and transport errors.

    The wiki is a Cloudflare worker and does start answering 500 when a sweep
    pushes a few thousand queries at it, so the backoff has to be real (up to
    ~8 s) rather than a token 0.5 s.
    """
    last = None
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code == 404 or attempt == retries:
                raise
            if e.code not in (408, 425, 429, 500, 502, 503, 504):
                raise
            last = e
        except Exception as e:  # timeouts, connection resets
            if attempt == retries:
                raise
            last = e
        time.sleep(min(8.0, 0.75 * (2 ** attempt)))
    raise last


def rag_search(base, query, top_k=20, timeout=60, retries=3):
    """POST /search -> {"results": [{path, title, kind, breadcrumb, source_url, snippet}]}"""
    body = json.dumps({"query": query, "topK": top_k}).encode("utf-8")
    headers = dict(_HEADERS)
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + "/search", data=body, headers=headers)
    return json.loads(_open(req, timeout, retries).decode("utf-8"))


def rag_file(base, path, timeout=60, retries=3):
    """GET /file?path=... -> the full page dict, or None when the page is absent."""
    url = base + "/file?" + urllib.parse.urlencode({"path": path})
    req = urllib.request.Request(url, headers=dict(_HEADERS))
    try:
        data = json.loads(_open(req, timeout, retries).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if not isinstance(data, dict) or "content" not in data:
        return None
    return data


def action_page_path(action):
    return "{}{}.md".format(ACTION_DIR_PREFIX, action)


# --------------------------------------------------------------------------
# per-action check
# --------------------------------------------------------------------------

def _classify_params(params, text):
    """Split params into (missing, case_mismatched) against a page's full text."""
    missing, case_only = [], []
    for p in params:
        if re.search(r"\b{}\b".format(re.escape(p)), text):
            continue
        if re.search(r"\b{}\b".format(re.escape(p)), text, re.IGNORECASE):
            case_only.append(p)
        else:
            missing.append(p)
    return missing, case_only


def check_action(base, action, params, official=None):
    """Return a result dict for one EPLAN action name."""
    official = official or {}
    try:
        page = rag_file(base, action_page_path(action))
    except Exception as e:
        return {"action": action, "status": "error", "detail": str(e)}

    if page is None:
        entry = official.get(action)
        if entry is None:
            return {
                "action": action,
                "status": "undocumented",
                "detail": "no 'API Reference/Actions/{}.md' page and not in "
                          "official_actions_2027.json - GUI-only or internal "
                          "action, parameters observed rather than documented"
                          .format(action),
            }
        # In our official list but missing from the wiki: fall back to the
        # parameter table scraped from eplan.help.
        text = json.dumps(entry, ensure_ascii=False)
        missing, case_only = _classify_params(params, text)
        detail = ("in official_actions_2027.json but the wiki has no "
                  "'API Reference/Actions/{}.md' page (wiki index gap); "
                  "parameters checked against the JSON instead".format(action))
        if missing:
            detail += " - params not in the JSON: {}".format(missing)
        if case_only:
            detail += " - case mismatch vs the JSON: {}".format(case_only)
        return {
            "action": action,
            "status": "no_wiki_page",
            "detail": detail,
            "doc": entry.get("doc_url", ""),
        }

    text = page.get("content", "")
    missing, case_only = _classify_params(params, text)
    if missing:
        status = "params_missing"
        detail = "params not on the doc page: {}".format(missing)
        if case_only:
            detail += "; case mismatch: {}".format(case_only)
    elif case_only:
        status = "case_mismatch"
        detail = ("params present only with different casing: {} - "
                  "_build_action forwards kwarg names verbatim as /KEY, so "
                  "check this against EPLAN".format(case_only))
    else:
        status = "ok"
        detail = ""
    return {
        "action": action,
        "status": status,
        "detail": detail,
        "doc": page.get("source_url", ""),
        "page": page.get("path", ""),
    }


# --------------------------------------------------------------------------
# wiki completeness sweep
# --------------------------------------------------------------------------

ALPHABET = string.ascii_lowercase + string.digits


def wiki_action_pages(base, seeds=None, top_k=20, workers=8, max_depth=3,
                      start_len=2, progress=None):
    """Enumerate every "API Reference/Actions/*.md" page in the wiki.

    /search caps topK at 20 and offers no pagination and no path filter, so
    the only way to enumerate is many queries. The wiki's FTS5 index does
    prefix matching (a query "XEs" is run as "XEs*"), which makes a prefix
    sweep sound: issue every prefix of length `start_len`; whenever a prefix
    comes back saturated (exactly top_k hits, so results may have been cut
    off), recurse into that prefix + one more character. A prefix that is not
    saturated has certainly returned all of its matches, so the recursion
    terminates on its own.

    Single-letter prefixes are avoided by default (start_len=2): they match
    most of the 1754-page index and the server takes ~40 s to answer one.

    `max_depth` is 3 rather than unbounded because the cost per level is
    brutal and the yield collapses: measured against the 2027 wiki, length-2
    prefixes found all 98 action pages, and length-3 (10,872 queries, 1115 of
    them still saturated) found not one more. Length-4 would have been
    ~40,000 queries for that same nothing. Raise it to distrust convergence.

    `seeds` (e.g. the known action names) are queried as-is in addition; they
    cost one request each and pin down names whose own prefix is saturated.

    Returns (pages, stats) where pages maps action name -> wiki path.
    """
    pages = {}
    stats = {"queries": 0, "saturated": 0, "max_depth": 0, "failed": 0,
             "failed_queries": []}

    def _one(q):
        """Never raise: a single failed query must not abandon the sweep."""
        try:
            return q, rag_search(base, q, top_k), None
        except Exception as e:
            return q, None, e

    def run(queries):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_one, queries))
        # One serial second pass over whatever failed - by then the burst that
        # provoked the 500s is over, and this keeps a handful of transient
        # failures from turning into silent holes in the enumeration.
        retry = [q for q, _, err in results if err is not None]
        if retry:
            fixed = {}
            for q in retry:
                time.sleep(0.2)
                _, data, err = _one(q)
                if err is None:
                    fixed[q] = data
            results = [(q, fixed.get(q, data), None if q in fixed else err)
                       for q, data, err in results]
        return results

    def harvest(results):
        saturated = []
        for q, data, err in results:
            if err is not None:
                stats["failed"] += 1
                if len(stats["failed_queries"]) < 50:
                    stats["failed_queries"].append(q)
                continue
            hits = data.get("results", [])
            for r in hits:
                m = ACTION_PAGE_RE.match(r.get("path", ""))
                if m:
                    pages[m.group(1)] = r["path"]
            if len(hits) >= top_k:
                saturated.append(q)
        return saturated

    if seeds:
        seeds = sorted(set(seeds))
        stats["queries"] += len(seeds)
        harvest(run(seeds))
        if progress:
            progress("seeds: {} queries, {} action pages"
                     .format(len(seeds), len(pages)))

    level = [""]
    for _ in range(start_len):
        level = [p + c for p in level for c in ALPHABET]
    depth = start_len
    while level and depth <= max_depth:
        stats["queries"] += len(level)
        stats["max_depth"] = depth
        saturated = harvest(run(level))
        stats["saturated"] += len(saturated)
        if progress:
            progress("prefix len {}: {} queries, {} saturated, {} failed, "
                     "{} action pages total"
                     .format(depth, len(level), len(saturated),
                             stats["failed"], len(pages)))
        level = [p + c for p in saturated for c in ALPHABET]
        depth += 1
    return pages, stats


def load_official(path=OFFICIAL_JSON):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_wiki_completeness(base, official=None, top_k=20, workers=8,
                            progress=None, sweep=True, max_depth=3,
                            sweep_workers=None):
    """Diff the wiki's action pages against official_actions_2027.json.

    Two independent passes:
      - direct: GET /file for every name we know about (exact yes/no);
      - sweep:  enumerate the wiki's own Actions/ pages, which is the pass
                that can find names we do NOT know about.
    """
    official = official if official is not None else load_official()
    names = sorted(official)

    def probe(n):
        try:
            return n, rag_file(base, action_page_path(n)) is not None, None
        except Exception as e:
            return n, None, e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        present = {n: (ok, err) for n, ok, err in pool.map(probe, names)}
    for n in [n for n, (ok, err) in present.items() if err is not None]:
        time.sleep(0.2)  # one calm serial retry
        _, ok, err = probe(n)
        present[n] = (ok, err)
    have_page = sorted(n for n, (ok, err) in present.items() if ok)
    no_page = sorted(n for n, (ok, err) in present.items() if ok is False)
    unknown = sorted(n for n, (ok, err) in present.items() if err is not None)
    if unknown:
        raise RuntimeError(
            "the wiki could not be reached for {}: {}".format(unknown[:5], len(unknown)))
    if progress:
        progress("direct /file probe: {}/{} of our known actions have a wiki "
                 "page".format(len(have_page), len(names)))

    result = {
        "known": len(names),
        "known_with_page": have_page,
        "known_without_page": no_page,
        "direct_queries": len(names),
    }

    if not sweep:
        return result

    # The sweep is thousands of queries; run it gentler than the per-action
    # pass so the worker does not start answering 500.
    pages, stats = wiki_action_pages(base, seeds=names, top_k=top_k,
                                     workers=sweep_workers or max(2, workers // 2),
                                     max_depth=max_depth, progress=progress)
    # A dotted page name under Actions/ (the Foo.Enums.md pattern the wiki
    # uses for class sub-pages) would not be an action - surface it rather
    # than counting it as one.
    actions = {n: p for n, p in pages.items() if "." not in n}
    suspicious = sorted(n for n in pages if "." in n)
    result.update({
        "wiki_pages": sorted(actions),
        "wiki_page_count": len(actions),
        "wiki_only": sorted(set(actions) - set(names)),
        "ours_only": sorted(set(names) - set(actions)),
        "non_action_pages": suspicious,
        "sweep_queries": stats["queries"],
        "sweep_saturated": stats["saturated"],
        "sweep_max_prefix_len": stats["max_depth"],
        "sweep_failed": stats["failed"],
        "sweep_failed_queries": stats["failed_queries"],
    })
    return result


def format_completeness(res):
    lines = [
        "## Wiki completeness",
        "",
        "Does the 2027 wiki document any action we do not know about?",
        "",
        "Direct probe - `GET /file` for each of the {} names in "
        "`tools/data/official_actions_2027.json`:".format(res["known"]),
        "",
        "- with a wiki page: **{}**".format(len(res["known_with_page"])),
        "- without a wiki page: **{}**{}".format(
            len(res["known_without_page"]),
            (" (`" + "`, `".join(res["known_without_page"]) + "`)")
            if res["known_without_page"] else ""),
        "",
    ]
    if "wiki_page_count" in res:
        lines += [
            "Reverse sweep - enumerate `API Reference/Actions/*.md` with {} "
            "prefix/seed queries (FTS5 prefix search, recursing only into "
            "saturated prefixes; deepest prefix used: {} characters):".format(
                res["sweep_queries"], res["sweep_max_prefix_len"]),
            "",
            "- action pages found in the wiki: **{}**".format(res["wiki_page_count"]),
            "- in the wiki but NOT in our list: **{}**{}".format(
                len(res["wiki_only"]),
                (" (`" + "`, `".join(res["wiki_only"]) + "`)")
                if res["wiki_only"] else " - our list is complete"),
            "- in our list but NOT in the wiki: **{}**{}".format(
                len(res["ours_only"]),
                (" (`" + "`, `".join(res["ours_only"]) + "`)")
                if res["ours_only"] else ""),
        ]
        if res["non_action_pages"]:
            lines.append("- dotted (non-action) pages under `Actions/`: `{}`"
                         .format("`, `".join(res["non_action_pages"])))
        if res.get("sweep_failed"):
            lines.append(
                "- queries that still failed after retries: **{}** "
                "(`{}`{}) - the sweep is that much less than exhaustive"
                .format(res["sweep_failed"],
                        "`, `".join(res["sweep_failed_queries"][:10]),
                        ", ..." if res["sweep_failed"] > 10 else ""))
        else:
            lines.append("- queries that failed after retries: 0")
        lines.append("")
    return lines


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=20,
                        help="results per /search query (the wiki caps it at 20)")
    parser.add_argument("--rag-url", default=DEFAULT_RAG_URL,
                        help="wiki base URL (default: %(default)s). A URL "
                             "ending in /search is accepted too.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sweep-workers", type=int, default=4,
                        help="concurrency for the completeness sweep; keep it "
                             "low, the wiki answers 500 under a burst")
    parser.add_argument("--completeness", action="store_true",
                        help="also run the wiki completeness sweep "
                             "(a few thousand queries, several minutes)")
    parser.add_argument("--completeness-only", action="store_true",
                        help="run only the completeness sweep and print it; "
                             "write no report")
    parser.add_argument("--max-depth", type=int, default=3,
                        help="deepest prefix length the sweep may recurse to. "
                             "Each level costs roughly 36x the previous one; "
                             "length 3 already converged on the 2027 wiki")
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "action_validation_report.md"))
    args = parser.parse_args(argv)

    base = normalise_rag_url(args.rag_url)
    official = load_official()

    if args.completeness_only:
        res = check_wiki_completeness(
            base, official, args.top_k, args.workers, max_depth=args.max_depth,
            progress=lambda m: print("  " + m, flush=True))
        print("\n".join(format_completeness(res)))
        return 0

    wrappers = extract_wrappers()
    scripted = [1 for _, _, a, _ in wrappers if a is None]
    declared = {}
    for module, func, action, params in wrappers:
        if action:
            entry = declared.setdefault(action, {"params": set(), "funcs": []})
            entry["params"].update(params)
            entry["funcs"].append("{}.{}".format(module, func))

    print("Wrappers: {} functions, {} unique EPLAN actions, {} scripted/no-action "
          "(skipped)".format(len(wrappers), len(declared), len(scripted)))
    print("Wiki: {}".format(base))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        checked = list(pool.map(
            lambda kv: check_action(base, kv[0], sorted(kv[1]["params"]), official),
            sorted(declared.items())))
    results = {r["action"]: r for r in checked}

    completeness = None
    if args.completeness:
        # The sweep is thousands of remote queries and can still die on a bad
        # day. Losing it must not also lose the per-action report, which is
        # the artifact people actually read.
        try:
            completeness = check_wiki_completeness(
                base, official, args.top_k, args.workers,
                max_depth=args.max_depth, sweep_workers=args.sweep_workers,
                progress=lambda m: print("  " + m, flush=True))
        except Exception as e:
            print("  completeness sweep FAILED ({}) - writing the per-action "
                  "report without it".format(e), flush=True)

    order = {"error": 0, "params_missing": 1, "case_mismatch": 2,
             "no_wiki_page": 3, "undocumented": 4, "ok": 5}
    rows = sorted(results.values(), key=lambda r: (order[r["status"]], r["action"]))
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in order}

    lines = [
        "# EPLAN Action Validation Report",
        "",
        "Checked **{}** unique EPLAN actions declared by the wrappers against "
        "the official EPLAN 2027 wiki (`{}`).".format(len(rows), base),
        "",
        "An action counts as documented if and only if the wiki serves a page "
        "at `API Reference/Actions/<Name>.md`. Parameter names are matched "
        "**case-sensitively** against that page's full text, because "
        "`_build_action` forwards kwarg names verbatim as `/KEY`.",
        "",
        "- OK: {}".format(counts["ok"]),
        "- Parameter names not found on the doc page: {}".format(counts["params_missing"]),
        "- Parameter names present but with different casing: {}".format(counts["case_mismatch"]),
        "- In our official list but no wiki page (wiki index gap): {}".format(counts["no_wiki_page"]),
        "- Undocumented (GUI-only / internal action, never in the API docs): {}".format(counts["undocumented"]),
        "- Request errors: {}".format(counts["error"]),
        "",
    ]
    if completeness:
        lines += format_completeness(completeness)
    lines += [
        "## Per-action results",
        "",
        "| Status | Action | Wrapper(s) | Detail |",
        "|--------|--------|------------|--------|",
    ]
    icon = {"ok": "OK", "params_missing": "WARN", "case_mismatch": "CASE",
            "no_wiki_page": "NO WIKI PAGE", "undocumented": "UNDOCUMENTED",
            "error": "ERROR"}
    for r in rows:
        funcs = ", ".join(declared[r["action"]]["funcs"])
        doc = r.get("doc", "")
        detail = r.get("detail", "")
        if doc:
            detail = "{} [doc]({})".format(detail, doc) if detail else "[doc]({})".format(doc)
        lines.append("| {} | `{}` | `{}` | {} |".format(
            icon[r["status"]], r["action"], funcs, detail))

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("\nReport written to {}".format(args.out))
    print("OK={ok}  WARN(params)={params_missing}  CASE={case_mismatch}  "
          "NO_WIKI_PAGE={no_wiki_page}  UNDOCUMENTED={undocumented}  "
          "ERROR={error}".format(**counts))
    # Only transport failures are a hard failure: a missing wiki page and an
    # undocumented GUI action are both known, explained states.
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
