# MCP token cost: measurement and plan

How much context this server costs a model, where the bytes are, and which
reductions are worth doing. Every number here was measured against this repo,
not estimated.

**The headline, in one line:** in Claude Code you already pay ~1,800 tokens for
this server, not ~49,000, because the client defers tool schemas and loads them
on demand. Optimise for that reality before refactoring.

Reproduce the baseline:

```bash
python -m pytest tests/ -q          # confirm the tree is the one measured
python tools/build_action_registry.py --help   # registry provenance
```

The byte census below was taken by serialising every registered tool's name,
description and JSON schema exactly as the MCP protocol sends them, then
counting characters; tokens are chars/4.

---

# Getting EPLAN MCP token usage down — synthesis and ranked plan

**Provenance:** every headline number below was re-measured against this tree
rather than carried over from an earlier estimate. Where a figure supersedes a
previously circulated one, the correction is flagged inline.

---

## 0. Lead finding: read this before approving any refactor

**Claude Code already defers every one of these tools.** The tool schemas are not in your context. What is in context is a name-only list.

| | chars | ~tokens |
|---|---|---|
| Full tool block (what the brief priced) | 197,369 | 49,342 |
| **What Claude Code actually sends you** | **7,235** | **~1,808** |
| Already saved, for free, today | 190,134 | ~47,534 |

This is not inference. It is primary evidence from this very session: my own system prompt lists `mcp__eplan__eplan_*` as deferred, name-only, with the literal note *"Their schemas are NOT loaded."* I then called `ToolSearch` on `eplan_export_pdf_pages` and its schema arrived on demand. The client is doing schema-on-demand for you already, at **27.3× compression**.

**Consequence:** a large server-side refactor aimed at the 49,342-token figure would be optimising a number you do not pay. Before spending effort, decide which of these you are actually solving for:

- **You, in Claude Code** → upfront cost is 1,808 tok and essentially cannot go much lower. The only remaining cost is *per-schema-load* during a session. One technique below helps that. The rest do not.
- **Everyone else** (Claude Desktop, Cursor, Cline, Bedrock Converse, a proxied `ANTHROPIC_BASE_URL`, `ENABLE_TOOL_SEARCH=false`, haiku-3.x which does not support deferral) → they pay the full 49,342 tok on every request. All the work below applies to them.

If the answer is "mostly me, in Claude Code," the honest recommendation is: **do item 1, do item 2, skip the rest.** That is roughly a half-day of work, not a refactor.

### Baseline (reproduced twice, independently)

```
199 tools   197,369 chars   ~49,342 tok
  names       4,648 ( 2.4%)
  descriptions 120,935 (61.3%)
  schemas      71,786 (36.4%)
median tool 731 chars | heaviest eplan_project_management 7,333
```

The brief's 194 tools / 179,881 chars is stale — the tree gained 5 wrappers. Note also that other agents are editing this tree concurrently (8 modified, 5 untracked); treat ±1% as noise.

---

## 1. Strip pydantic schema boilerplate — **do this first**

**What:** FastMCP/pydantic auto-generates a `"title"` for all 913 schema nodes (`export_file` → `"Export File"`) and emits `"default": null` 354 times. Both are zero-information. A ~10-line post-registration loop over `mcp._tool_manager._tools[n].parameters` deletes them.

**Saving — measured by me, exactly reproducing the census figure:**

```
schema block  71,786 -> 40,518   =  31,268 chars   ~7,817 tok
new total    197,369 -> 166,101                    (-15.8%)
```

Preserves all 210 *informative* (non-null) defaults. Only 354 null defaults and 913 titles go.

**This is the one technique that helps you in Claude Code too.** I verified the boilerplate reaches the model verbatim on a `ToolSearch` load — the payload I got back contained `"title": "Black White"`, `"default": null`, and `"title": "export_pdf_pagesArguments"`. Measured per-load effect:

| tool | load before | after | cut |
|---|---|---|---|
| `eplan_export_pdf_pages` | 1,965 | 1,461 | −26% |
| `eplan_renumber_terminals` | 2,523 | 1,972 | −22% |
| `eplan_project_management` | 7,309 | 6,957 | −5% (prose-dominated) |

Average ~16% off every schema you pull mid-session.

**Effort: S.** **Usability impact: none** — this is genuinely lossless. Verified safe: `Tool` is a non-frozen pydantic model, and `Tool.run()` validates through `fn_metadata.call_fn_with_arg_validation`, *not* through `self.parameters`. Mutating that dict cannot affect execution. There is no public FastMCP knob for this in mcp 1.28.1 (`StrictJsonSchema` exists at `func_metadata.py:37` but is wired only into *output* schemas), so the loop is the way.

**Stacks with discovery mode?** Orthogonal — and I can now say why concretely rather than assert it. I read `tool_registry.py`: `eplan_tools_describe` builds its parameter payload from `inspect.signature` via `_param_records(sig)` (line 203), completely independently of `_tools[n].parameters`. Discovery's describe payloads never contained pydantic boilerplate in the first place. So the strip helps full mode and `ToolSearch` loads; it neither helps nor hinders discovery mode.

---

## 2. Delete `eplan_lock_unlock_all_objects` — a tool that cannot work

**What:** Its own docstring says it was tested and *"IT DOES NOT WORK. Every call FAILED with 'Unable to gain access to the database'."* EPLAN's 2027 index marks the action deprecated and its doc page 404s. You are shipping 2,407 chars to describe a guaranteed failure.

**Saving:** 2,407 chars / ~600 tok (~2,350 after the strip in item 1). **Effort: S.** **Usability impact: none** — removing a tool that always fails cannot degrade usability; it removes a trap.

One caveat: keep its "prefer `set_setting` / `set_project_setting`" line as a one-liner in the action catalog, so a model doesn't reach for `execute_raw_action` instead.

**Stacks with discovery mode?** Yes — one less thing to index.

---

## 3. Deduplicate genuinely repeated prose into `instructions=`

**⚠️ This is where I correct the source report.** Angle B proposed moving 18,617 chars (5 `NOT VERIFIED` banners + cross-tool duplicate lines) into FastMCP's unused `instructions=` field. Two problems I measured:

**(a) The banners are not duplicates.** I intersected all 5 banner tools: only **5 lines, 1,595 chars total**, are common. The other **11,323 chars are unique, hard-won per-tool knowledge** ("this one was tested and it does not work", "resolving via FindAction only means the name is registered"). That content is exactly the kind of thing that prevents expensive mistakes. Moving it is not deduplication, it is relocation.

**(b) In Claude Code, `instructions=` is strictly worse than a description.** Descriptions are deferred (~0 tok until loaded). `instructions=` is injected verbatim into every request (verified in the CC v2.1.259 binary: `mcp_instructions_delta`, rendered as `## <serverName>\n<instructions>`). So moving 18,617 chars there would **add ~4,650 tok/request to your bill** while saving nothing.

**Corrected saving:** only the truly duplicated text is a win — 1,595 (banner header) + 5,699 (cross-tool lines ≥30 chars in ≥3 tools; worst offender `project_name: Project path (optional)` in **45** tools) ≈ 7,294 gross, **~6,500 net** of the single retained copy. ~1,625 tok.

**Effort: M** (touches ~50 docstrings). **Usability impact: none if you move only true duplicates; real tradeoff if you move the unique banners — don't.**

**Stacks with discovery mode?** Yes for non-deferring clients. **For Claude Code it is a net negative** — skip it unless you are optimising for Desktop/Cursor users.

---

## 4. Optional: compress the 4 remaining `NOT VERIFIED` banners

**What:** Four tools (`insert_model_view`, `export_production_data_ras_center`, `export_production_data_smart_mounting`, `update_detail_engineering`) carry ~11,323 chars of untested-behaviour prose. Trim each to a ~400-char warning plus a pointer to an MCP **resource** holding the full text.

Resources are the cheapest channel in the protocol: the entire resource surface in Claude Code is two builtin tools totalling 1,133 chars — *flat, regardless of how many resources you expose* — and in this session both are themselves deferred, so the real cost is ~0.

**Saving:** ~9,300 chars / ~2,325 tok. **Effort: M.**

**Usability impact: minor tradeoff, stated bluntly.** The warning still fires at selection time; the detail becomes one fetch away. The risk is that a model ignores the pointer and uses an unverified tool as if verified. Mitigate by keeping the word `NOT VERIFIED` and the specific failure mode inline, and moving only the reasoning and retest instructions.

**Note the trend this reveals:** those 5 newest wrappers average **3,498 chars — 4.8× the 731 median**. Docstrings are growing with every commit. See item 8.

---

## 5. Safe tool consolidation — do it for hygiene, not for tokens

**What:** 12 families wrap the same EPLAN action from multiple Python functions. The risk-≤3 subset merges 19 tools away (199 → 180): dxf/dwg project + pages + import page (identical signatures — pure renames), search 5→1, typed settings 8→2, pdf/graphics/dxfdwg-scheme project+pages 2→1 each, check 3→1, and deleting `partsmanagement_export_all` (a 3-line delegation to `export(part_numbers=["*"])`).

**Saving as measured by Angle C:** 10,157 chars / ~2,539 tok.

**⚠️ Correction — this double-counts with item 1.** That figure was measured on *unstripped* schemas. I computed the boilerplate sitting inside the 19 tools consolidation deletes: **3,511 chars**, which item 1 already removes. **Net incremental saving after the strip: ~6,600 chars / ~1,650 tok.** Do not add 31,268 + 10,157.

**Effort: L.** Not just signature work — `export_pdf_project` uses `_build_action` + `_execute_with_quiet_mode` while `export_pdf_pages` hand-builds a `/PAGENAMEn:` string. Merges are implementation work too.

**Usability impact: none-to-positive for the safe set** (fewer near-identical choices; `search("renumber")` currently returns five hits). Use `Union[str,bool,int,float]` for the settings merge — measured *cheaper* than `value: str` (805 vs 851 chars) *and* it keeps client-side type validation.

**A warning this repo already proves:** `eplan_export_to_graphics` is *already* a type-enum merge. It costs 3,200 chars; the two tools it overlaps cost 2,458 combined — the merge costs **742 chars more than what it replaced**, and all three still exist. 989 chars of it is pure "how this differs from its siblings" prose that exists only because the siblings do. **A merge that does not delete the originals is a net loss.**

**Stacks with discovery mode? Largely made redundant by it.** Under discovery mode the listing cost of these families is ~0, so the token case collapses to nothing. Its remaining value is fewer wrong-tool retries and fewer describe round-trips. Pitch it as tool-surface hygiene.

---

## 6. Gate `EPLAN_MCP_EXTENSIONS` out of production sessions

**What:** private tools loaded through `EPLAN_MCP_EXTENSIONS` are counted too. On the reference setup 18 site-specific dev tools added **22,861 chars (~5,715 tok)** on top of the base server, the largest of them 4,621 chars — which would make it the #3 tool overall. Extension tools are development aids, so paying for them in production sessions is waste: load them from a separate MCP entry, or run the server in discovery mode, which indexes extension tools instead of publishing them.

**Effort: S** (an env flag you already control). **Usability impact: none for production work; you lose your dev loop when the flag is off — keep it on in dev.**

**In Claude Code this is nearly moot** — they are deferred too (~576 chars of name list, ~144 tok). This is a real 10.4% win only for non-deferring clients. Discovery mode already gates them (`server.py:349` indexes rather than publishes).

---

## 7. Where discovery mode helps — and where it hurts

Credit where due: for non-deferring clients it is by far the biggest lever — measured at 13 tools / 16,121 chars / ~4,030 tok, a **92–93% cut**, and it gates the extensions too.

**But in Claude Code specifically it is a regression, and this should not be soft-pedalled:**

1. Its own `eplan_tools_search` / `_describe` / `_call` are themselves MCP tools, so they get **deferred as well**. The path becomes `ToolSearch` → load `_search` → call → `ToolSearch` `_describe` → call: **3–4 round trips where the client natively does it in 1.**
2. It **blinds the client's own search.** Claude Code's deferral ranks over the real tool names (`tool_search_tool_regex` / `_bm25`). Hiding 190 tools behind a generic proxy removes exactly the signal that search matches on.
3. It relocates rather than deletes. The ~101,585 chars of Args blocks and prose are re-paid per `_describe`, uncached, mid-conversation.
4. Its search quality depends on lead paragraphs — which are **degenerate for precisely the biggest tools**. `eplan_project_management`'s lead is 56 chars ("Project management operations. Action: projectmanagement"); its selection-critical guidance ("to duplicate a project use CREATESNAPSHOTCOPY, not a filesystem copy") is in paragraph 2 and would not be surfaced.

**Verdict:** valuable for Desktop / Cursor / Bedrock / proxied / `ENABLE_TOOL_SEARCH=false` users. For you, it makes things slower. Item 1 stacks with it; items 3–5 are largely redundant under it.

**Free prerequisite either way:** fix the lead paragraphs of the top-20 tools so the first line says *when to use this*. Costs ~0 chars (rewrite, don't extend), improves both discovery search and the client's native ranking.

---

## 8. Add a CI ceiling on description length

**What:** fail any tool description >2,500 chars without an explicit allow-list entry.

**Saving:** 0 today; it is what stops the number climbing back. The 5 newest wrappers average 3,498 chars vs a 731 median — **the trend is the problem, not the current total.** **Effort: S. Usability impact: none.**

---

## Skip list — measured and rejected

| Idea | Why it dies |
|---|---|
| **`inspect.cleandoc()` on docstrings** | I measured it: **387 chars total**, ~97 tok across all 199 tools. The 6,987 chars of "leading indentation" is mostly *meaningful* Args-block indentation that cleandoc does not touch, and runs of spaces tokenize cheaply anyway. Not worth a commit. |
| **Drop the redundant `eplan_` prefix** | The only lever that moves the *deferring* number: 1,170 chars ≈ 16% of your 7,235-char name list. But it breaks every caller, skill, and doc for ~290 tokens. **Real tradeoff — skip unless a major version.** |
| **Merge `renumber` 5→1** | 33-param union, ~7 shared. Saves 1,645 but creates the 2nd-largest tool. `fill_gaps` with `type="DEVICES"` is **silently ignored** — the model believes it applied. Risk 4. |
| **Merge properties 6→2, print 2→1** | Properties: `property_ident_name` is SELECTION-only, silently wrong elsewhere (risk 4). Print: saves **95 chars** (23 tok) while making 5 of 10 params mode-restricted. |
| **`export` 11→1 mega-tool** | ~25-param union with two different output params. Merge on the format axis instead. |
| **Pagination (`cursor`/`nextCursor`)** | Saves **0 model tokens** — the model still sees every tool. |
| **Tool annotations (`readOnlyHint`)** | Never reach the model; not in the Messages API tool schema. 0 cost, 0 saving. |
| **Dynamic registration / `listChanged`** | A tool-set change invalidates the cached system prefix. Actively harmful. |
| **`aas_*` tools** | 4 tools, 3,994 chars (2.0%). Too small to bother. |
| **Moving unique banner prose to `instructions=`** | Costs you ~4,650 tok/request in Claude Code while saving nothing. See item 3. |

---

## Recommended sequence

**Phase 1 — do now (half a day, zero usability cost):**
1. Schema boilerplate strip → **−31,268 chars / −7,817 tok**
2. Delete `eplan_lock_unlock_all_objects` → **−2,350**
3. CI description ceiling (stops regression)
4. Rewrite top-20 lead paragraphs to say *when to use* (free, and a prerequisite for any search-based mode)

**Phase 2 — only if you care about non-Claude-Code clients:**
5. Dedupe true cross-tool repeats → −6,500
6. Compress the 4 unverified banners into a resource → −9,300 *(minor tradeoff)*
7. Gate extensions in production → −22,861 *(when applicable)*

**Phase 3 — hygiene, not tokens:**
8. Risk-≤3 merges only, and **delete the originals** → −6,600 net

**Skip:** everything in the table above.

### End state

| Scenario | Now | After Phase 1 | After Phases 1–3 |
|---|---|---|---|
| **Claude Code (deferring)** | ~1,808 tok upfront | ~1,800 upfront, **per-load −16 to −26%** | ~1,700 upfront (180 tools) |
| **Non-deferring client** | 197,369 ch / ~49,342 tok | 163,751 / ~40,938 (−17%) | **~141,500 / ~35,400 (−28%)** |
| Non-deferring + extensions | ~220,230 / ~55,057 | — | ~141,500 (extensions gated) |

**Combined realistic saving, non-deferring client: ~55,800 chars ≈ ~13,960 tokens (−28%).** That is *not* the sum of the angles (which would have read ~72,000 chars) — it nets out 3,511 chars of strip/consolidation overlap and corrects the 18,617-char dedupe claim down to ~6,500.

**Two calibration footnotes.** (a) The brief mandates chars/4; JSON schema actually tokenizes closer to chars/3, so every schema-side saving above is *understated* by roughly a third. (b) With prompt caching, the per-request dollar cost of the tool block in a non-deferring client is ~10% of face value on cache reads — but context-window occupancy is full price, which is the constraint that actually bites.

**The one-sentence answer to "are there other ways without degrading usability":** yes — one, and it is item 1. 31,268 characters of auto-generated `title` and `"default": null` that carry no information, removable in ten lines, with no docstring edits and no behaviour change. Everything beyond that either trades usability for bytes or optimises a bill your client is already not sending you.

---

# What was actually implemented

Two of the techniques above are in the tree; the rest stay as analysis.

## 1. Lossless schema strip — ON BY DEFAULT, all modes

`strip_schema_boilerplate()` in `mcp_server/server.py` runs after registration and
deletes pydantic's auto-generated `"title"` on every schema node plus every
`"default": null`. Informative defaults (`0`, `false`, `""`) are preserved.

```
full mode, titles kept   199 tools   197,369 chars   ~49,342 tokens
full mode, stripped      199 tools   166,101 chars   ~41,525 tokens   -15.8%
```

Exactly 31,268 characters, matching the prediction. It is safe because
`Tool.parameters` is only serialised out to the client — validation and dispatch
go through `Tool.fn_metadata`. A test asserts observable behaviour is identical
with and without it, so the safety argument is checked rather than asserted.
Escape hatch: `EPLAN_MCP_KEEP_SCHEMA_TITLES=1`.

**This is the only item here that also helps in Claude Code**, because it shrinks
each schema pulled on demand (~16% off a typical load) as well as the full
manifest.

## 2. Discovery mode — OPT-IN

`EPLAN_MCP_MODE=discovery` publishes 13 tools instead of 199:

```
full        199 tools   166,101 chars   ~41,525 tokens
discovery    13 tools    13,214 chars   ~3,303 tokens   -93.3%
```

Default remains `full`. In Claude Code discovery mode is a **regression** — the
client already defers schemas, so it would trade a ~1,800-token baseline for
extra round-trips and blind the client's own name-based search. Turn it on for
clients that do not defer: Claude Desktop, Cursor, Cline, Bedrock, or any direct
Messages API integration.

## Not done, deliberately

- **Deleting `eplan_lock_unlock_all_objects`** (item 2 in the plan). The owner
  asked for licence-blocked and broken wrappers to ship *marked*, not removed, so
  it stays with a `NOT VERIFIED` block that says plainly that it was tested and
  fails.
- Tool consolidation, shorter names, `instructions=` relocation, pagination — see
  the skip list above for why each was rejected.
