"""Fetch free models from NVIDIA NIM."""

from __future__ import annotations

import json

from lib.html_tree import parse_html
from lib.http_client import get_url
from providers.base import models_url

SEPARATOR_FOLD = str.maketrans({".": "-", "_": "-"})


def join_key(model_id: str) -> str:
    """Return the key that a model's two NVIDIA id spellings share.

    The models API reports ``nvidia/llama-3.1-nemotron-safety-guard-8b-v3``
    while the card for the same model links to
    ``/nvidia/llama-3_1-nemotron-safety-guard-8b-v3``, and the API's
    ``z-ai/glm-5.3`` links as ``/z-ai/glm-5-3``, so the two namespaces only line
    up once dots, underscores and hyphens fold together. The fold is lossy in
    exchange: two models whose ids differ only by one of those separators would
    match the same card.
    """
    return model_id.casefold().translate(SEPARATOR_FOLD)


def nvidia_free_keys(html: str | bytes) -> set[str]:
    """Return the join keys of the models marked free on the catalogue page.

    The page is the "Free Endpoint" filtered view of build.nvidia.com; each free
    model is an ``<a>`` carrying ``data-nvtrack-nav-object="artifact-card"``
    whose ``href`` like ``/nvidia/llama-3.1-8b`` names the model with the
    leading slash stripped. The publisher links carry
    ``artifact-card-publisher-link``, so the exact attribute match skips them.
    """
    free_keys: set[str] = set()
    for node in parse_html(html).walk():
        if node.tag != "a":
            continue
        if node.attrs.get("data-nvtrack-nav-object") != "artifact-card":
            continue
        model_id = (node.attrs.get("href") or "").removeprefix("/")
        if model_id:
            free_keys.add(join_key(model_id))
    return free_keys


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free NVIDIA NIM models.

    The models list needs no API key; free status is decided by parsing the
    "Free Endpoint" filtered catalogue page referenced in "other_source" and
    keeping only the models whose ``id`` appears there.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The provider's free models as a list of dictionaries.

    Raises:
        ValueError: If "other_source" lists no free-endpoint page, the page
            lists no free models, or none of the API models match a free card.
    """
    page_url = next(
        (
            source["url"]
            for source in provider_config["other_source"]
            if source["type"] == "models"
        ),
        None,
    )
    if page_url is None:
        raise ValueError("no Free Endpoint page listed in other_source")
    free_keys = nvidia_free_keys(get_url(page_url))
    if not free_keys:
        raise ValueError(
            "NVIDIA Free Endpoint page listed no free models; keeping existing data"
        )
    models = json.loads(get_url(models_url(provider_config)))["data"]
    free_models = [model for model in models if join_key(model["id"]) in free_keys]
    if models and not free_models:
        raise ValueError(
            "NVIDIA matched no API model against its free endpoint page"
            f" ({len(models)} listed, {len(free_keys)} free)"
        )
    return free_models
