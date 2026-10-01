"""Fetch free models from Google AI, including pricing-page scraping."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

from lib.html_tree import Node, parse_html
from lib.http_client import get_url
from providers.base import models_url

ROOT = Path(__file__).resolve().parent.parent
RATE_LIMITS_SNAPSHOT = "data/google_rate_limits.html"
MAX_PAGES = 20


def heading_model_ids(heading_group: Node) -> set[str]:
    """Extract every model ID from a ``.heading-group`` element.

    Model IDs live in ``<em><a><code>`` elements; any ``models/`` prefix is
    stripped from the returned values.
    """
    model_ids: set[str] = set()
    for anchor in heading_group.walk():
        if anchor.tag != "a":
            continue
        for code in anchor.walk():
            if code.tag != "code":
                continue
            value = code.text().strip()
            value = value.removeprefix("models/")
            if value:
                model_ids.add(value)
    return model_ids


def _free_tier_column(rows: list[list[str]]) -> int | None:
    """Return the column index whose header mentions the free tier."""
    return next(
        (i for row in rows for i, value in enumerate(row) if "free tier" in value),
        None,
    )


def _is_free_price(value: str) -> bool:
    """Return whether a price cell value indicates free pricing."""
    return value in {"free of charge", "free"}


def is_free_standard_table(table: Node) -> bool:
    """Return whether a pricing table lists free input and output prices.

    The table must contain a free-tier column whose input and output price
    cells all read "free of charge".
    """
    rows = []
    for row in table.walk():
        if row.tag == "tr":
            cells = [
                cell
                for cell in row.children
                if isinstance(cell, Node) and cell.tag in {"th", "td"}
            ]
            rows.append([" ".join(cell.text().split()).lower() for cell in cells])
    free_index = _free_tier_column(rows)
    if free_index is None:
        return False
    prices: dict[str, list[bool]] = {}
    for row in rows:
        if not row:
            continue
        label = row[0]
        for kind in ("input", "output"):
            if re.match(rf"^{kind}\b", label):
                prices.setdefault(kind, []).append(
                    len(row) > free_index and _is_free_price(row[free_index])
                )
    return all(prices.get(kind) and all(prices[kind]) for kind in ("input", "output"))


def _inside_models_section(node: Node) -> bool:
    """Return whether a node is nested inside a ``.models-section`` element."""
    parent = node.parent
    while parent is not None:
        if parent.has_class("models-section"):
            return True
        parent = parent.parent
    return False


def google_free_ids(html: str | bytes) -> set[str]:
    """Return model IDs whose Standard pricing is free of charge.

    Each model is described in a ``.models-section`` followed by ``<section>``
    elements holding its pricing tables; a model counts as free when its
    Standard table lists free input and output prices.
    """
    root = parse_html(html)
    found: set[str] = set()
    pending: set[str] = set()
    for node in root.walk():
        if node.has_class("models-section"):
            pending = heading_model_ids(node)
            continue
        if node.tag != "section" or _inside_models_section(node):
            continue
        standard = any(
            child.tag == "h3"
            and re.match(
                r"^standard(?:\s+pricing)?$",
                " ".join(child.text().split()).lower(),
            )
            for child in node.walk()
        )
        table = next(
            (
                child
                for child in node.walk()
                if child.tag == "table" and child.has_class("pricing-table")
            ),
            None,
        )
        if standard and table is not None and is_free_standard_table(table):
            found.update(pending)
    return found


def _parse_limit_value(text: str) -> int | None:
    """Parse a rate limit like '250K', '1M', '14.4K', 'Unlimited', or '0'."""
    text = text.strip()
    if not text or text == "-" or text.lower() == "unlimited":
        return None
    text = text.replace(",", "")
    multiplier = 1
    if text.upper().endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.upper().endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    return int(float(text) * multiplier)


def _model_id(cells: list[Node]) -> str | None:
    """Return the model id from the Model cell of a rate-limits row."""
    model = next(
        (
            cell
            for cell in cells
            if "mat-column-Model" in (cell.attrs.get("class") or "").split()
        ),
        None,
    )
    return model.attrs.get("data-test-id") if model is not None else None


def _column_limit(cells: list[Node], column: str) -> int | None:
    """Return the limit value (after ``/``) from a rate-limits cell."""
    cell = next(
        (
            cell
            for cell in cells
            if f"mat-column-{column}" in (cell.attrs.get("class") or "").split()
        ),
        None,
    )
    if cell is None:
        return None
    value = next(
        (node.text().strip() for node in cell.walk() if node.has_class("metric-value")),
        None,
    )
    if value is None or "/" not in value:
        return None
    return _parse_limit_value(value.split("/", 1)[1])


def parse_rate_limits(html: str | bytes) -> dict[str, dict[str, int | None]]:
    """Parse the Google AI Studio rate-limits HTML table.

    Each row lists one model with a ``data-test-id`` on its Model cell and
    ``span.metric-value`` elements reading ``current / limit`` in the RPM,
    TPM and RPD cells.  Values without a limit (``-``, ``Unlimited``) become
    ``None``.  Group-header rows, whose only cell spans the full table width,
    are skipped.  If a model appears multiple times (e.g., in different
    sections), only the first occurrence is kept.

    Args:
        html: The rate-limits page markup.

    Returns:
        A mapping of model id to ``{"rpm": int | None, "tpm": int | None,
        "rpd": int | None}`` for every model row.
    """
    root = parse_html(html)
    limits: dict[str, dict[str, int | None]] = {}
    for row in root.walk():
        if row.tag != "tr":
            continue
        cells = [
            cell for cell in row.children if isinstance(cell, Node) and cell.tag == "td"
        ]
        if len(cells) <= 1:
            continue  # group-header row spanning the table width
        model_id = _model_id(cells)
        if model_id is None:
            continue
        if model_id in limits:
            continue  # keep first occurrence only
        limits[model_id] = {
            "rpm": _column_limit(cells, "RPM"),
            "tpm": _column_limit(cells, "TPM"),
            "rpd": _column_limit(cells, "RPD"),
        }
    return limits


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Google AI models.

    The models list requires a "GOOGLE_API_KEY"; free status is decided by
    scraping the pricing page referenced in "other_source" for Standard
    tables whose input and output prices are free of charge.

    Args:
        provider_config: A provider entry from providers.json.

    Returns:
        The provider's free models as a list of dictionaries.

    Raises:
        ValueError: If "GOOGLE_API_KEY" is not set, the models list runs past
            MAX_PAGES, repeats a page token, "other_source" lists no pricing
            page, or the pricing page lists no free Standard models.
    """
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ValueError("GOOGLE_API_KEY is required for Google models.list")
    url = models_url(provider_config)
    models = []
    token = None
    seen_tokens = set()
    for _ in range(MAX_PAGES):
        page_url = url + ("?" + urlencode({"pageToken": token}) if token else "")
        page = json.loads(get_url(page_url, {"x-goog-api-key": key}))
        models.extend(page["models"])
        token = page.get("nextPageToken")
        if not token:
            break
        if token in seen_tokens:
            raise ValueError("Google models.list repeated nextPageToken")
        seen_tokens.add(token)
    else:
        raise ValueError(f"Google models.list served more than {MAX_PAGES} pages")
    pricing_url = next(
        (
            source["url"]
            for source in provider_config["other_source"]
            if "pricing" in source["url"]
        ),
        None,
    )
    if pricing_url is None:
        raise ValueError("no pricing page listed in other_source")
    free_ids = google_free_ids(get_url(pricing_url))
    if not free_ids:
        raise ValueError(
            "Google pricing page contained no free Standard models; "
            "keeping existing data"
        )
    models = [
        model for model in models if model["name"].removeprefix("models/") in free_ids
    ]
    # The snapshot is saved by hand from the signed-in rate-limit page, so it
    # drifts from the live quotas; report which models it cannot cover.
    rate_limits_path = ROOT / RATE_LIMITS_SNAPSHOT
    if rate_limits_path.exists():
        limits = parse_rate_limits(rate_limits_path.read_text(encoding="utf-8"))
        uncovered = []
        for model in models:
            model_id = model["name"].removeprefix("models/")
            if model_id in limits:
                model["rate_limits"] = limits[model_id]
            else:
                uncovered.append(model_id)
        if uncovered:
            print(
                f"googleai: no saved rate limits for {len(uncovered)} free models: "
                + ", ".join(sorted(uncovered)),
                file=sys.stderr,
            )
    else:
        print(
            f"googleai: {RATE_LIMITS_SNAPSHOT} is missing, publishing no rate limits",
            file=sys.stderr,
        )
    return models
