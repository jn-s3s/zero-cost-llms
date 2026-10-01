"""Fetch free models from Agnes AI."""

from __future__ import annotations

import json
import os
import re

from lib.html_tree import Node, parse_html
from lib.http_client import get_url
from providers.base import models_url


def _is_free_price(text: str) -> bool:
    """Return whether a price cell value indicates free pricing.

    A leading dollar amount of zero is free in any format, so "$0", "$0.00",
    "$0 / 1M tokens" and "$0/1M tokens" qualify while "$0.025" does not.
    The literal word "free" also qualifies.
    """
    text = text.strip()
    if text.lower() == "free":
        return True
    match = re.match(r"\$(\d+(?:\.\d+)?)", text)
    return match is not None and float(match.group(1)) == 0


def parse_pricing(html: str | bytes) -> set[str]:
    """Parse the Agnes pricing page to find free models.

    The page contains tables with columns: Model | Billing item | List price | Current price.
    Models are considered free if their current price is $0.

    Args:
        html: The pricing page markup.

    Returns:
        A set of model IDs that are currently free.
    """
    root = parse_html(html)
    free_models: set[str] = set()

    # Find all tables
    for table in root.walk():
        if table.tag != "table":
            continue

        # Check if this is a pricing table by looking at headers
        headers = []
        for row in table.walk():
            if row.tag != "tr":
                continue
            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag in {"th", "td"}
            ]
            if cells and cells[0].tag == "th":
                headers = [cell.text().strip().lower() for cell in cells]
                break

        # Look for tables with pricing columns
        if "model" not in headers or "current price" not in headers:
            continue

        model_col = headers.index("model")
        current_price_col = headers.index("current price")

        # Parse data rows
        for row in table.walk():
            if row.tag != "tr":
                continue

            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag == "td"
            ]

            if len(cells) <= max(model_col, current_price_col):
                continue

            # Extract model name from the first column
            model_cell = cells[model_col]
            # Model names are in <code> tags
            model_name = None
            for code in model_cell.walk():
                if code.tag == "code":
                    model_name = code.text().strip()
                    break

            if not model_name:
                continue

            # Extract current price
            price_cell = cells[current_price_col]
            price_text = price_cell.text().strip()

            # Check if the price is free
            if _is_free_price(price_text):
                free_models.add(model_name)

    return free_models


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Agnes AI.

    Agnes AI's /models endpoint lists all models. We fetch the pricing page
    to determine which models are currently free (current price = $0).

    Args:
        provider_config: Provider configuration from providers.json

    Returns:
        List of free model dictionaries
    """
    key_env_var = provider_config["keyEnvVar"]
    api_key = os.environ.get(key_env_var)
    if not api_key:
        raise ValueError(f"{key_env_var} is required for Agnes models.list")

    # Fetch the pricing page to identify free models
    pricing_url = next(
        (
            source["url"]
            for source in provider_config.get("other_source", [])
            if source["type"] == "pricing"
        ),
        None,
    )

    if pricing_url is None:
        raise ValueError("No pricing page listed in other_source")

    pricing_html = get_url(pricing_url)
    free_model_ids = parse_pricing(pricing_html)

    if not free_model_ids:
        raise ValueError(
            "Agnes pricing page contained no free models; keeping existing data"
        )

    # Fetch models from API
    url = models_url(provider_config)
    headers = {"Authorization": f"Bearer {api_key}"}
    response = get_url(url, headers)
    data = json.loads(response)

    # Filter to only include free models
    free_models = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if model_id in free_model_ids:
            free_models.append(model)

    return free_models
