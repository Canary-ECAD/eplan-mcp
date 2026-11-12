"""Offline tests for tools/validate_actions.py.

Nothing here touches the network. The wiki transport is exercised through a
stubbed ``rag_file`` / ``rag_search``, so these tests pin the parts that
decide correctness: how a URL is normalised, how an action name maps to a wiki
page path, and the case-sensitive parameter classification that exists
precisely because ``_build_action`` forwards kwarg names verbatim as ``/KEY``.
"""

import importlib.util
import os

import pytest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(REPO_ROOT, "tools", "validate_actions.py")


@pytest.fixture(scope="module")
def va():
    spec = importlib.util.spec_from_file_location("_validate_actions", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# endpoint plumbing
# ---------------------------------------------------------------------------

def test_default_rag_url_is_the_2027_wiki(va):
    assert va.DEFAULT_RAG_URL == "https://rag2027.covaga.xyz"


@pytest.mark.parametrize("given,expected", [
    ("https://rag2027.covaga.xyz", "https://rag2027.covaga.xyz"),
    ("https://rag2027.covaga.xyz/", "https://rag2027.covaga.xyz"),
    # A URL copied from the old 2026 invocation still points at /search.
    ("https://rag2027.covaga.xyz/search", "https://rag2027.covaga.xyz"),
    ("https://rag2027.covaga.xyz/file/", "https://rag2027.covaga.xyz"),
    ("http://localhost:8787/search", "http://localhost:8787"),
    (None, "https://rag2027.covaga.xyz"),
])
def test_normalise_rag_url(va, given, expected):
    assert va.normalise_rag_url(given) == expected


def test_action_page_path_and_regex_round_trip(va):
    path = va.action_page_path("XEsSetPropertyAction")
    assert path == "API Reference/Actions/XEsSetPropertyAction.md"
    assert va.ACTION_PAGE_RE.match(path).group(1) == "XEsSetPropertyAction"


@pytest.mark.parametrize("path", [
    "API Reference/Actions/renumber.md",
    "API Reference/Actions/XEsGetPropertyAction.md",
])
def test_action_page_regex_accepts_action_pages(va, path):
    assert va.ACTION_PAGE_RE.match(path)


@pytest.mark.parametrize("path", [
    # A class page, not an action page.
    "API Reference/Assemblies for .NET Framework/Eplan.EplApi.HEServicesu "
    "Assembly/Eplan.EplApi.HEServices Namespace/Renumber.md",
    "User Guide/API Framework/Add-ins/Actions/Calling actions.md",
    # Anything nested below Actions/ is not one page per action.
    "API Reference/Actions/sub/thing.md",
])
def test_action_page_regex_rejects_everything_else(va, path):
    assert va.ACTION_PAGE_RE.match(path) is None


# ---------------------------------------------------------------------------
# parameter classification: case matters
# ---------------------------------------------------------------------------

def test_classify_params_exact_match_is_clean(va):
    missing, case_only = va._classify_params(
        ["PROJECTNAME", "OpenMode"], "| PROJECTNAME | ... | OpenMode |")
    assert missing == []
    assert case_only == []


def test_classify_params_flags_case_mismatch_separately(va):
    """A key that only matches case-insensitively must NOT count as documented.

    EPLAN silently ignores a /KEY whose casing is wrong, so folding this into
    OK is exactly the failure mode the report exists to catch.
    """
    missing, case_only = va._classify_params(
        ["OPENMODE"], "| OpenMode | how the project is opened |")
    assert missing == []
    assert case_only == ["OPENMODE"]


def test_classify_params_reports_absent_keys(va):
    missing, case_only = va._classify_params(
        ["NOSUCHKEY"], "| OpenMode | ... |")
    assert missing == ["NOSUCHKEY"]
    assert case_only == []


def test_classify_params_uses_word_boundaries(va):
    """A substring hit must not be accepted: /SCALE is not /SCALESETTING."""
    missing, _ = va._classify_params(["SCALE"], "| SCALESETTING | ... |")
    assert missing == ["SCALE"]


# ---------------------------------------------------------------------------
# check_action: the four outcomes, with the wiki stubbed out
# ---------------------------------------------------------------------------

def _stub_file(va, monkeypatch, pages):
    monkeypatch.setattr(va, "rag_file",
                        lambda base, path, **kw: pages.get(path))


def test_check_action_ok(va, monkeypatch):
    _stub_file(va, monkeypatch, {
        "API Reference/Actions/ProjectAction.md": {
            "content": "| PROJECTNAME | ... | | OpenMode | ... |",
            "source_url": "https://example.invalid/ProjectAction.html",
            "path": "API Reference/Actions/ProjectAction.md",
        }})
    res = va.check_action("https://x.invalid", "ProjectAction",
                          ["PROJECTNAME", "OpenMode"], {})
    assert res["status"] == "ok"
    assert res["doc"].endswith("ProjectAction.html")


def test_check_action_params_missing(va, monkeypatch):
    _stub_file(va, monkeypatch, {
        "API Reference/Actions/ProjectAction.md": {"content": "| PROJECTNAME |"}})
    res = va.check_action("https://x.invalid", "ProjectAction",
                          ["PROJECTNAME", "NOPE"], {})
    assert res["status"] == "params_missing"
    assert "NOPE" in res["detail"]


def test_check_action_case_mismatch(va, monkeypatch):
    _stub_file(va, monkeypatch, {
        "API Reference/Actions/ProjectAction.md": {"content": "| OpenMode |"}})
    res = va.check_action("https://x.invalid", "ProjectAction", ["OPENMODE"], {})
    assert res["status"] == "case_mismatch"
    assert "OPENMODE" in res["detail"]


def test_check_action_no_wiki_page_falls_back_to_the_official_json(va, monkeypatch):
    """An action we know about whose wiki page is missing is a wiki index gap,
    not an unknown action - and its params are then checked against the JSON."""
    _stub_file(va, monkeypatch, {})
    official = {"LockUnlockAllObjects": {
        "name": "LockUnlockAllObjects", "params": [],
        "doc_url": "https://example.invalid/LockUnlockAllObjects.html",
    }}
    res = va.check_action("https://x.invalid", "LockUnlockAllObjects", [], official)
    assert res["status"] == "no_wiki_page"
    assert "wiki index gap" in res["detail"]


def test_check_action_undocumented_when_unknown_everywhere(va, monkeypatch):
    _stub_file(va, monkeypatch, {})
    res = va.check_action("https://x.invalid", "XPrjActionProjectClose", [], {})
    assert res["status"] == "undocumented"


def test_check_action_reports_transport_errors_rather_than_raising(va, monkeypatch):
    def boom(base, path, **kw):
        raise OSError("connection reset")
    monkeypatch.setattr(va, "rag_file", boom)
    res = va.check_action("https://x.invalid", "ProjectAction", [], {})
    assert res["status"] == "error"
    assert "connection reset" in res["detail"]


# ---------------------------------------------------------------------------
# the enumeration sweep terminates and only recurses into saturated prefixes
# ---------------------------------------------------------------------------

def test_wiki_action_pages_recurses_only_into_saturated_prefixes(va, monkeypatch):
    """"ab" is saturated so its 36 children are queried; every other 2-letter
    prefix returns a short list and is never expanded."""
    asked = []

    def fake_search(base, query, top_k=20, **kw):
        asked.append(query)
        if query == "ab":
            return {"results": [
                {"path": "API Reference/Actions/Filler%d.md" % i}
                for i in range(top_k)]}
        if query == "abc":
            return {"results": [{"path": "API Reference/Actions/abcAction.md"}]}
        return {"results": []}

    monkeypatch.setattr(va, "rag_search", fake_search)
    pages, stats = va.wiki_action_pages("https://x.invalid", workers=2)

    assert "abcAction" in pages
    assert stats["saturated"] == 1
    assert stats["max_depth"] == 3, "should stop once nothing is saturated"
    # 36*36 two-letter prefixes plus exactly the 36 children of "ab".
    assert stats["queries"] == len(va.ALPHABET) ** 2 + len(va.ALPHABET)
    assert "ba" in asked and "abz" in asked


def test_wiki_action_pages_queries_seeds_too(va, monkeypatch):
    seen = []

    def fake_search(base, query, top_k=20, **kw):
        seen.append(query)
        if query == "SomeAction":
            return {"results": [{"path": "API Reference/Actions/SomeAction.md"}]}
        return {"results": []}

    monkeypatch.setattr(va, "rag_search", fake_search)
    pages, stats = va.wiki_action_pages(
        "https://x.invalid", seeds=["SomeAction"], workers=2)
    assert pages == {"SomeAction": "API Reference/Actions/SomeAction.md"}
    assert "SomeAction" in seen


def test_check_wiki_completeness_splits_known_from_wiki_only(va, monkeypatch):
    official = {"Known": {"name": "Known", "params": []},
                "GapOnly": {"name": "GapOnly", "params": []}}
    monkeypatch.setattr(
        va, "rag_file",
        lambda base, path, **kw: ({"content": ""} if "Known" in path else None))
    monkeypatch.setattr(
        va, "wiki_action_pages",
        lambda *a, **kw: ({"Known": "p", "Surprise": "p", "Foo.Enums": "p"},
                          {"queries": 3, "saturated": 0, "max_depth": 2,
                           "failed": 0, "failed_queries": []}))

    res = va.check_wiki_completeness("https://x.invalid", official, workers=2)
    assert res["known_with_page"] == ["Known"]
    assert res["known_without_page"] == ["GapOnly"]
    assert res["wiki_only"] == ["Surprise"]
    assert res["ours_only"] == ["GapOnly"]
    # A dotted page under Actions/ is a sub-page, not an action.
    assert res["non_action_pages"] == ["Foo.Enums"]
    assert res["wiki_page_count"] == 2
    assert res["sweep_failed"] == 0


# ---------------------------------------------------------------------------
# the wrapper parser still agrees with the shipped wrappers
# ---------------------------------------------------------------------------

def test_extract_wrappers_finds_the_action_docstring_line(va):
    wrappers = va.extract_wrappers()
    assert wrappers, "no wrappers parsed"
    actions = {a for _, _, a, _ in wrappers if a}
    assert "ProjectAction" in actions
    by_func = {f: p for _, f, a, p in wrappers if a == "InsertModelViewAction"}
    assert "insert_model_view" in by_func
    assert "LAYOUTSPACE" in by_func["insert_model_view"]


def test_wiki_action_pages_survives_a_failing_query(va, monkeypatch):
    """One bad query (the wiki does answer 500 under a burst) must be recorded,
    not allowed to abandon the whole enumeration."""
    calls = {"n": 0}

    def flaky(base, query, top_k=20, **kw):
        if query == "zz":
            calls["n"] += 1
            raise OSError("HTTP Error 500: Internal Server Error")
        if query == "aa":
            return {"results": [{"path": "API Reference/Actions/aaAction.md"}]}
        return {"results": []}

    monkeypatch.setattr(va, "rag_search", flaky)
    monkeypatch.setattr(va.time, "sleep", lambda *_: None)
    pages, stats = va.wiki_action_pages("https://x.invalid", workers=2)

    assert pages == {"aaAction": "API Reference/Actions/aaAction.md"}
    assert stats["failed"] == 1
    assert stats["failed_queries"] == ["zz"]
    assert calls["n"] == 2, "failed queries get exactly one serial retry"
