"""
Pin the counts ACTION_COVERAGE.md quotes to the data files it cites.

Why this exists: the doc's headline numbers were transcribed by hand from a
probe run, then the probe was re-run and the JSON moved on without the prose.
The result was a document that contradicted the data sitting next to it (doc
said 1148 probed / 937 resolved / 211 unresolved; the JSON said 1150 / 938 /
212) and a tool docstring - which the MODEL reads at runtime - repeating the
stale figure. A reader had no way to tell which was authoritative.

So: any number the doc states about the registry or the probe must be derivable
from the committed JSON. If someone regenerates the data and forgets the prose,
this fails and names the number to fix.

Runs with EPLAN closed - it only reads files.
"""

import io
import json
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)

COVERAGE_MD = os.path.join(SERVER, "ACTION_COVERAGE.md")
LIVE_ACTIONS = os.path.join(SERVER, "tools", "data", "live_actions_2027.json")
REGISTRY = os.path.join(
    SERVER, "mcp_server", "api", "actions", "data", "action_registry.json"
)


def _read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _json(path):
    return json.loads(_read(path))


@pytest.fixture(scope="module")
def doc():
    return _read(COVERAGE_MD)


@pytest.fixture(scope="module")
def probe_meta():
    return _json(LIVE_ACTIONS)["_meta"]


@pytest.fixture(scope="module")
def registry_counts():
    return _json(REGISTRY)["_meta"]["counts"]


def test_probe_and_registry_agree_with_each_other(probe_meta, registry_counts):
    """The two data files are generated from one run; they must not disagree."""
    assert probe_meta["probed"] == registry_counts["total"]
    assert probe_meta["resolved"] == registry_counts["live_resolved"]
    assert probe_meta["unresolved"] == registry_counts["live_unresolved"]


def test_probe_counts_are_self_consistent(probe_meta):
    assert probe_meta["resolved"] + probe_meta["unresolved"] <= probe_meta["probed"]


def test_doc_states_the_real_probed_total(doc, probe_meta):
    probed = probe_meta["probed"]
    assert "all %d candidate" % probed in doc, (
        "ACTION_COVERAGE.md should say 'all %d candidate names' to match "
        "live_actions_2027.json's _meta.probed" % probed
    )


def test_doc_states_the_real_resolved_and_unresolved(doc, probe_meta):
    assert "**%d resolve**" % probe_meta["resolved"] in doc
    assert "- %d do not" % probe_meta["unresolved"] in doc


def test_doc_registry_total_matches_the_registry(doc, registry_counts):
    assert "**%d**" % registry_counts["total"] in doc


def test_doc_does_not_quote_a_stale_probe_number(doc, probe_meta):
    """
    Catch the specific drift that happened: the previous run's numbers left
    behind in the prose. Any 3-4 digit number in the 900-1200 band that is not
    one the data files justify is almost certainly a leftover.
    """
    allowed = {
        str(probe_meta["probed"]),
        str(probe_meta["resolved"]),
        str(probe_meta["unresolved"]),
    }
    # Numbers the doc legitimately cites from other sources (inventory table).
    allowed |= {"1019", "1049", "1150", "1000"}
    stale = set()
    for match in re.findall(r"\b(9\d\d|1[01]\d\d)\b", doc):
        if match not in allowed:
            stale.add(match)
    assert not stale, (
        "ACTION_COVERAGE.md quotes number(s) %s that no committed data file "
        "justifies - probe was re-run without updating the prose?"
        % sorted(stale)
    )


def test_doc_does_not_disclose_a_licence_tier(doc):
    """
    The doc is published. Naming the licence tier, asserting what the
    subscription does or does not cover, or naming a vendor add-on as not
    owned, together describe the maintainer's purchasing footprint - which is
    company information and is not needed to explain action coverage.
    """
    for tier in ("Premium", "Professional", "Compact", "Select"):
        assert "2027.0.1 %s" % tier not in doc, (
            "ACTION_COVERAGE.md names the '%s' licence tier; say the version "
            "only" % tier
        )
    assert "outside this subscription" not in doc
    assert "not installed)" not in doc, (
        "describe a gap by mechanism ('an add-on not present on the reference "
        "installation'), not by naming a vendor product as un-owned"
    )


def test_doc_does_not_hardcode_a_test_count(doc):
    """
    '411 passed, 2 skipped' was wrong by 179 tests. A count that changes on
    every commit does not belong in prose; the suite reports it.
    """
    assert not re.search(r"\b\d{3,4} passed\b", doc), (
        "ACTION_COVERAGE.md hardcodes a pytest pass count; it goes stale on "
        "the next commit - describe what the suite covers instead"
    )


def test_catalog_docstring_does_not_hardcode_the_probe_result():
    """
    catalog.py's docstring is read by the MODEL at runtime, so a stale number
    there is worse than one in a human-facing doc.
    """
    src = _read(
        os.path.join(SERVER, "mcp_server", "api", "actions", "catalog.py")
    )
    doc_start = src.index("available_only:")
    doc_end = src.index("limit:", doc_start)
    section = src[doc_start:doc_end]
    assert not re.search(r"\bonly \d{3,4} resolved\b", section), (
        "catalog.action_catalog's available_only docstring hardcodes the probe "
        "result; point at the registry's _meta.counts instead"
    )
