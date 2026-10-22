"""Attaching scraped rate limits to a provider's model list."""

from __future__ import annotations

import sys
from collections.abc import Callable


def _model_id(model: dict) -> str:
    return model.get("id", "")


def attach_rate_limits(
    models: list[dict],
    limits: dict[str, dict],
    provider_id: str,
    model_id_of: Callable[[dict], str] = _model_id,
    saved: bool = False,
) -> None:
    """Attach each model's rate limits in place and report the uncovered ones.

    A model whose id is missing from ``limits`` gets no ``rate_limits`` field,
    and the uncovered ids are listed on stderr so a stale page or snapshot
    shows up in the run log instead of silently shrinking the published data.

    Args:
        models: The provider's model list, mutated by adding ``rate_limits``.
        limits: Mapping of model id to the limits object to attach.
        provider_id: Prefix for the warning line, the ``config/providers.json`` id.
        model_id_of: How to read a model's id when it is not the ``id`` field.
        saved: Whether the limits came from a hand-kept snapshot rather than a
            live page, which changes the wording of the warning.
    """
    uncovered = []
    for model in models:
        model_id = model_id_of(model)
        if model_id in limits:
            model["rate_limits"] = limits[model_id]
        else:
            uncovered.append(model_id)
    if uncovered:
        saved_word = "saved " if saved else ""
        model_word = "free models" if saved else "models"
        print(
            f"{provider_id}: no {saved_word}rate limits"
            f" for {len(uncovered)} {model_word}: " + ", ".join(sorted(uncovered)),
            file=sys.stderr,
        )
