"""Fetch free models from OpenRouter."""

from __future__ import annotations

import json

from lib.http_client import get_url
from providers.base import models_url


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free OpenRouter models.

    A model is free when its id ends with the ``:free`` suffix or starts
    with ``stealth``.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The provider's free models as a list of dictionaries.
    """
    payload = json.loads(get_url(models_url(provider_config)))
    return [
        model
        for model in payload["data"]
        if model["id"].endswith(":free") or model["id"].startswith("stealth")
    ]
