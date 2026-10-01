"""Fetch free models from Cerebras."""

from __future__ import annotations

import json
import os
import sys

from lib.html_tree import Node, parse_html
from lib.http_client import get_url
from lib.limit_value import parse_limit_value
from lib.rate_limits import attach_rate_limits
from providers.base import models_url


def parse_rate_limits(html: str | bytes) -> dict[str, dict[str, int | float | None]]:
    """Parse the Cerebras rate-limits HTML page.

    The page contains a tabbed interface with Free Trial, Developer, and Enterprise tiers.
    We extract the Free Trial tier table which has columns: Model, RPM, Uncached TPM, Total TPM, TPH, TPD.

    Args:
        html: The rate-limits page markup.

    Returns:
        A mapping of model id to ``{"rpm": int | float | None, "tpm": ...}``
        for every value column, over every model in the Free Trial tier.
    """
    root = parse_html(html)
    limits: dict[str, dict[str, int | float | None]] = {}

    # Find the Free Trial tab panel
    free_trial_panel = None
    for node in root.walk():
        if node.tag == "div" and node.attrs.get("id") == "panel-free-trial-0":
            free_trial_panel = node
            break

    if free_trial_panel is None:
        return limits

    # Find the table within the Free Trial panel
    for table in free_trial_panel.walk():
        if table.tag != "table":
            continue

        # Extract headers
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

        if not headers:
            continue

        # Map column names to indices
        col_map = {}
        for i, header in enumerate(headers):
            if header in {"model", "rpm", "uncached tpm", "total tpm", "tph", "tpd"}:
                col_map[header] = i

        if "model" not in col_map:
            continue

        # Parse data rows
        for row in table.walk():
            if row.tag != "tr":
                continue

            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag == "td"
            ]

            if len(cells) <= col_map.get("model", 0):
                continue

            # Extract model name from <code> tag
            model_cell = cells[col_map["model"]]
            model_id = None
            for code in model_cell.walk():
                if code.tag == "code":
                    model_id = code.text().strip()
                    break

            if not model_id:
                continue

            # Extract rate limits
            model_limits: dict[str, int | float | None] = {}
            for col_name in ["rpm", "uncached tpm", "total tpm", "tph", "tpd"]:
                if col_name in col_map and len(cells) > col_map[col_name]:
                    value = cells[col_map[col_name]].text().strip()
                    # Normalize column names
                    key = col_name.replace(" ", "_")
                    model_limits[key] = parse_limit_value(value)

            limits[model_id] = model_limits

    return limits


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Cerebras models.

    Cerebras exposes an OpenAI-compatible ``/models`` endpoint that requires a
    Bearer token. Rate limits are scraped from the public rate-limits documentation page
    listed in "other_source".

    Args:
        provider_config: A provider entry from providers.json.

    Returns:
        The provider's free models as a list of dictionaries, each with
        an added "rate_limits" field when available.

    Raises:
        ValueError: If the environment variable is unset or no rate-limits
            page is listed in other_source.
    """
    key_env_var = provider_config["keyEnvVar"]
    key = os.environ.get(key_env_var)
    if not key:
        raise ValueError(f"{key_env_var} is required for Cerebras models.list")

    payload = json.loads(
        get_url(models_url(provider_config), {"Authorization": f"Bearer {key}"})
    )
    models = list(payload.get("data", []))

    # Fetch rate limits from the public documentation page
    rate_limits_url = next(
        (
            source["url"]
            for source in provider_config.get("other_source", [])
            if source["type"] == "quota"
        ),
        None,
    )
    if rate_limits_url is None:
        raise ValueError("No rate-limits page listed in other_source")

    limits = parse_rate_limits(get_url(rate_limits_url))
    if not limits:
        print(
            "cerebras: rate-limits page contained no model data; publishing no rate limits",
            file=sys.stderr,
        )
        return models

    attach_rate_limits(models, limits, "cerebras")

    return models
