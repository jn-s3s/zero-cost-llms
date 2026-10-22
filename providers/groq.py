"""Fetch free models from Groq."""

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
    """Parse the Groq rate-limits HTML table.

    The page has two separate ``<table>`` elements: one with headers (MODEL ID,
    RPM, RPD, TPM, TPD, ASH, ASD) and another with data rows. Values of "-"
    become None.

    Args:
        html: The rate-limits page markup.

    Returns:
        A mapping of model id to ``{"rpm": int | float | None, "rpd": ...}``
        for every value column, over every model row.
    """
    root = parse_html(html)
    limits: dict[str, dict[str, int | float | None]] = {}

    # Find all tables
    tables = [node for node in root.walk() if node.tag == "table"]

    # Find the header table (contains MODEL ID)
    header_table = None
    col_map: dict[str, int] = {}
    for table in tables:
        for row in table.walk():
            if row.tag != "tr":
                continue
            headers = []
            for cell in row.children:
                if isinstance(cell, Node) and cell.tag in {"th", "td"}:
                    headers.append(cell.text().strip().upper())
            if "MODEL ID" in headers:
                header_table = table
                for i, header in enumerate(headers):
                    if header in {"MODEL ID", "RPM", "RPD", "TPM", "TPD", "ASH", "ASD"}:
                        col_map[header] = i
                break
        if header_table is not None:
            break

    if header_table is None or "MODEL ID" not in col_map:
        return limits

    # Find the data table (contains tbody with model rows)
    for table in tables:
        if table is header_table:
            continue
        for row in table.walk():
            if row.tag != "tr":
                continue

            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag == "td"
            ]

            if len(cells) <= col_map.get("MODEL ID", 0):
                continue

            # Extract model ID
            model_id = cells[col_map["MODEL ID"]].text().strip()
            if not model_id:
                continue

            # Extract rate limits
            model_limits: dict[str, int | float | None] = {}
            for col_name in ["RPM", "RPD", "TPM", "TPD", "ASH", "ASD"]:
                if col_name in col_map and len(cells) > col_map[col_name]:
                    value = cells[col_map[col_name]].text().strip()
                    model_limits[col_name.lower()] = parse_limit_value(value)

            limits[model_id] = model_limits

    return limits


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Groq models.

    Groq exposes an OpenAI-compatible ``/models`` endpoint that requires a
    Bearer token.  Every listed model is available to free-tier users.
    Rate limits are scraped from the public rate-limits documentation page
    listed in "other_source".

    Args:
        provider_config: A provider entry from config/providers.json.

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
        raise ValueError(f"{key_env_var} is required for Groq models.list")
    payload = json.loads(
        get_url(models_url(provider_config), {"Authorization": f"Bearer {key}"})
    )
    models = list(payload["data"])

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
        print(
            "groq: no rate-limits page listed in other_source, publishing no rate limits",
            file=sys.stderr,
        )
        return models

    limits = parse_rate_limits(get_url(rate_limits_url))
    if not limits:
        print(
            "groq: rate-limits page contained no model data; publishing no rate limits",
            file=sys.stderr,
        )
        return models

    attach_rate_limits(models, limits, "groq")

    return models
