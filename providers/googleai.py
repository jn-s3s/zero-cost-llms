"""Fetch free models from Google AI, including pricing-page scraping."""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlencode

from lib.html_tree import Node, parse_html
from lib.http_client import get_url
from lib.limit_value import parse_limit_value
from lib.rate_limits import attach_rate_limits
from lib.repo_root import REPO_ROOT
from providers.base import models_url

MAX_PAGES = 20

_MODEL_LINK = re.compile(r"\[`([^`]+)`\]\(/docs/models/[^)]*\)")
_SECTION = re.compile(r"(?m)^## ")
_STANDARD_TAB = re.compile(r'\{% tab title="Standard" %\}(.*?)\{% /tab %\}', re.DOTALL)
_TABLE = re.compile(r"\{% table %\}(.*?)\{% /table %\}", re.DOTALL)
_ROW_SEPARATOR = re.compile(r"(?m)^\s*---\s*$")
_ROW_CELL = re.compile(r"(?m)^\s*\*\s?(.*)$")
_FREE_TIER_HEADER = "free tier"
_FREE_PRICES = frozenset({"free", "free of charge"})


def _cell_text(value: str) -> str:
    """Return a Markdown table cell without emphasis markers or padding."""
    return re.sub(r"[*_`]", "", value).strip()


def _free_tier_index(header: list[str]) -> int | None:
    """Return the column index whose header mentions the free tier."""
    return next(
        (i for i, value in enumerate(header) if _FREE_TIER_HEADER in value),
        None,
    )


def _is_free_price(value: str) -> bool:
    """Return whether a Free Tier cell marks standard pricing as free."""
    return _cell_text(value).lower() in _FREE_PRICES


def _is_free_standard_table(table: str) -> bool:
    """Return whether a Markdown Standard table lists free input and output prices.

    The table must contain a free-tier column whose input and output price
    cells all read "free of charge".
    """
    rows = []
    for block in _ROW_SEPARATOR.split(table):
        cells = [_cell_text(value) for value in _ROW_CELL.findall(block)]
        if cells:
            rows.append(cells)
    if not rows:
        return False
    free_index = _free_tier_index([value.lower() for value in rows[0]])
    if free_index is None:
        return False
    prices: dict[str, list[bool]] = {}
    for row in rows[1:]:
        label = row[0].lower()
        for kind in ("input", "output"):
            if re.match(rf"^{kind}\b", label):
                prices.setdefault(kind, []).append(
                    len(row) > free_index and _is_free_price(row[free_index])
                )
    return all(prices.get(kind) and all(prices[kind]) for kind in ("input", "output"))


def google_free_ids(markdown: str | bytes) -> set[str]:
    """Return model IDs whose Standard pricing is free of charge.

    Each model is introduced by a level-two heading with one or more model
    links, and its Standard pricing table sits either in a ``Standard`` tab or
    directly under the heading when the section has no tabs at all. A model
    counts as free when both its input and output price cells in the Free Tier
    column read ``Free of charge``.

    Args:
        markdown: The pricing page Markdown.

    Returns:
        The set of model IDs whose Standard input and output prices are free.
    """
    if isinstance(markdown, bytes):
        markdown = markdown.decode("utf-8")
    found: set[str] = set()
    for section in _SECTION.split(markdown)[1:]:
        model_ids = set(_MODEL_LINK.findall(section))
        if not model_ids:
            continue
        standard = _STANDARD_TAB.search(section)
        if standard is not None:
            source = standard.group(1)
        elif "{% tabs %}" in section:
            continue  # other tiers only, so no Standard price to read
        else:
            source = section
        if any(_is_free_standard_table(table) for table in _TABLE.findall(source)):
            found.update(model_ids)
    return found


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


def _column_limit(cells: list[Node], column: str) -> int | float | None:
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
    return parse_limit_value(value.split("/", 1)[1])


def parse_rate_limits(html: str | bytes) -> dict[str, dict[str, int | float | None]]:
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
        A mapping of model id to ``{"rpm": int | float | None, "tpm": ...,
        "rpd": ...}`` for every model row.
    """
    root = parse_html(html)
    limits: dict[str, dict[str, int | float | None]] = {}
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


def _rate_limit_model_id(model: dict, limits: dict[str, dict]) -> str:
    model_id = model["name"].removeprefix("models/")
    if model_id.endswith("-preview") and model_id not in limits:
        fallback_id = model_id.removesuffix("-preview")
        if fallback_id in limits:
            return fallback_id
    return model_id


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Google AI models.

    The models list requires the API key named by the entry's "keyEnvVar";
    free status is decided by reading the Markdown pricing page referenced in
    "other_source" for Standard tables whose input and output prices are free
    of charge.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The provider's free models as a list of dictionaries.

    Raises:
        ValueError: If the "keyEnvVar" environment variable is not set, the
            models list runs past MAX_PAGES, repeats a page token,
            "other_source" lists no pricing page, or the pricing page lists no
            free Standard models.
    """
    key_env_var = provider_config["keyEnvVar"]
    key = os.environ.get(key_env_var)
    if not key:
        raise ValueError(f"{key_env_var} is required for Google models.list")
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
            if source["type"] == "pricing"
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
    rate_limit_snapshot = next(
        (
            source["snapshot"]
            for source in provider_config["other_source"]
            if source["type"] == "quota"
        ),
        None,
    )
    if rate_limit_snapshot is None:
        raise ValueError("no rate-limit snapshot listed in other_source")

    rate_limits_path = REPO_ROOT / rate_limit_snapshot
    if rate_limits_path.exists():
        limits = parse_rate_limits(rate_limits_path.read_text(encoding="utf-8"))
        attach_rate_limits(
            models,
            limits,
            "googleai",
            model_id_of=lambda model: _rate_limit_model_id(model, limits),
            saved=True,
        )
    else:
        print(
            f"googleai: {rate_limit_snapshot} is missing, publishing no rate limits",
            file=sys.stderr,
        )
    return models
