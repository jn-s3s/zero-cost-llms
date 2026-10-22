"""Qoder provider implementation."""

from __future__ import annotations

import json
import os

from lib.http_client import get_url
from providers.base import models_url


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Qoder.

    Args:
        provider_config: Provider configuration from config/providers.json

    Returns:
        List of free model dictionaries
    """
    # Get API key from environment
    api_key = os.environ.get(provider_config["keyEnvVar"])
    if not api_key:
        raise ValueError(
            f"{provider_config['keyEnvVar']} environment variable is required"
        )

    # Fetch models from API with authentication
    url = models_url(provider_config)
    headers = {"Authorization": f"Bearer {api_key}"}
    response = get_url(url, headers)
    data = json.loads(response)

    # Filter to only include free models
    # Free models have `price_factor` equal to 0 in data[]
    free_models = []
    for model in data.get("data", []):
        if model.get("price_factor") == 0:
            free_models.append(model)

    return free_models
