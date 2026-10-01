"""Fetch free models from LLM7."""

from __future__ import annotations

import json

from lib.http_client import get_url
from providers.base import models_url


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free LLM7 models.

    LLM7 exposes an OpenAI-compatible ``/models`` endpoint that doesn't require
    authentication. Free models have ``tier: "turbo"`` in their data.

    Args:
        provider_config: A provider entry from providers.json.

    Returns:
        The provider's free models as a list of dictionaries.
    """
    payload = json.loads(get_url(models_url(provider_config)))
    models = payload.get("data", [])

    # Filter to only include free models (tier == "turbo")
    free_models = [model for model in models if model.get("tier") == "turbo"]

    return free_models
