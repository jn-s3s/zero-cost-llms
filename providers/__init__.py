"""Registry mapping provider ids to their fetching modules."""

from . import googleai, nvidia, openrouter, requesty, routeway
from .base import Provider

REGISTRY = {
    "googleai": googleai,
    "nvidia": nvidia,
    "openrouter": openrouter,
    "requesty": requesty,
    "routeway": routeway,
}


def get_provider(provider_id: str) -> Provider:
    """Return the fetching module registered for ``provider_id``.

    Args:
        provider_id: A provider id from providers.json.

    Returns:
        The module exposing a ``fetch(provider_config)`` function.

    Raises:
        ValueError: If the provider id is not registered.
    """
    if provider_id not in REGISTRY:
        raise ValueError(f"unsupported provider: {provider_id}")
    return REGISTRY[provider_id]
