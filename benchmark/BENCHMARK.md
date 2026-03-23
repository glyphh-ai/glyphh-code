# Benchmark Summary — Glyphh Code

> Last run: 2026-03-23 · Model: Sonnet 4.6 · Target repo: fastmcp (766 files)

## TL;DR

On automated benchmarks, Glyphh + LLM matches bare LLM on accuracy (85%)
and cost ($2.14 vs $2.14). Navigation is 7% cheaper on tokens. Semantic
queries win on accuracy (4/5 vs 3/5) at equal cost. Blast radius is tied.

The real advantage shows in interactive sessions: a manual blast radius
query ("edit proxy.py, what else might break?") costs **$0.16 with Glyphh
vs $0.28 without** (43% cheaper, 5x faster, 1 tool call vs 36).

---

## Methodology

Real Claude Code sessions via `claude -p --output-format json`. Two modes:

- **Bare LLM** — Claude Code with grep/glob/read (no Glyphh)
- **Glyphh + LLM** — Claude Code with Glyphh MCP tools + grep/glob/read

20 test cases across 3 categories:
- **Navigation** (10) — find a specific file by concept. Grep's strength.
- **Blast radius** (5) — "what breaks if I edit X?" Glyphh's strength.
- **Semantic** (5) — conceptual queries with no exact string match.

Success criteria:
- Navigation: Claude reads the correct file (first-line path match).
- Blast radius: response mentions N+ of the expected affected files.
- Semantic: response mentions 1+ of the expected relevant files.

## Results (Sonnet 4.6, 2026-03-23)

### Overall

| Metric | Glyphh + LLM | Bare LLM | Delta |
|--------|-------------|----------|-------|
| Accuracy | 17/20 (85%) | 17/20 (85%) | tied |
| Avg tokens | 67,766 | 65,926 | -3% |
| Avg turns | 4.2 | 3.9 | -8% |
| Avg latency | 16.2s | 14.5s | -12% |
| Total cost | $2.14 | $2.14 | tied |

### By category

| Category | Glyphh + LLM | Bare LLM | Token delta | Cost delta |
|----------|-------------|----------|-------------|------------|
| **Navigation** (10) | 9/10 · 2.7 turns · 51.7K tok | **10/10** · 3.1 turns · 55.6K tok | **+7% better** | **+1% better** |
| **Blast radius** (5) | 4/5 · 4.8 turns · 65.0K tok | 4/5 · 4.0 turns · 64.2K tok | ~tied | ~tied |
| **Semantic** (5) | **4/5** · 6.6 turns · 102.6K tok | 3/5 · 5.4 turns · 88.3K tok | -16% | **+2% better** |

## What works

1. **Navigation token savings**: Glyphh finds files in fewer turns (2.7 vs 3.1)
   and 7% fewer tokens. One MCP call replaces 2-3 grep/glob cycles.

2. **Semantic accuracy**: Glyphh finds auth middleware chain (semantic_02) that
   bare Claude misses entirely. Conceptual queries are Glyphh's natural advantage.

3. **Cost parity**: Updated tool descriptions stopped Claude from over-using
   `glyphh_search` for navigation. Cost is now dead even ($2.14 vs $2.14),
   improved from -29% penalty in earlier versions.

4. **Interactive blast radius**: Manual testing shows the real gap — $0.16 vs
   $0.28 (43% cheaper, 5x faster) on "edit X, what else might break?" queries.
   The automated benchmark underestimates this because its directed prompt lets
   bare Claude grep imports mechanically.

## What doesn't work

1. **Blast radius is tied in benchmarks**: The directed prompt ("what files are
   affected if I change X?") lets bare Claude `grep -r "from.*X import"` and
   find dependents mechanically. In interactive sessions, the open-ended question
   forces bare Claude to spawn an Explore agent (36 tool calls, 2 minutes).

2. **MCP response payload overhead**: Each `glyphh_search` call injects ~20K
   tokens of JSON (fact_tree, top_tokens, imports for every match). For semantic
   queries this shows as -16% more tokens despite better accuracy. The new
   `detail="minimal"` parameter (v0.4.4) addresses this but hasn't been
   benchmarked yet.

3. **One nav regression**: nav_09 ("function tool decorator and registration")
   returned a provider decorator file instead of `function_tool.py`. The symbols
   layer matched "decorator" in both files.

## Common failures (both modes)

| Test | Expected | Issue |
|------|----------|-------|
| blast_03 | SSE transport siblings | Both find `__init__.py` and `inference.py` instead of `streamable_http.py` and `stdio.py` |
| semantic_01 | OAuth proxy/auth files for "webhook validation" | Both return authorization middleware — query is ambiguous |

## Previous results

### Haiku 4.5 (2026-03-21, old benchmark with forced glyphh_search)

| Metric | Bare LLM | Glyphh + LLM | Delta |
|--------|----------|--------------|-------|
| Total tokens | 3,505,889 | 2,808,783 | -20% |
| Avg turns | 5.2 | 4.0 | -22% |
| Accuracy | 21/25 (84%) | 19/25 (76%) | -8pp |
| Total cost | $0.85 | $1.11 | +30% |

The old benchmark forced `glyphh_search` for all queries (including navigation).
This inflated cost due to MCP payload overhead. The current benchmark lets Claude
choose the right tool for each task.

### Sonnet 4.6 (2026-03-22, forced glyphh_search)

| Metric | Bare LLM | Glyphh + LLM | Delta |
|--------|----------|--------------|-------|
| Accuracy | 19/25 (76%) | **22/25 (88%)** | +12pp |
| Avg tokens | 60,238 | 77,535 | -29% |
| Total cost | $2.48 | $3.21 | -29% |

Higher accuracy with Glyphh but significantly more expensive due to forced
`glyphh_search` on every query.

## Next steps

1. **Benchmark `detail="minimal"`**: The v0.4.4 parameter strips top_tokens,
   imports, and extension from responses (~15K fewer tokens per call). Expected
   to close the token gap on semantic queries.

2. **Larger repos**: 766 files is small enough that grep is fast. The hypothesis
   is that Glyphh's advantage grows with repo size (5K+ files) where grep
   becomes expensive. Need to test on a 5K-10K file repo.

3. **Interactive benchmark**: The automated benchmark doesn't capture wall time
   savings or the Explore-agent pattern that makes Glyphh's blast radius
   advantage so large in practice. Need a benchmark that measures real
   interactive sessions.

## Reproducing

```bash
cd glyphh-models/code

# Run both modes (default: haiku)
python benchmark/run_claude_benchmark.py --model sonnet

# Run bare only
python benchmark/run_claude_benchmark.py --mode bare --model sonnet

# Run combined only (requires Glyphh runtime on localhost:8002)
python benchmark/run_claude_benchmark.py --mode combined --model sonnet

# Filter by test type
python benchmark/run_claude_benchmark.py --types blast_radius semantic

# Limit to N test cases
python benchmark/run_claude_benchmark.py --limit 5
```

Results are saved to `benchmark/results/` as JSON. A live `status.json` updates
after each test case for monitoring long runs.
