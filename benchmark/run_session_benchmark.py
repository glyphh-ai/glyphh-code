#!/usr/bin/env python3
"""
Benchmark: Session write/recall HDC encoding accuracy.

Measures how well the session encoder preserves and retrieves
notes from a simulated coding session.  No database — encodes
notes and queries in-memory, scores with the same layer-weighted
cosine used by _handle_session_recall.

Metrics:
  Recall@1   — correct note ranks first
  Recall@3   — correct note in top 3
  MRR        — mean reciprocal rank
  Precision  — top-1 score > threshold AND correct
  Abstention — adversarial queries score below threshold

Categories:
  clear          — unambiguous single-note queries
  near_collision — queries that could match multiple notes
  context_recall — queries targeting file paths or code symbols
  adversarial    — out-of-scope or keyword-stuffing queries

Usage:
    python benchmark/run_session_benchmark.py
    python benchmark/run_session_benchmark.py --verbose
    python benchmark/run_session_benchmark.py --threshold 0.15
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "glyphh-runtime"))

from glyphh_code.encoder import (
    SESSION_ENCODER_CONFIG,
    _encode_session_concept,
    _get_session_encoder,
    _session_score,
)

BENCHMARK_DIR = Path(__file__).parent
QUERIES_PATH = BENCHMARK_DIR / "session_queries.json"


# ═══════════════════════════════════════════════════════════════
# Benchmark runner
# ═══════════════════════════════════════════════════════════════

def run_benchmark(threshold: float, verbose: bool) -> dict:
    data = json.loads(QUERIES_PATH.read_text())

    encoder = _get_session_encoder()

    # Phase 1: Encode all notes
    print(f"\n{'='*60}")
    print(f"  Session Benchmark — {len(data['notes'])} notes, threshold={threshold:.2f}")
    print(f"  Encoder: dim={SESSION_ENCODER_CONFIG.dimension}, seed={SESSION_ENCODER_CONFIG.seed}")
    print(f"  Scoring: adaptive weights (0.60/0.40 when context present, 1.0/0.0 otherwise)")
    print(f"{'='*60}\n")

    t0 = time.perf_counter()
    note_glyphs = {}
    note_contents = {}
    for note in data["notes"]:
        concept = _encode_session_concept(note["content"], note["label"])
        glyph = encoder.encode(concept)
        note_glyphs[note["label"]] = glyph
        note_contents[note["label"]] = note["content"]
    encode_ms = (time.perf_counter() - t0) * 1000
    print(f"  Encoded {len(note_glyphs)} notes in {encode_ms:.1f}ms "
          f"({encode_ms / len(note_glyphs):.1f}ms/note)\n")

    # Phase 2: Score all queries
    categories = {}
    all_results = []

    for cat_name, queries in data["queries"].items():
        cat_results = []

        for q in queries:
            query_text = q["query"]
            expected = q.get("expected")

            t1 = time.perf_counter()
            concept = _encode_session_concept(query_text, "query")
            query_glyph = encoder.encode(concept)

            scores = []
            for label, note_glyph in note_glyphs.items():
                s = _session_score(query_glyph, note_glyph, query_text, note_contents[label])
                scores.append({"label": label, **s})

            scores.sort(key=lambda x: x["combined"], reverse=True)
            query_ms = (time.perf_counter() - t1) * 1000

            top1 = scores[0]
            top1_correct = (top1["label"] == expected) if expected else None

            # Find rank of expected note (1-indexed, None if not expected)
            rank = None
            if expected:
                for i, s in enumerate(scores):
                    if s["label"] == expected:
                        rank = i + 1
                        break

            result = {
                "query": query_text,
                "expected": expected,
                "category": cat_name,
                "top1_label": top1["label"],
                "top1_score": top1["combined"],
                "top1_content": top1["content"],
                "top1_context": top1["context"],
                "top1_correct": top1_correct,
                "expected_rank": rank,
                "above_threshold": top1["combined"] >= threshold,
                "query_ms": query_ms,
                "top3": [s["label"] for s in scores[:3]],
                "all_scores": scores,
            }

            cat_results.append(result)
            all_results.append(result)

        categories[cat_name] = cat_results

    # Phase 3: Compute metrics
    print_results(categories, threshold, verbose)

    metrics = compute_metrics(categories, threshold)
    metrics["encode_ms"] = encode_ms
    metrics["threshold"] = threshold
    metrics["num_notes"] = len(note_glyphs)

    return metrics


def compute_metrics(categories: dict, threshold: float) -> dict:
    """Compute aggregate metrics across all categories."""
    metrics = {"categories": {}}

    # Per-category metrics
    for cat_name, results in categories.items():
        cat_metrics = {}

        if cat_name == "adversarial":
            # For adversarial: measure abstention rate (top1 < threshold)
            abstained = sum(1 for r in results if not r["above_threshold"])
            cat_metrics["abstention_rate"] = abstained / len(results) if results else 0
            cat_metrics["count"] = len(results)
        else:
            # For recall categories: Recall@1, Recall@3, MRR
            recall_1 = sum(1 for r in results if r["top1_correct"]) / len(results) if results else 0
            recall_3 = sum(1 for r in results if r["expected_rank"] and r["expected_rank"] <= 3) / len(results) if results else 0
            mrr = sum(1.0 / r["expected_rank"] for r in results if r["expected_rank"]) / len(results) if results else 0

            # Precision: correct AND above threshold
            precise = sum(1 for r in results if r["top1_correct"] and r["above_threshold"])
            precision = precise / len(results) if results else 0

            cat_metrics["recall_at_1"] = recall_1
            cat_metrics["recall_at_3"] = recall_3
            cat_metrics["mrr"] = mrr
            cat_metrics["precision"] = precision
            cat_metrics["count"] = len(results)

        metrics["categories"][cat_name] = cat_metrics

    # Aggregate (excluding adversarial)
    recall_cats = [c for c in categories if c != "adversarial"]
    all_recall = [r for c in recall_cats for r in categories[c]]
    if all_recall:
        metrics["overall_recall_at_1"] = sum(1 for r in all_recall if r["top1_correct"]) / len(all_recall)
        metrics["overall_recall_at_3"] = sum(1 for r in all_recall if r["expected_rank"] and r["expected_rank"] <= 3) / len(all_recall)
        metrics["overall_mrr"] = sum(1.0 / r["expected_rank"] for r in all_recall if r["expected_rank"]) / len(all_recall)

    return metrics


def print_results(categories: dict, threshold: float, verbose: bool):
    """Print formatted benchmark results."""

    for cat_name, results in categories.items():
        is_adversarial = cat_name == "adversarial"
        icon = "◆" if is_adversarial else "●"
        print(f"  {icon} {cat_name} ({len(results)} queries)")
        print(f"  {'─'*56}")

        for r in results:
            correct = r["top1_correct"]
            if is_adversarial:
                status = "✗ MATCHED" if r["above_threshold"] else "✓ ABSTAINED"
            else:
                status = "✓" if correct else "✗"

            score_str = f"{r['top1_score']:.3f}"
            rank_str = f"rank={r['expected_rank']}" if r["expected_rank"] else ""

            line = f"    {status} [{score_str}] {r['query'][:45]:<45}"
            if not correct and not is_adversarial:
                line += f"  got={r['top1_label']}"
            if rank_str and not correct:
                line += f"  {rank_str}"
            print(line)

            if verbose:
                print(f"         content={r['top1_content']:.3f}  context={r['top1_context']:.3f}")
                if not is_adversarial:
                    # Show expected note's scores
                    for s in r["all_scores"]:
                        if s["label"] == r["expected"]:
                            print(f"         expected: combined={s['combined']:.3f}  "
                                  f"content={s['content']:.3f}  context={s['context']:.3f}")
                            break
                print(f"         top3: {', '.join(r['top3'])}")

        print()

    # Summary table
    print(f"  {'='*60}")
    print(f"  SUMMARY (threshold={threshold:.2f})")
    print(f"  {'─'*60}")
    print(f"  {'Category':<20} {'Recall@1':>10} {'Recall@3':>10} {'MRR':>10} {'Count':>6}")
    print(f"  {'─'*60}")

    for cat_name, results in categories.items():
        if cat_name == "adversarial":
            abstained = sum(1 for r in results if not r["above_threshold"])
            rate = abstained / len(results) if results else 0
            print(f"  {cat_name:<20} {'abstain':>10} {rate:>10.1%} {'':>10} {len(results):>6}")
        else:
            r1 = sum(1 for r in results if r["top1_correct"]) / len(results)
            r3 = sum(1 for r in results if r["expected_rank"] and r["expected_rank"] <= 3) / len(results)
            mrr = sum(1.0 / r["expected_rank"] for r in results if r["expected_rank"]) / len(results)
            print(f"  {cat_name:<20} {r1:>10.1%} {r3:>10.1%} {mrr:>10.3f} {len(results):>6}")

    # Overall
    recall_cats = [c for c in categories if c != "adversarial"]
    all_recall = [r for c in recall_cats for r in categories[c]]
    if all_recall:
        r1 = sum(1 for r in all_recall if r["top1_correct"]) / len(all_recall)
        r3 = sum(1 for r in all_recall if r["expected_rank"] and r["expected_rank"] <= 3) / len(all_recall)
        mrr = sum(1.0 / r["expected_rank"] for r in all_recall if r["expected_rank"]) / len(all_recall)
        print(f"  {'─'*60}")
        print(f"  {'OVERALL':<20} {r1:>10.1%} {r3:>10.1%} {mrr:>10.3f} {len(all_recall):>6}")

    print(f"  {'='*60}\n")


# ═══════════════════════════════════════════════════════════════
# Gap analysis — score distribution diagnostics
# ═══════════════════════════════════════════════════════════════

def print_gap_analysis(categories: dict):
    """Show score distributions and gap between top-1 and top-2."""
    print(f"\n  {'='*60}")
    print(f"  GAP ANALYSIS")
    print(f"  {'─'*60}")
    print(f"  {'Query':<35} {'Top1':>7} {'Top2':>7} {'Gap':>7} {'Status':<8}")
    print(f"  {'─'*60}")

    for cat_name, results in categories.items():
        if cat_name == "adversarial":
            continue
        for r in results:
            top1 = r["all_scores"][0]["combined"]
            top2 = r["all_scores"][1]["combined"] if len(r["all_scores"]) > 1 else 0
            gap = top1 - top2
            status = "✓" if r["top1_correct"] else "✗"
            query_short = r["query"][:33]
            print(f"  {query_short:<35} {top1:>7.3f} {top2:>7.3f} {gap:>7.3f} {status:<8}")

    print(f"  {'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Session write/recall HDC benchmark")
    parser.add_argument("--threshold", type=float, default=0.12,
                        help="Minimum score to consider a match (default: 0.12)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show per-query layer scores and top-3")
    parser.add_argument("--gap", action="store_true",
                        help="Show gap analysis between top-1 and top-2 scores")
    parser.add_argument("--save", type=str, default=None,
                        help="Save results JSON to path")
    args = parser.parse_args()

    metrics = run_benchmark(args.threshold, args.verbose)

    if args.gap:
        # Re-run to get categories for gap analysis (metrics doesn't store all_scores)
        data = json.loads(QUERIES_PATH.read_text())
        encoder = _get_session_encoder()
        note_glyphs = {}
        note_contents = {}
        for note in data["notes"]:
            concept = _encode_session_concept(note["content"], note["label"])
            note_glyphs[note["label"]] = encoder.encode(concept)
            note_contents[note["label"]] = note["content"]

        categories = {}
        for cat_name, queries in data["queries"].items():
            cat_results = []
            for q in queries:
                concept = _encode_session_concept(q["query"], "query")
                query_glyph = encoder.encode(concept)
                scores = []
                for label, ng in note_glyphs.items():
                    s = _session_score(query_glyph, ng, q["query"], note_contents[label])
                    scores.append({"label": label, **s})
                scores.sort(key=lambda x: x["combined"], reverse=True)
                cat_results.append({
                    "query": q["query"],
                    "expected": q.get("expected"),
                    "top1_correct": scores[0]["label"] == q.get("expected") if q.get("expected") else None,
                    "all_scores": scores,
                })
            categories[cat_name] = cat_results
        print_gap_analysis(categories)

    if args.save:
        Path(args.save).write_text(json.dumps(metrics, indent=2))
        print(f"  Results saved to {args.save}")

    # Exit with error if overall recall < 80%
    overall = metrics.get("overall_recall_at_1", 0)
    if overall < 0.80:
        print(f"\n  ⚠ Overall Recall@1 = {overall:.1%} (below 80% target)")
        sys.exit(1)
    else:
        print(f"\n  ✓ Overall Recall@1 = {overall:.1%}")


if __name__ == "__main__":
    main()
