"""Fetch free models from Requesty."""

from __future__ import annotations

import json
import time

from lib.http_client import get_url
from providers.base import models_url


def _requesty_is_free(model: dict) -> bool:
    """Return whether Requesty prices both input and output at exactly zero.

    A missing or non-numeric price is unknown, not free, so an upstream field
    rename fails closed instead of publishing every paid model as free.
    """
    for key in ("input_price", "output_price"):
        price = model.get(key)
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            return False
        if price != 0:
            return False
    return True


def _requesty_is_retired(model: dict) -> bool:
    """Return whether a Requesty model has passed its retirement date.

    A missing or non-numeric ``retires`` value is treated as not retired, so an
    upstream field rename does not silently drop every model.
    """
    retires = model.get("retires")
    if isinstance(retires, bool) or not isinstance(retires, (int, float)):
        return False
    return retires <= time.time()


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Requesty models.

    A model is free when both its input and output price are zero and its
    retirement date (when present) is still in the future.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The provider's free models as a list of dictionaries.
    """
    payload = json.loads(get_url(models_url(provider_config)))
    return [
        model
        for model in payload["data"]
        if _requesty_is_free(model) and not _requesty_is_retired(model)
    ]
