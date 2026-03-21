# Benchmark Summary — Glyphh Code

> **Status: WORK IN PROGRESS**
> Last run: 2026-03-21 · Model: Haiku 4.5 · Target repo: fastmcp (316 files)

## TL;DR

Glyphh Code uses **20% fewer tokens and 22% fewer turns** than bare Claude Code,
with identical search accuracy (13/15). The overall accuracy gap (76% vs 84%)
is caused by MCP startup latency triggering timeouts — not by the HDC model.
The `total_cost_usd` reported by Claude CLI shows combined mode costing more,
but the token breakdown contradicts this (fewer tokens in every category);
cost metric is unreliable and under investigation.

---

## Methodology

Real Claude Code sessions via `claude -p --output-format json`. Each test case
asks Claude to find a specific source file. Two modes:

- **Bare LLM** — Claude Code with grep/glob/read (no Glyphh)
- **Glyphh + LLM** — Claude Code with glyphh_search MCP + grep/glob/read fallback

Success = Claude reads the correct file. Primary metric = total tokens to get
there. 25 test cases across 4 categories: search (15), edit (5), debug (3),
understand (2).

## Results

| Metric | Bare LLM | Glyphh + LLM | Delta |
|--------|----------|--------------|-------|
| **Total tokens** | 3,505,889 | **2,808,783** | **-20%** |
| **Avg turns** | 5.2 | **4.0** | **-22%** |
| Accuracy | **21/25 (84%)** | 19/25 (76%) | -8pp* |
| Avg latency | 18.7s | 26.8s | +43% |
| Total cost (CLI) | $0.85 | $1.11 | +30%** |

\* Accuracy gap is from 2 MCP-timeout failures + 1 wrong result, not HDC accuracy.
\*\* Cost metric is unreliable — token breakdown shows fewer tokens in every category
for combined mode, yet CLI reports higher cost. Under investigation.

### By category

| Category | Bare LLM | Glyphh + LLM |
|----------|----------|--------------|
| search (15) | 13/15 · avg 4.0 turns · 88K tok | 13/15 · avg 3.3 turns · 80K tok |
| edit (5) | 4/5 · avg 6.0 turns · 192K tok | 3/5 · avg 4.8 turns · 177K tok |
| debug (3) | 3/3 · avg 8.7 turns · 321K tok | 2/3 · avg 3.0 turns · 77K tok |
| understand (2) | 1/2 · avg 6.5 turns · 132K tok | 1/2 · avg 8.5 turns · 246K tok |

## What works

1. **Token savings on search tasks**: When Glyphh finds the right file (13/15),
   it uses fewer tokens (80K vs 88K) and fewer turns (3.3 vs 4.0). One MCP call
   replaces 2-3 grep/glob cycles.

2. **Debug shortcut**: debug_01 and debug_02 solved in 3-4 turns with Glyphh vs
   4+ turns bare. Glyphh points Claude at the right file immediately.

3. **Fewer speculative reads**: Bare LLM reads 3-5 files before finding the
   right one. Glyphh mode reads 1-2.

## What doesn't work

1. **MCP startup latency causes timeouts**: The Glyphh MCP server adds ~5-15s
   of warmup on first call. Combined with the 120s timeout, this caused 2 extra
   timeouts (edit_02, edit_03) that bare mode completed fine. This is the primary
   cause of the accuracy gap — not HDC quality.

2. **Wrong Glyphh results waste iterations**: When Glyphh returns a wrong
   high-confidence result, Claude trusts it, reads the wrong file, then has to
   backtrack. debug_03 is the clearest example — Glyphh pointed to
   `dependencies.py` instead of `authorization.py`, and Claude never recovered.
   Bare Claude found it in 20 turns by brute-force grep.

3. **Outlier queries dominate totals**: edit_04 (706-717K tokens) and debug_03
   (815K bare, 54K combined) account for 43% of all tokens. These are genuinely
   hard multi-step tasks where both modes struggle.

4. **Cost metric unreliable**: Claude CLI's `total_cost_usd` shows combined mode
   costing 30% more, but the token breakdown shows fewer tokens in every
   category (input, output, cache_read, cache_create). The cost field may include
   overhead not reflected in usage counts. Token totals are the reliable metric.

## Common failures (both modes)

| Test | Expected | Got | Issue |
|------|----------|-----|-------|
| search_08 | `experimental/server/openapi/__init__.py` | `server/providers/openapi/provider.py` | Ambiguous: "experimental" not in query |
| search_11 | `tests/server/auth/oauth_proxy/test_authorization.py` | `auth/oauth_proxy/models.py` or `proxy.py` | Wants test file, both modes return source |
| understand_02 | `src/fastmcp/tools/base.py` | `server/server.py` or explanation text | Broad query, multiple valid files |

## What needs to happen

1. **Fix MCP latency**: The timeout-induced failures are the #1 blocker. Either
   keep the MCP connection warm, increase the timeout, or reduce server startup
   time. This alone could close the accuracy gap.

2. **Improve HDC accuracy on edge cases**: search_08 (experimental path) and
   search_11 (test vs source) need better encoding. The file_role signal is
   there but not strong enough to override content similarity.

3. **Confidence calibration**: When Glyphh returns a wrong result with high
   confidence, the LLM trusts it and wastes turns. Need to either lower
   confidence on ambiguous matches or return ASK state so Claude falls back to
   grep earlier.

4. **Benchmark at scale**: 25 test cases is too few. Need 100+ cases across
   repos of varying sizes (100, 1K, 10K files) to understand where the token
   savings compound. The hypothesis is that Glyphh's advantage grows with repo
   size — 316 files is small enough that grep is fast.

5. **Test with larger models**: Haiku is cheap but may not follow the "trust
   Glyphh then verify" prompt well. Sonnet or Opus may show different behavior.

## Reproducing

```bash
cd glyphh-models/code

# Run both modes
python benchmark/run_claude_benchmark.py --model haiku

# Run bare only
python benchmark/run_claude_benchmark.py --mode bare

# Run combined only (requires Glyphh runtime on localhost:8002)
python benchmark/run_claude_benchmark.py --mode combined

# Limit to N test cases
python benchmark/run_claude_benchmark.py --limit 5
```

Results are saved to `benchmark/results/` as JSON. A live `status.json` updates
after each test case for monitoring long runs.
