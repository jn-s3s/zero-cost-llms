"""Fetch free models from ZAI."""

from __future__ import annotations

import sys

from lib.html_tree import Node, parse_html
from lib.http_client import get_url
from lib.rate_limits import attach_rate_limits
from lib.repo_root import REPO_ROOT


def parse_rate_limits(html: str | bytes) -> dict[str, int]:
    """Parse the ZAI rate-limits HTML table.

    The Ant Design table has columns: Model type | Model name | Concurrency limit.
    Each row lists one model with its concurrency limit.

    Args:
        html: The rate-limits page markup.

    Returns:
        A mapping of model name to concurrency limit for every model row.
    """
    root = parse_html(html)
    limits: dict[str, int] = {}

    for table in root.walk():
        if table.tag != "table":
            continue

        # Find the header row to identify columns
        header_row = None
        for row in table.walk():
            if row.tag != "tr":
                continue
            headers = []
            for cell in row.children:
                if isinstance(cell, Node) and cell.tag in {"th", "td"}:
                    headers.append(cell.text().strip().lower())
            if "model name" in headers:
                header_row = row
                break

        if header_row is None:
            continue

        # Map column names to indices
        headers = []
        for cell in header_row.children:
            if isinstance(cell, Node) and cell.tag in {"th", "td"}:
                headers.append(cell.text().strip().lower())

        if "model name" not in headers or "concurrency limit" not in headers:
            continue

        model_col = headers.index("model name")
        limit_col = headers.index("concurrency limit")

        # Parse data rows
        for row in table.walk():
            if row.tag != "tr" or row is header_row:
                continue

            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag == "td"
            ]

            if len(cells) <= max(model_col, limit_col):
                continue

            model_name = cells[model_col].text().strip()
            if not model_name:
                continue

            try:
                limit_value = int(cells[limit_col].text().strip())
                limits[model_name] = limit_value
            except ValueError:
                continue

    return limits


def fetch(provider_config: dict) -> list[dict]:
    """Fetch free models from ZAI.

    ZAI's /models endpoint doesn't list all available models, so we scrape
    the pricing page to find models marked as free.

    Args:
        provider_config: Provider configuration from config/providers.json

    Returns:
        List of free model dictionaries

    Raises:
        ValueError: If no pricing page is listed in "other_source".
    """
    # Fetch the pricing page directly from the live site
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
    tree = parse_html(pricing_html)

    # Find all tables and extract free models
    free_models = []
    for node in tree.walk():
        if node.tag != "table":
            continue

        # Collect all rows in this table
        rows = []
        for child in node.walk():
            if child.tag == "tr":
                rows.append(child)

        if not rows:
            continue

        # Check if this is a pricing table with Model/Input/Cached Input/Output columns
        header_row = rows[0]
        headers = []
        for cell in header_row.walk():
            if cell.tag in ("th", "td"):
                headers.append(cell.text().strip().lower())

        # Look for tables with pricing columns
        if "model" in headers and "input" in headers and "output" in headers:
            model_col = headers.index("model")
            input_col = headers.index("input")
            output_col = headers.index("output")

            # Check each row for free pricing
            for row in rows[1:]:
                cells = []
                for cell in row.walk():
                    if cell.tag == "td":
                        cells.append(cell)

                if len(cells) <= max(model_col, input_col, output_col):
                    continue

                model_name = cells[model_col].text().strip()
                input_price = cells[input_col].text().strip().lower()
                output_price = cells[output_col].text().strip().lower()

                # Model is free if both input and output are "Free"
                if input_price == "free" and output_price == "free":
                    # Construct a model object
                    free_models.append(
                        {
                            "id": model_name,
                            "object": "model",
                            "owned_by": "zai",
                        }
                    )

    # Load rate limits from snapshot (auth-gated page)
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
    rate_limits_path = REPO_ROOT / rate_limits_snapshot
    if rate_limits_path.exists():
        limits = parse_rate_limits(rate_limits_path.read_text(encoding="utf-8"))
        concurrency_limits = {
            name: {"concurrency": value} for name, value in limits.items()
        }
        attach_rate_limits(free_models, concurrency_limits, "zai", saved=True)
    else:
        print(
            f"zai: {rate_limits_snapshot} is missing, publishing no rate limits",
            file=sys.stderr,
        )

    return free_models
