"""Parsing of rate-limit values scraped from provider documentation pages."""

from __future__ import annotations


def parse_limit_value(text: str) -> int | float | None:
    """Parse a rate limit that may carry a "K" or "M" suffix, like "14.4K".

    Args:
        text: The raw cell text.

    Returns:
        The limit as an int when it is a whole number, otherwise the float as
        written, so "2.08" survives instead of truncating to 2. None for a
        blank or unparseable cell, so a page that writes "Unlimited", "N/A"
        or "-" keeps its row without inventing a number.
    """
    text = text.strip()
    if not text or text == "-":
        return None
    text = text.replace(",", "")
    multiplier = 1
    if text.upper().endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.upper().endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        value = float(text) * multiplier
    except ValueError:
        return None
    return int(value) if value == int(value) else value
