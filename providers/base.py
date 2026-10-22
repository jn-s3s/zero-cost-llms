"""Protocol and shared config helpers for provider implementations."""

from typing import Protocol


class Provider(Protocol):
    """Fetch free models from a single provider.

    Implementations are provided as module-level ``fetch`` functions that
    satisfy this shape.
    """

    def fetch(self, provider_config: dict) -> list[dict]:
        """Return the provider's free models for ``provider_config``."""
        ...


def models_url(provider_config: dict) -> str:
    """Return the absolute models endpoint for one ``config/providers.json`` entry.

    Args:
        provider_config: A provider entry from config/providers.json.

    Returns:
        The base URL joined to the models endpoint with a single separator.
    """
    api = provider_config["api"]
    endpoint = api["models"]["endpoint"]
    return api["baseUrl"].rstrip("/") + "/" + endpoint.lstrip("/")
