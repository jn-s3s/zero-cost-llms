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


def _price_column(headers: list[str]) -> int | None:
    """Return the index of the column showing the price currently charged."""
    return next(
        (
            index
            for index, header in enumerate(headers)
            if "current price" in header or "trial price" in header
        ),
        None,
    )


def parse_pricing(html: str | bytes) -> set[str]:
    """Parse the Agnes pricing page to find free models.

    The page contains tables with columns: Model | Billing item | List price |
    Trial price. Models are considered free only when every price row for
    them is zero. The model cell spans the rows of one model, so later rows
    inherit the model name from the row above.

    Args:
        html: The pricing page markup.

    Returns:
        A set of model IDs that are currently free.
    """
    root = parse_html(html)
    prices: dict[str, list[bool]] = {}

    for table in root.walk():
        if table.tag != "table":
            continue

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
                headers = [" ".join(cell.text().split()).lower() for cell in cells]
                break

        if "model" not in headers:
            continue
        price_col = _price_column(headers)
        if price_col is None:
            continue
        model_col = headers.index("model")

        model_name = None
        for row in table.walk():
            if row.tag != "tr":
                continue

            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag == "td"
            ]
            if not cells:
                continue

            # The model cell uses rowspan, so a continuation row has one cell
            # fewer and shifts the price column left by one.
            skipped = len(headers) - len(cells)
            if skipped == 0:
                model_name = next(
                    (
                        code.text().strip()
                        for code in cells[model_col].walk()
                        if code.tag == "code"
                    ),
                    model_name,
                )
                price_index = price_col
            elif skipped == 1 and model_col == 0:
                price_index = price_col - 1
            else:
                continue

            if model_name is None or price_index < 0:
                continue
            prices.setdefault(model_name, []).append(
                _is_free_price(cells[price_index].text().strip())
            )

    return {
        model_name for model_name, values in prices.items() if values and all(values)
    }


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from Agnes AI.

    Agnes AI's /models endpoint lists all models. We fetch the pricing page
    to determine which models are currently free (trial price = $0).

    Args:
        provider_config: Provider configuration from config/providers.json

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
