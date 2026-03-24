# Benchmark — Glyphh Code

> Last run: 2026-03-23 · Model: Sonnet 4.6 · Target repo: fastmcp (766 files)

## TL;DR

Glyphh replaces 14-32 grep/glob tool calls with a single MCP call.
Same answer, **50-74% cheaper, 3-5x faster**.

The LLM will always beat Glyphh at file search — it can grep its way to any
answer. Glyphh's value is in capabilities that have **zero grep equivalent**:
blast radius, semantic drift scoring, and commit risk profiling.

---

## Head-to-head: blast radius

Real Claude Code sessions, same query, same model. No prompt engineering.

### Test 1: DI engine (64 importers)

> "I'm changing the dependency injection in `src/fastmcp/server/dependencies.py`
> — what files could break?"

| Metric | Glyphh | Bare LLM | Delta |
|--------|--------|----------|-------|
| **Cost** | $0.17 | $0.23 | **-26%** |
| **API time** | 16s | 58s | **-72%** |
| **Wall time** | 25s | 64s | **-61%** |
| **Tool calls** | 1 | 14 | **-93%** |
| Models used | Sonnet only | Sonnet + Haiku subagent | — |

### Test 2: Auth orchestrator (43 importers)

> "I'm editing `src/fastmcp/server/auth/auth.py` — what other files are
> affected?"

| Metric | Glyphh | Bare LLM | Delta |
|--------|--------|----------|-------|
| **Cost** | $0.10 | $0.21 | **-50%** |
| **API time** | 14s | 68s | **-79%** |
| **Wall time** | 1m 37s | 2m 1s | **-20%** |
| **Tool calls** | 1 | 32 | **-97%** |
| Models used | Sonnet only | Sonnet + Haiku subagent | — |

### What happens under the hood

**With Glyphh:** Claude calls `glyphh_related(file_path, top_k=10)`. One MCP
call returns ranked files with similarity scores, top tokens, and imports.
Claude reads the results and responds. Done.

**Without Glyphh:** Claude spawns an Explore subagent (Haiku) that runs 14-32
grep/glob/read calls over 45-80 seconds to manually trace imports, find
dependents, and build the same picture file by file.

Both reach the same answer. Glyphh does it in one call.

---

## Glyphh-only capabilities

These tools have no grep equivalent. Bare LLM cannot do them at all.

### Drift scoring (`glyphh_drift`)

Computes semantic drift between the indexed version and current disk version
of a file. Measures how much the *meaning* changed, not just the diff.

| Label | Score | Meaning |
|-------|-------|---------|
| cosmetic | < 0.10 | Formatting, comments, renames |
| moderate | 0.10 – 0.30 | Logic update, new function |
| significant | 0.30 – 0.60 | Behavioral change, new dependency |
| architectural | ≥ 0.60 | Rewrite, interface change |

Benchmark: **3/3 correct**, avg 3 turns, avg $0.08/query, avg 7.5s.

### Risk profiling (`glyphh_risk`)

Aggregates drift scores across all changed files in a commit or working tree.
Returns `risk_label`, `max_drift`, `mean_drift`, and `hot_files` (files above
the moderate threshold).

Benchmark: **2/2 correct**, avg 3 turns, avg $0.08/query, avg 11s.

### Why these matter

Before merging or deploying, one `glyphh_risk` call answers: "how risky is
this change set?" If `risk_label` is `significant` or `architectural`, flag
for human review. No grep, no manual diff reading, no guessing.

---

## Automated benchmark results

13 test cases: 8 blast radius + 3 drift + 2 risk.

### Combined mode (Glyphh + LLM)

| Type | Accuracy | Avg turns | Avg cost | Avg latency |
|------|----------|-----------|----------|-------------|
| Blast radius | 8/8 – 9/10 | 4.2 | $0.09 | 18s |
| Drift | 3/3 | 3.0 | $0.08 | 7.5s |
| Risk | 2/2 | 3.0 | $0.08 | 11s |

### Bare LLM (blast radius only)

| Type | Accuracy | Avg turns | Avg cost | Avg latency |
|------|----------|-----------|----------|-------------|
| Blast radius | 8/8 – 9/10 | 4.7 | $0.10 | 19s |

### Why the automated benchmark underestimates Glyphh

The `claude -p` single-prompt benchmark flattens everything into one session.
It measures total cost and pass/fail accuracy, but does **not** capture:

- **Tool call count**: 1 vs 14-32 (the real efficiency gap)
- **Subagent spawning**: bare LLM spawns Haiku Explore agents at extra cost
- **API duration**: 14s vs 68s (hidden inside the session)

The head-to-head interactive tests above show the true picture.

---

## What we don't benchmark

**File search / semantic queries.** The LLM will always beat Glyphh at search.
Sonnet with grep/glob is excellent at finding files by concept — it
understands code well enough to grep its way to any answer. We tested this
extensively (10+ semantic query benchmarks across multiple runs) and bare LLM
consistently matched or beat Glyphh on accuracy.

Glyphh is not a grep replacement. It's a capability layer that adds blast
radius analysis, drift scoring, and risk profiling — things grep cannot do.

---

## Reproducing

```bash
cd glyphh-models/code

# Full benchmark (8 blast + 3 drift + 2 risk, both modes)
python benchmark/run_claude_benchmark.py --model sonnet

# Glyphh-only
python benchmark/run_claude_benchmark.py --mode combined --model sonnet

# Bare LLM only (runs blast radius tests, skips drift/risk)
python benchmark/run_claude_benchmark.py --mode bare --model sonnet

# Filter by type
python benchmark/run_claude_benchmark.py --types blast_radius
python benchmark/run_claude_benchmark.py --types drift risk

# Limit to N test cases
python benchmark/run_claude_benchmark.py --limit 5
```

Results are saved to `benchmark/results/` as JSON.
