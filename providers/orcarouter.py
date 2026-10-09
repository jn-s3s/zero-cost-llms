"""Fetch free models from OrcaRouter."""

from __future__ import annotations

import json

from lib.http_client import get_url
from providers.base import models_url


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from OrcaRouter.

    Args:
        provider_config: Provider configuration from config/providers.json

    Returns:
        List of free model dictionaries
    """
    url = models_url(provider_config)
    response = get_url(url)
    data = json.loads(response)

    # Filter to only include free models (those with -free suffix)
    free_models = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if model_id.endswith(("-free", "/free")):
            free_models.append(model)

    return free_models
