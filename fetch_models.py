"""Fetch free model metadata from the configured providers (Python stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

from providers import get_provider
from providers.http_client import one_line, safe_text

ROOT = Path(__file__).resolve().parent


def fetch_provider(provider: dict) -> list[dict]:
    """Fetch the free models for one provider.

    Args:
        provider: A provider entry from providers.json.

    Returns:
        The provider's free models as a list of dictionaries.

    Raises:
        ValueError: If the provider is unsupported or an expected API key is
            not set.
    """
    provider_module = get_provider(provider["id"])
    return provider_module.fetch(provider)


def save_provider(output: Path, provider_id: str, models: list[dict]) -> None:
    """Write free models to ``<output>/<provider_id>.json``.

    The file is written atomically through a temporary file in the same
    directory.

    Args:
        output: Directory to write the JSON file into.
        provider_id: Slug identifying the provider.
        models: Free model entries collected for the provider.

    Raises:
        ValueError: If the provider id is unsafe, the model list is empty or
            two models share an id.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", provider_id):
        raise ValueError(f"unsafe provider id: {provider_id!r}")
    if not models:
        raise ValueError("fetched no free models; keeping existing data")
    models = list(models)
    ids = [
        model["name"] if provider_id == "googleai" else model["id"] for model in models
    ]
    if len({model_id.casefold() for model_id in ids}) != len(ids):
        raise ValueError("duplicate model id")
    payload = json.dumps(models, ensure_ascii=False, indent=2) + "\n"

    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{provider_id}.json"
    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{provider_id}-new-",
            suffix=".json",
            dir=output,
            delete=False,
        ) as staged_file:
            staging = Path(staged_file.name)
            staged_file.write(payload)
        os.replace(staging, target)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def run(providers_path: Path, output: Path) -> int:
    """Fetch and save free models for every provider in ``providers_path``.

    A failing provider is reported to stderr and does not stop the others, so
    the providers that did succeed still get published by the caller.

    Returns:
        ``0`` when every provider succeeded, otherwise ``1``.
    """
    try:
        providers = json.loads(providers_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"{providers_path.name}: {one_line(error)}", file=sys.stderr)
        return 1
    if not isinstance(providers, list):
        print(
            f"{providers_path.name}: expected a JSON array of providers, "
            f"got {type(providers).__name__}",
            file=sys.stderr,
        )
        return 1
    failures = 0
    for index, provider in enumerate(providers):
        provider_id = provider.get("id") if isinstance(provider, dict) else None
        if not isinstance(provider_id, str):
            failures += 1
            print(
                f'provider at index {index}: entry is not an object with an "id"',
                file=sys.stderr,
            )
            continue
        try:
            models = fetch_provider(provider)
            save_provider(output, provider_id, models)
            print(f"{provider_id}: saved {len(models)} free models")
        except Exception as error:  # noqa: BLE001
            # Top-level fault boundary: one provider's unexpected response
            # shape must not stop the providers after it, so anything raised
            # here is reported with its traceback instead of escaping.
            failures += 1
            print(f"{provider_id}: {one_line(error)}", file=sys.stderr)
            print(safe_text(traceback.format_exc()), file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    """Run the fetch script from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        type=Path,
        default=ROOT / "providers.json",
        help="provider catalogue to read (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data",
        help="directory for the generated JSON files (default: %(default)s)",
    )
    args = parser.parse_args()
    return run(args.providers, args.output)


if __name__ == "__main__":
    sys.exit(main())
