"""LiveCodeBench scores for models."""

from __future__ import annotations

from lib.benchmark_lookup import load_score_index, lookup_score


def get_livecodebench_score(
    model_id: str | None, model_name: str | None = None
) -> float | None:
    """Return LiveCodeBench score as a percentage (0-100) if known."""
    return lookup_score(
        load_score_index("config/benchmarks/livecodebench_mapping.json"),
        model_id,
        model_name,
    )
