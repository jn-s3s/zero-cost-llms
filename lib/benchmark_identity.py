"""Resolve documented checkpoint identities without heuristic name matching."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

SAFE_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
SOURCE_IDS = frozenset(
    {"livebench", "evalplus", "aider_polyglot", "bigcodebench", "aider_python"}
)


def require_object(value: object, label: str) -> dict:
    """Require a JSON object at a named contract boundary."""
    if not isinstance(value, dict):
        raise TypeError(f"{label}: expected an object")
    return value


def require_text(value: object, label: str) -> str:
    """Require nonempty text without changing its literal identity."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: expected nonempty text")
    return value


def _array(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise TypeError(f"{label}: expected an array")
    return value


def provider_ids(path: Path) -> list[str]:
    """Read configured providers and reject unsafe or duplicate filenames."""
    entries = _array(json.loads(path.read_text(encoding="utf-8")), "providers")
    if not entries:
        raise ValueError("providers: empty catalogue")
    ids: list[str] = []
    for raw in entries:
        provider_id = require_object(raw, "provider").get("id")
        if not isinstance(provider_id, str) or not SAFE_PROVIDER_ID.fullmatch(
            provider_id
        ):
            raise ValueError("provider: unsafe id")
        if provider_id in ids:
            raise ValueError(f"provider: duplicate {provider_id!r}")
        ids.append(provider_id)
    return ids


def _active_provider(
    entry: dict, providers: list[str], issues: list[dict], mapping_type: str
) -> bool:
    provider_id = require_text(entry.get("providerId"), "providerId")
    if not SAFE_PROVIDER_ID.fullmatch(provider_id):
        raise ValueError("mapping: unsafe provider id")
    if provider_id not in providers:
        issues.append(
            {
                "scope": "mapping",
                "code": "removed_provider_mapping",
                "providerId": provider_id,
                "mappingType": mapping_type,
                "message": "Reference ignored because the provider is not configured.",
            }
        )
        return False
    return True


def _pair(entry: dict) -> tuple[str, str]:
    return entry["providerId"], require_text(entry.get("modelId"), "modelId")


def load_identities(path: Path, providers: list[str]) -> dict:
    """Validate the v2 identity, exclusion and explicit transformation contract."""
    config = require_object(json.loads(path.read_text(encoding="utf-8")), "mappings")
    json.dumps(config, allow_nan=False)
    if type(config.get("schemaVersion")) is not int or config["schemaVersion"] != 2:
        raise ValueError("mappings: schemaVersion must be 2")
    identities: dict[str, dict] = {}
    offerings: dict[tuple[str, str], dict] = {}
    evaluations: dict[tuple[str, str], list[dict]] = {}
    issues: list[dict] = []
    for raw in _array(config.get("identities"), "identities"):
        identity = require_object(raw, "identity")
        canonical_id = require_text(identity.get("canonicalId"), "canonicalId")
        if canonical_id.startswith("offering:") or canonical_id in identities:
            raise ValueError(
                f"identity: reserved or duplicate canonicalId {canonical_id!r}"
            )
        require_text(identity.get("displayName"), "displayName")
        if canonical_id.startswith("hf:") and not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", canonical_id[3:]
        ):
            raise ValueError("identity: malformed HF canonical identifier")
        for url in _array(
            identity.get("reviewedCheckpointUrls", []), "reviewedCheckpointUrls"
        ):
            _reviewed_url(url, "reviewedCheckpointUrls entry")
            if _hf_slug(url) is None:
                raise ValueError(
                    "reviewedCheckpointUrls: expected an HF checkpoint URL"
                )
        identities[canonical_id] = identity
        for raw_offering in _array(identity.get("offerings"), "offerings"):
            offering = require_object(raw_offering, "offering")
            if not _active_provider(offering, providers, issues, "offering"):
                continue
            pair = _pair(offering)
            require_text(offering.get("evidence"), "offering.evidence")
            if "expectedName" in offering:
                require_text(offering["expectedName"], "expectedName")
            if "expectedMetadata" in offering:
                require_object(offering["expectedMetadata"], "expectedMetadata")
            if pair in offerings:
                raise ValueError(f"offering: duplicate pair {pair!r}")
            offerings[pair] = {**offering, "canonicalId": canonical_id}
        for raw_evaluation in _array(identity.get("evaluations"), "evaluations"):
            evaluation = require_object(raw_evaluation, "evaluation mapping")
            source_id = require_text(evaluation.get("sourceId"), "sourceId")
            if source_id not in SOURCE_IDS:
                raise ValueError(
                    f"evaluation mapping: unsupported source {source_id!r}"
                )
            model_id = require_text(evaluation.get("modelId"), "evaluation.modelId")
            require_text(evaluation.get("evidence"), "evaluation.evidence")
            if "configuration" in evaluation:
                require_object(evaluation["configuration"], "evaluation.configuration")
            if "expectedModelUrl" in evaluation:
                _reviewed_url(evaluation["expectedModelUrl"], "expectedModelUrl")
            pair = (source_id, model_id)
            existing = evaluations.setdefault(pair, [])
            if existing and existing[0]["canonicalId"] != canonical_id:
                raise ValueError(f"evaluation mapping: conflicting identity {pair!r}")
            linked = {**evaluation, "canonicalId": canonical_id}
            if linked not in existing:
                existing.append(linked)
    exclusions: dict[tuple[str, str], dict] = {}
    for raw in _array(config.get("exclusions", []), "exclusions"):
        entry = require_object(raw, "exclusion")
        if not _active_provider(entry, providers, issues, "exclusion"):
            continue
        pair = _pair(entry)
        require_text(entry.get("reason"), "exclusion.reason")
        require_text(entry.get("evidence"), "exclusion.evidence")
        if pair in exclusions:
            raise ValueError(f"exclusion: duplicate pair {pair!r}")
        exclusions[pair] = entry
    rules: list[dict] = []
    for rule in _array(config.get("automaticRules", []), "automaticRules"):
        require_object(rule, "automatic rule")
        if not _active_provider(rule, providers, issues, "automaticRule"):
            continue
        require_text(rule.get("evidence"), "automatic rule.evidence")
        for key in ("idPrefix", "idSuffix", "checkpointNamespace"):
            if key in rule:
                require_text(rule[key], f"automatic rule.{key}")
        rules.append(rule)
    return {
        "identities": identities,
        "offerings": offerings,
        "evaluations": evaluations,
        "exclusions": exclusions,
        "rules": rules,
        "issues": issues,
    }


def configuration_matches(expected: dict, actual: dict) -> bool:
    """Constrain only documented configuration fields, preserving the harness."""
    for key, value in expected.items():
        if key not in actual:
            return False
        if isinstance(value, dict):
            if not isinstance(actual[key], dict) or not configuration_matches(
                value, actual[key]
            ):
                return False
        elif type(value) is not type(actual[key]) or value != actual[key]:
            return False
    return True


def _hf_slug(
    url: object, issues: list[dict] | None = None, context: dict | None = None
) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        if issues is not None:
            issues.append(
                {
                    **(context or {}),
                    "code": "invalid_model_url",
                    "message": "Malformed optional model URL; not used for automatic identity.",
                }
            )
        return None
    parts = parsed.path.strip("/").split("/")
    if hostname != "huggingface.co" or len(parts) != 2:
        return None
    if parts[0] in {"datasets", "spaces"} or not all(parts):
        return None
    return "/".join(parts).casefold()


def _reviewed_url(value: object, label: str) -> str:
    url = require_text(value, label)
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as error:
        raise ValueError(f"{label}: malformed URL") from error
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise ValueError(f"{label}: expected an HTTPS URL without credentials")
    return url


def evaluation_identity_matches(mapping: dict, record: dict) -> bool:
    """Apply a reviewed evaluated URL guard without trusting refreshed URLs."""
    if "expectedModelUrl" not in mapping:
        return True
    expected = mapping["expectedModelUrl"]
    actual = record.get("modelUrl")
    expected_slug = _hf_slug(expected)
    if expected_slug is not None:
        return expected_slug == _hf_slug(actual)
    return expected == actual


def trusted_slugs(
    config: dict, sources: list[dict], issues: list[dict] | None = None
) -> dict[str, set[str]]:
    """Index only reviewed HF identities, never labels' refreshed model URLs."""
    slugs: dict[str, set[str]] = {}
    for canonical_id, identity in config["identities"].items():
        if canonical_id.startswith("hf:"):
            slugs.setdefault(canonical_id.casefold(), set()).add(canonical_id)
        for url in identity.get("reviewedCheckpointUrls", []):
            slug = _hf_slug(url)
            if slug is not None:
                slugs.setdefault(f"hf:{slug}", set()).add(canonical_id)
    # Optional current URLs can produce diagnostics, but cannot establish an
    # automatic alias or mutate any reviewed checkpoint's slug index.
    for source in sources:
        snapshot = source.get("snapshot")
        if not snapshot:
            continue
        for cohort in snapshot["cohorts"]:
            for row in cohort["records"]:
                _hf_slug(
                    row.get("modelUrl"),
                    issues,
                    {
                        "scope": "evaluation",
                        "sourceId": source["sourceId"],
                        "cohort": cohort["id"],
                        "evaluationId": row["evaluationId"],
                    },
                )
    return slugs


def resolve_offering(
    provider_id: str,
    model_id: str,
    model: dict,
    config: dict,
    slugs: dict[str, set[str]],
) -> tuple[str | None, dict | None, str | None]:
    """Resolve exact offerings first, then documented transforms to trusted slugs."""
    explicit = config["offerings"].get((provider_id, model_id))
    if explicit is not None:
        expected = explicit.get("expectedName")
        actual_name = next(
            (
                model[key]
                for key in ("name", "displayName", "display_name")
                if isinstance(model.get(key), str) and model[key].strip()
            ),
            None,
        )
        if expected is not None and expected != actual_name:
            return None, explicit, "expected_name_mismatch"
        if not configuration_matches(explicit.get("expectedMetadata", {}), model):
            return None, explicit, "expected_metadata_mismatch"
        return explicit["canonicalId"], explicit, None
    candidates: dict[str, dict] = {}
    for rule in config["rules"]:
        if rule["providerId"] != provider_id:
            continue
        transformed = model_id
        prefix, suffix = rule.get("idPrefix"), rule.get("idSuffix")
        if prefix is not None:
            if not transformed.startswith(prefix):
                continue
            transformed = transformed[len(prefix) :]
        if suffix is not None:
            if not transformed.endswith(suffix):
                continue
            transformed = transformed[: -len(suffix)]
        namespace = rule.get("checkpointNamespace")
        if namespace and namespace not in {"hf", "huggingface", "huggingface.co"}:
            transformed = f"{namespace}/{transformed}"
        matches = set(slugs.get(transformed, set()))
        if "/" in transformed:
            matches.update(slugs.get(f"hf:{transformed.casefold()}", set()))
        for canonical_id in matches:
            candidates[canonical_id] = rule
    if len(candidates) == 1:
        canonical_id = next(iter(candidates))
        return (
            canonical_id,
            {"canonicalId": canonical_id, "automaticRule": candidates[canonical_id]},
            None,
        )
    return None, None, "ambiguous_automatic_identity" if candidates else None


def eligibility(model: dict) -> tuple[str, str]:
    """Use declared tasks/output support, never coding-related name substrings."""
    architecture = model.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    modalities = model.get("output_modalities", architecture.get("output_modalities"))
    if isinstance(modalities, list) and modalities:
        outputs = {str(item).lower() for item in modalities}
        if "text" not in outputs:
            return "excluded", "declared_non_text_output"
    tasks: list[str] = []
    for key in ("task", "tasks", "pipeline_tag", "type"):
        value = model.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                item = item.get("name", item.get("id"))
            if isinstance(item, str):
                tasks.append(item.lower().replace("_", "-").replace(" ", "-"))
    excluded = {
        "embedding",
        "embeddings",
        "text-embedding",
        "text-embeddings",
        "feature-extraction",
        "rerank",
        "reranker",
        "reranking",
        "guard",
        "safety",
        "moderation",
        "text-classification",
        "image-generation",
        "text-to-image",
        "image-to-image",
        "audio",
        "speech",
        "asr",
        "text-to-speech",
        "automatic-speech-recognition",
        "audio-classification",
        "audio-to-text",
        "audio-generation",
        "image",
    }
    generation = {
        "text-generation",
        "text2text-generation",
        "chat",
        "completion",
        "completions",
        "conversational",
        "image-text-to-text",
        "multimodal-generation",
        "text-to-text",
    }
    methods = model.get("supportedGenerationMethods", [])
    capabilities = model.get("capabilities")
    if isinstance(capabilities, dict) and any(
        capabilities.get(key) is True
        for key in ("chat", "completion", "text_generation")
    ):
        return "eligible", "declared_text_generation_capability"
    if any(task in generation for task in tasks) or (
        isinstance(methods, list)
        and any(method in methods for method in ("generateContent", "generateText"))
    ):
        return "eligible", "declared_text_generation"
    if tasks and all(task in excluded for task in tasks):
        return "excluded", "declared_non_generation_task"
    if isinstance(modalities, list) and "text" in {
        str(item).lower() for item in modalities
    }:
        return "eligible", "declared_text_output"
    return "uncertain", "generation_capability_not_declared"
