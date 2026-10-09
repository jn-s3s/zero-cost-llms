"""Publish checkpoint evidence and provisional frozen-panel coding tiers."""

from __future__ import annotations

import datetime
import hashlib
import importlib
import json
import math
import os
import sys
import tempfile
import uuid
from pathlib import Path

from lib.benchmark_identity import (
    SOURCE_IDS,
    configuration_matches,
    eligibility,
    evaluation_identity_matches,
    load_identities,
    provider_ids,
    require_object,
    require_text,
    resolve_offering,
    trusted_slugs,
)
from lib.benchmark_tiers import load_policy, score_models
from lib.repo_root import REPO_ROOT

_FAILURES = (OSError, ValueError, TypeError, OverflowError, ImportError)
_WORKLOADS = {
    "generation_debugging": "generationDebugging",
    "repository_editing": "repositoryEditing",
}
_DEFAULT_SOURCES = ("livebench", "evalplus", "aider_polyglot", "bigcodebench")


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _message(error: object) -> str:
    return " ".join(str(error).split())[:300]


def _list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise TypeError(f"{label}: expected an array")
    return value


def _nullable_text(value: object, label: str) -> None:
    if value is not None:
        require_text(value, label)


def _validate_source(payload: object, source_id: str) -> dict:
    source = require_object(payload, source_id)
    json.dumps(source, allow_nan=False)
    if type(source.get("schemaVersion")) is not int or source["schemaVersion"] != 2:
        raise ValueError(f"{source_id}: schemaVersion must be 2")
    if source.get("sourceId") != source_id or source_id not in SOURCE_IDS:
        raise ValueError(f"{source_id}: invalid sourceId")
    require_text(source.get("benchmark"), "benchmark")
    if source.get("status") not in {"success", "failed"}:
        raise ValueError(f"{source_id}: invalid status")
    for key in ("updatedAt", "lastFailedAt", "lastFailedMessage"):
        _nullable_text(source.get(key), key)
    snapshot = source.get("snapshot")
    if snapshot is None:
        if source["status"] == "success":
            raise ValueError(f"{source_id}: successful source lacks snapshot")
        return source
    snapshot = require_object(snapshot, "snapshot")
    for key in ("revision", "sourceUrl", "capturedAt", "contentHash"):
        require_text(snapshot.get(key), f"snapshot.{key}")
    cohort_ids: set[str] = set()
    for raw in _list(snapshot.get("cohorts"), "cohorts"):
        cohort = require_object(raw, "cohort")
        cohort_id = require_text(cohort.get("id"), "cohort.id")
        if cohort_id in cohort_ids:
            raise ValueError(f"{source_id}: duplicate cohort {cohort_id!r}")
        cohort_ids.add(cohort_id)
        if cohort.get("workload") not in _WORKLOADS:
            raise ValueError("cohort: unsupported workload")
        for key in ("label", "metric"):
            require_text(cohort.get(key), f"cohort.{key}")
        _nullable_text(cohort.get("release"), "release")
        if (
            cohort.get("unit") not in {"percent", "score_0_100"}
            or cohort.get("direction") != "higher"
        ):
            raise ValueError("cohort: unsupported unit or direction")
        evaluation_ids: set[str] = set()
        for raw_record in _list(cohort.get("records"), "records"):
            record = require_object(raw_record, "record")
            evaluation_id = require_text(record.get("evaluationId"), "evaluationId")
            if evaluation_id in evaluation_ids:
                raise ValueError(f"cohort: duplicate evaluationId {evaluation_id!r}")
            evaluation_ids.add(evaluation_id)
            require_text(record.get("modelId"), "evaluated modelId")
            require_object(record.get("configuration"), "configuration")
            score = record.get("score")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not 0 <= score <= 100
            ):
                raise ValueError("record: score must be finite from 0 to 100")
            for key in ("modelUrl", "evaluatedAt"):
                _nullable_text(record.get(key), key)
            count = record.get("taskCount")
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError(
                    "record: taskCount must be a nonnegative integer or null"
                )
    return source


def _load_sources(
    seeds: Path, cache: Path | None
) -> tuple[list[dict], list[dict], list[dict], dict]:
    loaded: list[dict] = []
    states: list[dict] = []
    issues: list[dict] = []
    input_hashes: dict[str, dict] = {}
    wanted = list(_DEFAULT_SOURCES)
    if (seeds / "aider_python.json").exists() or (
        cache is not None and (cache / "aider_python.json").exists()
    ):
        wanted.append("aider_python")
    for source_id in wanted:
        candidates = (
            [("cache", cache / f"{source_id}.json")] if cache is not None else []
        )
        candidates.append(("seed", seeds / f"{source_id}.json"))
        source = None
        origin = None
        for candidate_origin, path in candidates:
            try:
                candidate = _validate_source(_read(path), source_id)
                source_hash = _hash(path)
            except FileNotFoundError:
                continue
            except _FAILURES as error:
                issues.append(
                    {
                        "scope": "source",
                        "sourceId": source_id,
                        "code": "source_invalid",
                        "origin": candidate_origin,
                        "message": _message(error),
                    }
                )
            else:
                source = candidate
                origin = candidate_origin
                input_hashes[source_id] = {"origin": origin, "sha256": source_hash}
                break
        if source is None:
            states.append(
                {"sourceId": source_id, "status": "unavailable", "hasSnapshot": False}
            )
            issues.append(
                {"scope": "source", "sourceId": source_id, "code": "source_unavailable"}
            )
            continue
        loaded.append(source)
        snapshot = source.get("snapshot")
        states.append(
            {
                "sourceId": source_id,
                "benchmark": source["benchmark"],
                "status": source["status"],
                "updatedAt": source.get("updatedAt"),
                "lastFailedAt": source.get("lastFailedAt"),
                "hasSnapshot": snapshot is not None,
                "revision": snapshot["revision"] if snapshot else None,
                "origin": origin,
            }
        )
        if source["status"] == "failed":
            issues.append(
                {
                    "scope": "source",
                    "sourceId": source_id,
                    "code": "retained_failed_source"
                    if snapshot
                    else "source_never_succeeded",
                    "message": _message(source.get("lastFailedMessage", "")),
                }
            )
    return loaded, states, issues, input_hashes


def _provider_models(
    path: Path, provider_id: str
) -> tuple[list[tuple[str, dict]], dict]:
    payload = _read(path)
    if isinstance(payload, list):
        models, metadata = payload, {"status": "legacy", "updatedAt": None}
    else:
        metadata = require_object(payload, "provider payload")
        models = _list(metadata.get("data"), "provider data")
        if metadata.get("status") not in {"success", "failed"}:
            raise ValueError("provider: invalid status")
    active: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for raw in models:
        model = require_object(raw, "provider model")
        if model.get("presence") == "removed":
            continue
        model_id = require_text(
            model.get("name" if provider_id == "googleai" else "id"),
            "provider model id",
        )
        if model_id in seen:
            raise ValueError(f"provider: duplicate active model {model_id!r}")
        seen.add(model_id)
        active.append((model_id, model))
    return active, {
        key: metadata.get(key)
        for key in ("status", "updatedAt", "lastFailedAt", "lastFailedMessage")
    }


def _display_name(model: dict, fallback: str) -> str:
    return next(
        (
            model[key]
            for key in ("displayName", "display_name", "name")
            if isinstance(model.get(key), str) and model[key].strip()
        ),
        fallback,
    )


def _evidence(
    config: dict, sources: list[dict]
) -> tuple[dict[str, dict], list[dict], list[dict]]:
    by_identity: dict[str, dict] = {}
    details: list[dict] = []
    issues: list[dict] = []
    for source in sources:
        snapshot = source.get("snapshot")
        if snapshot is None:
            continue
        for cohort in snapshot["cohorts"]:
            view = _WORKLOADS[cohort["workload"]]
            for record in cohort["records"]:
                mappings = config["evaluations"].get(
                    (source["sourceId"], record["modelId"]), []
                )
                matches = [
                    mapping
                    for mapping in mappings
                    if configuration_matches(
                        mapping.get("configuration", {}), record["configuration"]
                    )
                ]
                if not matches:
                    if mappings:
                        issues.append(
                            {
                                "scope": "evaluation",
                                "sourceId": source["sourceId"],
                                "cohort": cohort["id"],
                                "evaluationId": record["evaluationId"],
                                "code": "evaluation_configuration_mismatch",
                            }
                        )
                    continue
                matches = [
                    mapping
                    for mapping in matches
                    if evaluation_identity_matches(mapping, record)
                ]
                if not matches:
                    issues.append(
                        {
                            "scope": "evaluation",
                            "sourceId": source["sourceId"],
                            "cohort": cohort["id"],
                            "evaluationId": record["evaluationId"],
                            "code": "evaluation_model_url_mismatch",
                        }
                    )
                    continue
                canonical_id = matches[0]["canonicalId"]
                evidence_id = (
                    "evidence:"
                    + hashlib.sha256(
                        json.dumps(
                            [
                                source["sourceId"],
                                snapshot["revision"],
                                cohort["id"],
                                record["evaluationId"],
                            ]
                        ).encode()
                    ).hexdigest()[:24]
                )
                result = {
                    "benchmark": source["benchmark"],
                    "evaluatedModelId": record["modelId"],
                    "cohort": cohort["id"],
                    "metric": cohort["metric"],
                    "score": record["score"],
                    "unit": cohort["unit"],
                    "configuration": record["configuration"],
                    "evidenceId": evidence_id,
                    "applicability": "checkpoint_evidence_endpoint_unverified",
                    "configurationStatus": "published"
                    if record["configuration"]
                    else "unknown",
                }
                by_identity.setdefault(
                    canonical_id, {"generationDebugging": [], "repositoryEditing": []}
                )[view].append(result)
                details.append(
                    {
                        "evidenceId": evidence_id,
                        "canonicalId": canonical_id,
                        "sourceId": source["sourceId"],
                        "cohort": cohort["id"],
                        "evaluationId": record["evaluationId"],
                        "evaluatedModelId": record["modelId"],
                        "mappingEvidence": sorted(
                            {mapping["evidence"] for mapping in matches}
                        ),
                        "configurationConstraints": [
                            mapping.get("configuration", {}) for mapping in matches
                        ],
                        "applicability": "checkpoint_evidence_endpoint_unverified",
                        "endpointConfigurationParity": "unknown",
                    }
                )
    for views in by_identity.values():
        for results in views.values():
            results.sort(
                key=lambda result: (
                    result["benchmark"],
                    result["cohort"],
                    result["evidenceId"],
                )
            )
    return by_identity, details, issues


def build_rankings(
    input_path: Path,
    sources: Path,
    mappings_path: Path,
    providers_path: Path,
    cache_path: Path | None = None,
    *,
    policy_path: Path | None = None,
) -> dict:
    """Build provisional tiers, two evidence views and a full provenance audit.

    Raw incompatible scores are never averaged. Frozen public panels supply
    workload-relative indices; missing data stays visible as a limitation.
    """
    policy, policy_hash = load_policy(
        policy_path or REPO_ROOT / "config/benchmarks/benchmark_tier_policy.json"
    )
    configured = provider_ids(providers_path)
    config = load_identities(mappings_path, configured)
    loaded, source_states, issues, source_hashes = _load_sources(sources, cache_path)
    issues.extend(config["issues"])
    slugs = trusted_slugs(config, loaded, issues)
    evidence, evidence_details, evidence_issues = _evidence(config, loaded)
    issues.extend(evidence_issues)
    models: dict[str, dict] = {}
    offering_details: list[dict] = []
    excluded: list[dict] = []
    provider_states: list[dict] = []
    active_count = eligible_count = uncertain_count = 0
    for provider_id in configured:
        path = input_path / f"{provider_id}.json"
        try:
            active, metadata = _provider_models(path, provider_id)
            input_hash = _hash(path)
        except _FAILURES as error:
            issues.append(
                {
                    "scope": "provider",
                    "providerId": provider_id,
                    "code": "provider_unavailable",
                    "message": _message(error),
                }
            )
            provider_states.append(
                {"providerId": provider_id, "available": False, "activeOfferings": None}
            )
            continue
        provider_states.append(
            {
                "providerId": provider_id,
                "available": True,
                **metadata,
                "inputHash": input_hash,
                "activeOfferings": len(active),
            }
        )
        if metadata["status"] != "success":
            issues.append(
                {
                    "scope": "provider",
                    "providerId": provider_id,
                    "code": "retained_failed_provider"
                    if metadata["status"] == "failed"
                    else "legacy_provider",
                }
            )
        for model_id, model in active:
            active_count += 1
            pair = (provider_id, model_id)
            decision, reason = eligibility(model)
            exclusion = config["exclusions"].get(pair)
            if exclusion is not None:
                decision, reason = "excluded", exclusion["reason"]
            detail = {
                "providerId": provider_id,
                "modelId": model_id,
                "name": _display_name(model, model_id),
                "eligibility": decision,
                "eligibilityReason": reason,
                "providerStatus": metadata["status"],
                "providerUpdatedAt": metadata["updatedAt"],
                "providerMetadata": model,
            }
            if decision == "excluded":
                detail["reviewedExclusion"] = exclusion
                excluded.append(detail)
                continue
            eligible_count += decision == "eligible"
            uncertain_count += decision == "uncertain"
            canonical_id, mapping, resolution_issue = resolve_offering(
                provider_id, model_id, model, config, slugs
            )
            if resolution_issue:
                issues.append(
                    {
                        "scope": "provider-model",
                        "providerId": provider_id,
                        "modelId": model_id,
                        "code": resolution_issue,
                    }
                )
            established = canonical_id is not None
            canonical_id = canonical_id or f"offering:{provider_id}:{model_id}"
            detail.update(
                {
                    "canonicalId": canonical_id,
                    "identityStatus": "established" if established else "unresolved",
                    "identityEvidence": mapping,
                }
            )
            offering_details.append(detail)
            if canonical_id not in models:
                identity = config["identities"].get(canonical_id)
                views = evidence.get(
                    canonical_id, {"generationDebugging": [], "repositoryEditing": []}
                )
                models[canonical_id] = {
                    "modelId": canonical_id,
                    "name": identity["displayName"] if identity else detail["name"],
                    "eligibility": decision,
                    "identityStatus": detail["identityStatus"],
                    "providers": [],
                    **views,
                }
            if decision == "eligible":
                models[canonical_id]["eligibility"] = "eligible"
            models[canonical_id]["providers"].append(
                {"providerId": provider_id, "modelId": model_id}
            )
    rows = list(models.values())
    tier_scoring = score_models(rows, evidence_details, loaded, policy, policy_hash)
    for row in rows:
        row["providers"].sort(
            key=lambda offering: (offering["providerId"], offering["modelId"])
        )
    generation_count = sum(bool(row["generationDebugging"]) for row in rows)
    editing_count = sum(bool(row["repositoryEditing"]) for row in rows)
    if not generation_count and not editing_count:
        issues.append(
            {
                "scope": "catalogue",
                "code": "no_matched_evidence",
                "message": "No active checkpoint has matched supported benchmark evidence.",
            }
        )
    summary = {
        "activeOfferings": active_count,
        "eligibleOfferings": eligible_count,
        "excludedOfferings": len(excluded),
        "uncertainOfferings": uncertain_count,
        "models": len(rows),
        "modelsWithGenerationEvidence": generation_count,
        "modelsWithEditingEvidence": editing_count,
        "ratedModels": sum(row["tier"] != "Unrated" for row in rows),
        "unratedModels": sum(row["tier"] == "Unrated" for row in rows),
        "tierCounts": {
            tier: sum(row["tier"] == tier for row in rows)
            for tier in [entry["tier"] for entry in policy["tierThresholds"]]
            + ["Unrated"]
        },
    }
    offering_generation = sum(
        bool(models[detail["canonicalId"]]["generationDebugging"])
        for detail in offering_details
    )
    offering_editing = sum(
        bool(models[detail["canonicalId"]]["repositoryEditing"])
        for detail in offering_details
    )
    return {
        "main": {
            "policyVersion": policy["policyVersion"],
            "tierInterpretation": policy["interpretation"],
            "summary": summary,
            "sourceStates": source_states,
            "data": rows,
        },
        "audit": {
            "policyVersion": policy["policyVersion"],
            "tierScoring": tier_scoring,
            "summary": summary,
            "sources": loaded,
            "providers": provider_states,
            "inputHashes": {
                "mappings": _hash(mappings_path),
                "providers": _hash(providers_path),
                "sources": source_hashes,
                "tierPolicy": {"sha256": policy_hash},
            },
            "identities": list(config["identities"].values()),
            "offerings": offering_details,
            "excludedOfferings": excluded,
            "evidence": evidence_details,
            "issues": issues,
            "coverage": {
                "denominator": "available active eligible and uncertain offerings; unavailable provider totals are unknown",
                "availableOfferings": len(offering_details),
                "canonicalModels": len(rows),
                "offeringsWithGenerationEvidence": offering_generation,
                "offeringsWithEditingEvidence": offering_editing,
                "canonicalModelsWithGenerationEvidence": generation_count,
                "canonicalModelsWithEditingEvidence": editing_count,
                "offeringsWithoutEvidence": sum(
                    not bool(
                        models[detail["canonicalId"]]["generationDebugging"]
                        or models[detail["canonicalId"]]["repositoryEditing"]
                    )
                    for detail in offering_details
                ),
                "canonicalModelsWithoutEvidence": sum(
                    not bool(row["generationDebugging"] or row["repositoryEditing"])
                    for row in rows
                ),
                "unavailableProviders": sum(
                    not state["available"] for state in provider_states
                ),
                "completeCurrentProviderCoverage": all(
                    state.get("status") == "success" for state in provider_states
                ),
            },
            "interpretation": "Provisional policy tiers summarize frozen-panel relative indices, not percentages solved or calibrated endpoint performance. Raw benchmark scores remain separate. Endpoint configuration parity is unverified.",
            "unsupportedSources": [
                {
                    "benchmark": "LiveCodeBench",
                    "status": "unsupported",
                    "reason": "Deferred: revision and evaluation-configuration mapping not implemented.",
                },
                {
                    "benchmark": "Arena",
                    "status": "unsupported",
                    "reason": "Deferred: preference evidence is not a supported coding workload cohort.",
                },
                {
                    "benchmark": "SWE-bench",
                    "status": "unsupported",
                    "reason": "Deferred: agent/scaffold identity is not verified endpoint evidence.",
                },
            ],
        },
    }


def _stage(target: Path, contents: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        prefix=f".{target.stem}-",
        suffix=".json",
        delete=False,
    ) as stream:
        staging = Path(stream.name)
        try:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            stream.close()
            staging.unlink(missing_ok=True)
            raise
    return staging


def _serialize(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _publish_pair(main_path: Path, main: dict, audit_path: Path, audit: dict) -> None:
    # Both files are staged before publication. Main is the commit marker; readers
    # must verify its auditRef generationId against the audit before using it.
    staged: list[Path] = []
    try:
        previous_audit = audit_path.read_bytes()
    except FileNotFoundError:
        previous_audit = None
    try:
        staged_audit = _stage(audit_path, _serialize(audit))
        staged.append(staged_audit)
        staged_main = _stage(main_path, _serialize(main))
        staged.append(staged_main)
        os.replace(staged_audit, audit_path)
        try:
            os.replace(staged_main, main_path)
        except OSError:
            if previous_audit is None:
                audit_path.unlink(missing_ok=True)
            else:
                rollback = _stage(audit_path, previous_audit)
                staged.append(rollback)
                os.replace(rollback, audit_path)
            raise
    finally:
        for staging in staged:
            staging.unlink(missing_ok=True)


def _previous_pair(main_path: Path, audit_path: Path) -> tuple[dict, dict]:
    try:
        main = require_object(_read(main_path), "previous main")
        audit = require_object(_read(audit_path), "previous audit")
        if (
            type(main.get("schemaVersion")) is not int
            or main.get("schemaVersion") not in {2, 3}
            or audit.get("schemaVersion") != main.get("schemaVersion")
            or not main.get("generationId")
            or main.get("generationId") != audit.get("generationId")
        ):
            return {}, {}
        return main, audit
    except _FAILURES:
        return {}, {}


def generate_rankings(
    input_path: Path,
    output: Path,
    sources: Path,
    mappings_path: Path,
    providers_path: Path,
    *,
    offline: bool = False,
    policy_path: Path | None = None,
) -> int:
    """Refresh sources if requested, then publish coherent v3 catalogue/audit files.

    A generation failure retains the last coherent v2 or v3 payload and its schema.
    Return 1 only when the outcome cannot be published. Provider inputs are never
    fetched, enriched or rewritten by this entry point.
    """
    main_path = output / "benchmarks" / "coding.json"
    audit_path = output / "benchmarks" / "coding-audit.json"
    cache_path = output / "benchmarks" / "sources"
    previous_main, previous_audit = _previous_pair(main_path, audit_path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    generation_id = uuid.uuid4().hex
    try:
        refresh_states = []
        if not offline:
            source_module = importlib.import_module("lib.benchmark_sources")
            refreshed = source_module.refresh_sources(cache_path, sources)
            refresh_states = [item for item in refreshed if isinstance(item, dict)]
        built = build_rankings(
            input_path,
            sources,
            mappings_path,
            providers_path,
            cache_path,
            policy_path=policy_path,
        )
        built["audit"]["sourceRefresh"] = refresh_states
        for state in refresh_states:
            if state.get("persisted") is False:
                built["audit"]["issues"].append(
                    {
                        "scope": "source",
                        "sourceId": state.get("sourceId"),
                        "code": "source_refresh_not_persisted",
                        "message": "Refresh outcome could not be written to the runtime source cache.",
                    }
                )
            for published in built["main"]["sourceStates"]:
                if published["sourceId"] == state.get("sourceId"):
                    published["refreshStatus"] = state.get("status")
                    published["refreshPersisted"] = state.get("persisted")
    except _FAILURES as error:
        message = _message(error)
        print(f"coding catalogue: {message}", file=sys.stderr)
        failure = {
            "schemaVersion": previous_main.get("schemaVersion", 3),
            "status": "failed",
            "lastFailedAt": now,
            "lastFailedMessage": message,
            "generationId": generation_id,
        }
        main = {
            "updatedAt": None,
            "summary": None,
            "sourceStates": [],
            "data": [],
            **previous_main,
            **failure,
        }
        audit = {
            "updatedAt": None,
            "sources": [],
            "issues": [],
            **previous_audit,
            **failure,
        }
        if previous_main.get("schemaVersion") == 2:
            audit["issues"] = [
                *audit.get("issues", []),
                {
                    "scope": "catalogue",
                    "code": "retained_v2_without_tiers",
                    "message": "Failed v3 migration retained the coherent v2 payload; no tiers were added.",
                },
            ]
    else:
        envelope = {
            "schemaVersion": 3,
            "status": "success",
            "updatedAt": now,
            "lastFailedAt": previous_main.get("lastFailedAt"),
            "lastFailedMessage": previous_main.get("lastFailedMessage"),
            "generationId": generation_id,
        }
        main, audit = {**envelope, **built["main"]}, {**envelope, **built["audit"]}
    main["auditRef"] = {"path": "coding-audit.json", "generationId": generation_id}
    try:
        _publish_pair(main_path, main, audit_path, audit)
    except _FAILURES as error:
        print(
            f"coding catalogue: cannot publish outcome: {_message(error)}",
            file=sys.stderr,
        )
        return 1
    return 0
