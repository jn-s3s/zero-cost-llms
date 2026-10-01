"""Cohere provider implementation."""

from __future__ import annotations

import json
import os

from lib.html_tree import parse_html
from lib.http_client import get_url
from providers.base import models_url


def _matches_free_id(model_id: str, pattern: str) -> bool:
    """Match an API id to a scraped page name only at a version boundary.

    Accepts the exact id, or the id followed by "-<digits>", so "command-r"
    covers "command-r-08-2024" but not "command-r-plus-08-2024".
    """
    if model_id == pattern:
        return True
    prefix = f"{pattern}-"
    if not model_id.startswith(prefix):
        return False
    return model_id[len(prefix) :][:1].isdigit()


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Cohere.

    Args:
        provider_config: Provider configuration from providers.json

    Returns:
        List of free model dictionaries
    """
    key_env_var = provider_config["keyEnvVar"]
    api_key = os.environ.get(key_env_var)
    if not api_key:
        raise ValueError(f"{key_env_var} environment variable is required")

    # Fetch the rate limits page to identify free models
    limits_url = next(
        (
            source["url"]
            for source in provider_config.get("other_source", [])
            if source["type"] == "quota"
        ),
        None,
    )
    if limits_url is None:
        raise ValueError("No rate-limits page listed in other_source")
    limits_html = get_url(limits_url)
    tree = parse_html(limits_html)

    # Extract model names from the rate limits page
    # Models listed on the rate limits page are available on the free tier
    free_model_names = set()
    for node in tree.walk():
        if node.tag == "table":
            # Check if this is a model table (has "Model" column)
            rows = [r for r in node.walk() if r.tag == "tr"]
            if not rows:
                continue

            # Check header row
            header_cells = [
                c.text().strip().lower()
                for c in rows[0].walk()
                if c.tag in ("th", "td")
            ]
            if "model" not in header_cells:
                continue

            model_col_idx = header_cells.index("model")

            # Extract model names from data rows
            for row in rows[1:]:
                cells = [c for c in row.walk() if c.tag == "td"]
                if len(cells) > model_col_idx:
                    model_name = cells[model_col_idx].text().strip()
                    if model_name:
                        free_model_names.add(model_name)

    # Fetch models from API
    url = models_url(provider_config)
    headers = {"Authorization": f"Bearer {api_key}"}
    response = get_url(url, headers)
    data = json.loads(response)

    # Map rate limits page names to API model ID patterns
    def name_to_pattern(name: str) -> str:
        """Convert rate limits page name to API model ID pattern."""
        # Normalize: lowercase, replace spaces with hyphens, handle special chars
        pattern = name.lower().replace(" ", "-").replace("+", "-plus")
        return pattern

    free_patterns = {name_to_pattern(name) for name in free_model_names}

    # Filter to only include free models
    free_models = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        # Check if the id equals a free name or a versioned variant of one
        if any(_matches_free_id(model_id, pattern) for pattern in free_patterns):
            free_models.append(model)

    return free_models
