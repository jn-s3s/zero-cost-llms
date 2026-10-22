"""Fetch free models from Ollama Cloud."""

from __future__ import annotations

import json

from lib.html_tree import parse_html
from lib.http_client import get_url
from lib.repo_root import REPO_ROOT
from providers.base import models_url


def _free_model_ids_from_snapshot(provider_config: dict) -> set[str]:
    """Extract free model IDs from the saved settings page snapshot.

    The snapshot contains a ``#free-plan-models`` section with a ``<ul>`` of
    ``<li>`` elements, each holding an ``<a>`` whose text is the model ID.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The set of free model IDs parsed from the snapshot.
    """
    settings_snapshot = next(
        (
            source["snapshot"]
            for source in provider_config["other_source"]
            if source["type"] == "settings"
        ),
        None,
    )
    if settings_snapshot is None:
        raise ValueError("no settings snapshot listed in other_source")

    snapshot_path = REPO_ROOT / settings_snapshot
    tree = parse_html(snapshot_path.read_bytes())
    free_section = None
    for node in tree.walk():
        if node.tag == "div" and node.attrs.get("id") == "free-plan-models":
            free_section = node
            break
    if free_section is None:
        return set()
    model_ids: set[str] = set()
    for anchor in free_section.walk():
        if anchor.tag != "a":
            continue
        href = anchor.attrs.get("href", "")
        if not href.startswith("/library/"):
            continue
        model_id = href.removeprefix("/library/").strip()
        if model_id:
            model_ids.add(model_id)
    return model_ids


def fetch(provider_config: dict) -> list[dict]:
    """Fetch the free Ollama Cloud models.

    Ollama's ``/v1/models`` endpoint is unauthenticated.  The free tier is a
    curated subset of all available models, identified by parsing the saved
    settings page snapshot.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The provider's free models as a list of dictionaries.
    """
    free_ids = _free_model_ids_from_snapshot(provider_config)
    payload = json.loads(get_url(models_url(provider_config)))
    return [model for model in payload["data"] if model["id"] in free_ids]
