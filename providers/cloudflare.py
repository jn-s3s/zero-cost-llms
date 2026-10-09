"""Fetch free models from Cloudflare AI."""

from __future__ import annotations

import json
import os

from lib.http_client import get_url


def _is_paid(model: dict) -> bool:
    """Return whether a Cloudflare model requires paid access.

    Paid models carry a property with ``property_id`` of
    ``require_workers_paid`` and ``value`` of ``"true"``.
    """
    properties = model.get("properties")
    if not isinstance(properties, list):
        return False
    return any(
        isinstance(prop, dict)
        and prop.get("property_id") == "require_workers_paid"
        and prop.get("value") == "true"
        for prop in properties
    )


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Cloudflare AI models.

    Cloudflare's GET models endpoint requires Bearer token auth and
    an account ID substituted into the base URL.  Models are filtered by
    excluding those with the ``require_workers_paid`` property.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The provider's free models as a list of dictionaries.

    Raises:
        ValueError: If the environment variables are unset.
    """
    key_env_var = provider_config["keyEnvVar"]
    key = os.environ.get(key_env_var)
    if not key:
        raise ValueError(f"{key_env_var} is required for Cloudflare models")
    account_env_var = provider_config["accountEnvVar"]
    account_id = os.environ.get(account_env_var)
    if not account_id:
        raise ValueError(f"{account_env_var} is required for Cloudflare models")
    api = provider_config["api"]
    base_url = api["baseUrl"].replace("<accountEnvVar>", account_id)
    endpoint = api["models"]["endpoint"]
    url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
    payload = json.loads(get_url(url, {"Authorization": f"Bearer {key}"}))
    return [model for model in payload["result"] if not _is_paid(model)]
