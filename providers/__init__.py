"""Registry mapping provider ids to their fetching modules."""

from . import (
    agnes,
    cerebras,
    cline,
    cloudflare,
    cohere,
    googleai,
    groq,
    kilo,
    llm7,
    mistral,
    nvidia,
    ollama_cloud,
    opencode_zen,
    openrouter,
    orcarouter,
    pollinations,
    qoder,
    requesty,
    routeway,
    zai,
)
from .base import Provider

REGISTRY = {
    "agnes": agnes,
    "cerebras": cerebras,
    "cline": cline,
    "cloudflare": cloudflare,
    "cohere": cohere,
    "googleai": googleai,
    "groq": groq,
    "kilo": kilo,
    "llm7": llm7,
    "mistral": mistral,
    "nvidia": nvidia,
    "ollama-cloud": ollama_cloud,
    "openrouter": openrouter,
    "opencode-zen": opencode_zen,
    "orcarouter": orcarouter,
    "pollinations": pollinations,
    "qoder": qoder,
    "requesty": requesty,
    "routeway": routeway,
    "zai": zai,
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
