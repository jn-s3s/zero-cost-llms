"""Benchmark scores for models (SWE-bench, etc.)."""

from __future__ import annotations

from lib.benchmark_lookup import load_score_index, load_score_metadata, lookup_score


def swebench_source() -> str:
    """Return the attribution to publish beside a SWE-bench score.

    The mapping file records where its numbers came from, so the published
    claim is quoted from there rather than restated in this module. A file that
    cannot account for itself falls back to the plain leaderboard name rather
    than inventing a capture date it never recorded.
    """
    meta = load_score_metadata("config/benchmarks/swebench_mapping.json")
    parts = [meta.get("source") or "SWE-bench Verified leaderboard"]
    if meta.get("capturedAt"):
        parts.append(f"captured {meta['capturedAt']}")
    if meta.get("measured"):
        parts.append(meta["measured"])
    return "; ".join(parts)


def get_swebench_score(
    model_id: str | None, model_name: str | None = None
) -> float | None:
    """Return SWE-bench Verified score as percentage (0-100) if known."""
    return lookup_score(
        load_score_index("config/benchmarks/swebench_mapping.json"),
        model_id,
        model_name,
    )


def swebench_tier(score: float | None) -> str | None:
    """Convert SWE-bench score to tier."""
    if score is None:
        return None
    if score >= 70:
        return "S+"
    if score >= 60:
        return "S"
    if score >= 50:
        return "A+"
    if score >= 40:
        return "A"
    if score >= 35:
        return "A-"
    if score >= 30:
        return "B+"
    if score >= 20:
        return "B"
    return "C"
