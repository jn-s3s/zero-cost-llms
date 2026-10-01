"""Fetch free models from Mistral."""

from __future__ import annotations

import json
import os

from lib.html_tree import parse_html
from lib.http_client import get_url
from lib.limit_value import parse_limit_value
from lib.repo_root import REPO_ROOT
from providers.base import models_url


def parse_rate_limits(html: str | bytes) -> dict[str, dict[str, int | float | None]]:
    """Parse the Mistral rate-limits HTML cards.

    Each card contains an ``<h3>`` with the model name, followed by metric
    blocks with "Tokens per Minute" and "Requests per Second" values.

    Args:
        html: The rate-limits page markup.

    Returns:
        A mapping of model name to ``{"tpm": int | float | None, "rps": ...}``
        for every model card.
    """
    root = parse_html(html)
    limits: dict[str, dict[str, int | None]] = {}

    # Find all card containers (div with class containing "bg-default")
    for node in root.walk():
        if node.tag != "div" or not node.has_class("bg-default"):
            continue

        # Extract model name from <h3>
        model_name = None
        for child in node.walk():
            if child.tag == "h3":
                model_name = child.text().strip()
                break

        if not model_name:
            continue

        # Extract metrics
        metrics: dict[str, int | float | None] = {}
        metric_blocks = []
        for child in node.walk():
            if child.tag == "div" and child.has_class("space-y-1"):
                metric_blocks.append(child)

        for block in metric_blocks:
            label = None
            value = None
            for sub in block.walk():
                if sub.tag == "div":
                    text = sub.text().strip()
                    if sub.has_class("text-muted"):
                        label = text
                    elif sub.has_class("font-medium"):
                        value = text

            if label and value is not None:
                if "tokens per minute" in label.lower():
                    metrics["tpm"] = parse_limit_value(value)
                elif "requests per second" in label.lower():
                    metrics["rps"] = parse_limit_value(value)

        limits[model_name] = metrics

    return limits


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Mistral.

    Args:
        provider_config: Provider configuration from providers.json

    Returns:
        List of free model dictionaries
    """
    key_env_var = provider_config["keyEnvVar"]
    api_key = os.environ.get(key_env_var)
    if not api_key:
        raise ValueError(f"{key_env_var} is required for Mistral models.list")

    # Parse the rate limits snapshot to identify free models and their limits
    rate_limits_snapshot = next(
        (
            source["snapshot"]
            for source in provider_config["other_source"]
            if source["type"] == "quota"
        ),
        None,
    )
    if rate_limits_snapshot is None:
        raise ValueError("no rate-limit snapshot listed in other_source")
    snapshot_path = REPO_ROOT / rate_limits_snapshot
    snapshot_html = snapshot_path.read_text(encoding="utf-8")
    rate_limits = parse_rate_limits(snapshot_html)

    # Extract model names from the rate limits
    free_model_ids = {name.lower() for name in rate_limits}

    # Fetch models from API
    url = models_url(provider_config)
    headers = {"Authorization": f"Bearer {api_key}"}
    response = get_url(url, headers)
    data = json.loads(response)

    # Filter to only include free models and attach rate limits
    free_models = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if model_id.lower() in free_model_ids:
            # Find the matching rate limits (case-insensitive)
            for name, limits in rate_limits.items():
                if name.lower() == model_id.lower():
                    model["rate_limits"] = limits
                    break
            free_models.append(model)

    return free_models
