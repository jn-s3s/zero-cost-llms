"""Fetch free models from Kilo."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from lib.http_client import get_url
from providers.base import models_url


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Kilo.

    Args:
        provider_config: Provider configuration from providers.json

    Returns:
        List of free model dictionaries
    """
    url = models_url(provider_config)
    response = get_url(url)
    data = json.loads(response)

    now = datetime.now(timezone.utc)
    free_models = []

    for model in data.get("data", []):
        # Check if model is marked as free
        if not model.get("isFree"):
            continue

        # Check if model has expired
        expiration_date = model.get("expiration_date")
        if expiration_date:
            try:
                expires = datetime.fromisoformat(expiration_date.replace("Z", "+00:00"))
                if expires < now:
                    continue
            except (ValueError, TypeError):
                # If we can't parse the date, skip the model
                continue

        free_models.append(model)

    return free_models
