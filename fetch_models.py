"""Fetch free model metadata from the configured providers (Python stdlib only)."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

from lib.http_client import one_line, safe_text
from providers import get_provider

ROOT = Path(__file__).resolve().parent

SAFE_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
MAX_FAILED_MESSAGE_CHARS = 300


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


def _load_payload(target: Path) -> dict:
    """Read the previously written wrapper, adopting the pre-wrapper format.

    Args:
        target: The provider's JSON file, which may not exist yet.

    Returns:
        The previous wrapper object, or an empty dict when the file is missing,
        unreadable or holds anything other than a JSON object or array. A bare
        array, the shape published before the wrapper existed, comes back as a
        wrapper holding that model list, so a failed fetch keeps the models it
        would otherwise discard.
    """
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        if target.exists():
            print(
                f"{target.name}: ignoring unusable previous data ({one_line(error)})",
                file=sys.stderr,
            )
        return {}
    if isinstance(payload, list):
        return {"data": payload}
    if not isinstance(payload, dict):
        return {}
    return payload


def _now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _target(output: Path, provider_id: str) -> Path:
    """Return the file a provider's data is stored in.

    Args:
        output: Directory the provider files live in.
        provider_id: Slug identifying the provider.

    Returns:
        The provider's JSON path inside ``output``.

    Raises:
        ValueError: If the provider id is unsafe as a file name.
    """
    if not SAFE_PROVIDER_ID.fullmatch(provider_id):
        raise ValueError(f"unsafe provider id: {provider_id!r}")
    return output / f"{provider_id}.json"


def _wrapper(
    status: str,
    models: list[dict],
    updated_at: str | None,
    failed_at: str | None,
    failed_message: str | None,
) -> dict:
    """Return the published wrapper for one provider result.

    Args:
        status: ``"success"`` or ``"failed"`` for the fetch that produced this.
        models: The model list to publish, always the latest successful one.
        updated_at: When that success happened, or None before there was one.
        failed_at: When the latest failure happened, or None when none did.
        failed_message: Sanitized text of the latest failure, or None when none
            did.

    Returns:
        The object written to the provider's file, with ``count`` derived from
        ``data`` here so the published pair can never disagree.
    """
    return {
        "status": status,
        "count": len(models),
        "updatedAt": updated_at,
        "lastFailedAt": failed_at,
        "lastFailedMessage": failed_message,
        "data": models,
    }


def _write_wrapper(target: Path, wrapper: dict) -> None:
    """Write ``wrapper`` to ``target``.

    The file is written atomically through a temporary file in the same
    directory, so a crash mid-write never leaves a partial file behind.
    """
    payload = json.dumps(wrapper, ensure_ascii=False, indent=2) + "\n"
    output = target.parent
    output.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{target.stem}-new-",
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


def save_provider(output: Path, provider_id: str, models: list[dict]) -> None:
    """Write a successful fetch as the provider's latest result.

    The new model list is stored under ``data`` with a fresh ``updatedAt`` and
    ``count``, while the failure details of the previous run, if any, are kept.

    Args:
        output: Directory to write the JSON file into.
        provider_id: Slug identifying the provider.
        models: Free model entries collected for the provider.

    Raises:
        ValueError: If the provider id is unsafe, the model list is empty or two
            models share an id.
        KeyError: If a model carries neither the ``id`` nor, for ``googleai``,
            the ``name`` the duplicate check reads.
    """
    target = _target(output, provider_id)
    if not models:
        raise ValueError("fetched no free models")
    models = list(models)
    ids = [
        model["name"] if provider_id == "googleai" else model["id"] for model in models
    ]
    if len({model_id.casefold() for model_id in ids}) != len(ids):
        raise ValueError("duplicate model id")
    previous = _load_payload(target)
    _write_wrapper(
        target,
        _wrapper(
            "success",
            models,
            _now(),
            previous.get("lastFailedAt"),
            previous.get("lastFailedMessage"),
        ),
    )


def record_failure(output: Path, provider_id: str, message: str) -> None:
    """Write a failed fetch as the provider's latest result.

    The previous ``updatedAt`` and ``data`` are republished so consumers still
    see the model list, and only the failure details are refreshed. A provider
    that has never succeeded records an empty list.

    Args:
        output: Directory to write the JSON file into.
        provider_id: Slug identifying the provider.
        message: The failure to publish. It is collapsed onto one line and
            capped here, because upstream servers write that text and every
            reader of the branch sees the result.

    Raises:
        ValueError: If the provider id is unsafe as a file name.
    """
    target = _target(output, provider_id)
    previous = _load_payload(target)
    models = previous.get("data")
    if not isinstance(models, list):
        models = []
    _write_wrapper(
        target,
        _wrapper(
            "failed",
            models,
            previous.get("updatedAt"),
            _now(),
            one_line(message)[:MAX_FAILED_MESSAGE_CHARS],
        ),
    )


def _credential_values(providers: list) -> set[str]:
    """Return the environment values the catalogue declares as credentials.

    A provider names its key through "ENV_VAR", and the server holding that key
    writes part of every failure message this script logs and publishes, so the
    values are collected to be stripped from those messages.
    """
    values = set()
    for provider in providers:
        name = provider.get("ENV_VAR") if isinstance(provider, dict) else None
        value = os.environ.get(name) if isinstance(name, str) else None
        if value:
            values.add(value)
    return values


def redact(text: str, credentials: set[str]) -> str:
    """Return ``text`` with every known credential value replaced.

    Args:
        text: A message built from upstream-controlled data.
        credentials: Secret values to strip, longest first so one secret cannot
            survive inside another secret's replacement.
    """
    for value in sorted(credentials, key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    return text


def run(providers_path: Path, output: Path) -> int:
    """Fetch and save free models for every provider in ``providers_path``.

    A provider whose fetch raises is reported on stderr and recorded in its own
    file with ``status: "failed"``, and the run carries on so the providers that
    succeeded still get published by the caller. That outcome is readable from
    the published data, so it does not change the exit code.

    Args:
        providers_path: JSON array of provider entries to fetch.
        output: Directory the provider files are written into.

    Returns:
        ``0`` when every provider's outcome reached its file, even if every
        provider failed. ``1`` when the run could not report what happened: the
        catalogue was unusable, or a result could not be written.
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
    if not providers:
        print(f"{providers_path.name}: lists no providers", file=sys.stderr)
        return 1
    credentials = _credential_values(providers)
    unreported = False
    fetched_ids: set[str] = set()
    for index, provider in enumerate(providers):
        provider_id = provider.get("id") if isinstance(provider, dict) else None
        if not isinstance(provider_id, str) or not SAFE_PROVIDER_ID.fullmatch(
            provider_id
        ):
            unreported = True
            print(
                f"provider at index {index}: entry needs an id that is safe"
                f" as a lowercase file name, got {provider_id!r}",
                file=sys.stderr,
            )
            continue
        if provider_id in fetched_ids:
            unreported = True
            print(
                f"provider at index {index}: duplicate id {provider_id!r}"
                " would overwrite the first entry's file",
                file=sys.stderr,
            )
            continue
        fetched_ids.add(provider_id)
        try:
            models = fetch_provider(provider)
            save_provider(output, provider_id, models)
        except Exception as error:  # noqa: BLE001
            # Top-level fault boundary: one provider's unexpected response
            # shape must not stop the providers after it, so anything raised
            # here is reported with its traceback instead of escaping. The
            # failure is also recorded in the provider's file so consumers see
            # the status flip with the models from the last success kept.
            print(
                f"{provider_id}: {redact(one_line(error), credentials)}",
                file=sys.stderr,
            )
            print(
                redact(safe_text(traceback.format_exc()), credentials), file=sys.stderr
            )
            try:
                record_failure(
                    output,
                    provider_id,
                    redact(f"{type(error).__name__}: {error}", credentials),
                )
            except Exception as record_error:  # noqa: BLE001
                unreported = True
                print(
                    f"{provider_id}: could not record failure: "
                    f"{one_line(record_error)}",
                    file=sys.stderr,
                )
        else:
            print(f"{provider_id}: saved {len(models)} free models")
    return 1 if unreported else 0


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
