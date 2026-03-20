"""
Drift scoring for glyphh-code.

Computes semantic drift between two versions of a file using cosine
distance between their HDC vectors. Useful for:
  - Detecting how much a file changed in meaning (vs formatting)
  - Scoring commit risk by aggregating per-file drift
  - Identifying hot files that may need review

Thresholds:
  0.00 - 0.10   cosmetic       formatting, comments, rename
  0.10 - 0.30   moderate       logic update, new function
  0.30 - 0.60   significant    behavioral change, new dependency
  0.60 - 1.00   architectural  rewrite, interface change

Usage:
    from drift import compute_drift, drift_label, score_commit_files
"""

from glyphh.core.ops import cosine_similarity


DRIFT_COSMETIC = 0.10
DRIFT_MODERATE = 0.30
DRIFT_SIGNIFICANT = 0.60


def drift_label(score: float) -> str:
    """Classify a drift score into a human-readable label."""
    if score < DRIFT_COSMETIC:
        return "cosmetic"
    if score < DRIFT_MODERATE:
        return "moderate"
    if score < DRIFT_SIGNIFICANT:
        return "significant"
    return "architectural"


def compute_drift(old_vector, new_vector) -> float:
    """Compute semantic drift between two file vectors.

    Returns a float in [0.0, 1.0] where 0 = identical, 1 = completely different.
    """
    sim = float(cosine_similarity(old_vector, new_vector))
    return round(max(0.0, 1.0 - sim), 4)


def score_commit_files(drift_scores: dict[str, float]) -> dict:
    """Score a commit from per-file drift scores.

    Args:
        drift_scores: {file_path: drift_score} for each changed file

    Returns:
        files:       per-file drift scores
        max_drift:   highest single-file drift
        mean_drift:  average across changed files
        risk_label:  overall commit risk tier (based on max)
        hot_files:   files above DRIFT_MODERATE threshold
    """
    if not drift_scores:
        return {"risk_label": "unknown", "files": {}}

    max_drift = max(drift_scores.values())
    mean_drift = round(sum(drift_scores.values()) / len(drift_scores), 4)
    hot_files = [f for f, s in drift_scores.items() if s >= DRIFT_MODERATE]

    return {
        "files": drift_scores,
        "max_drift": max_drift,
        "mean_drift": mean_drift,
        "risk_label": drift_label(max_drift),
        "hot_files": hot_files,
    }
