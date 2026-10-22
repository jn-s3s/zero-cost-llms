"""Cline provider implementation."""

from __future__ import annotations

import json

from lib.http_client import get_url
from providers.base import models_url


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Cline.

    Args:
        provider_config: Provider configuration from config/providers.json

    Returns:
        List of free model dictionaries
    """
    # Fetch models from API (no authentication required)
    url = models_url(provider_config)
    response = get_url(url)
    data = json.loads(response)

    # Filter to only include free models
    # Free models have `:free` suffix or `stealth` as prefix in data[].id
    free_models = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if model_id.endswith(":free") or model_id.startswith("stealth"):
            free_models.append(model)

    return free_models
