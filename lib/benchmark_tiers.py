"""Assign provisional tiers from frozen public panels, not raw-score averages."""

from __future__ import annotations

import bisect
import datetime
import hashlib
import json
import math
from pathlib import Path

from lib.benchmark_identity import (
    SOURCE_IDS,
    configuration_matches,
    require_object,
    require_text,
)

WORKLOADS = ("generationDebugging", "repositoryEditing")
THRESHOLDS = (
    ("S+", 90),
    ("S", 80),
    ("A+", 70),
    ("A", 60),
    ("A-", 50),
    ("B+", 40),
    ("B", 25),
    ("C", 0),
)
SELECTION = "priority_then_latest_evaluation_then_literal_ids"
NORMALIZER = "100 * (count(reference < score) + 0.5 * count(reference == score)) / N"


def _array(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise TypeError(f"{label}: expected an array")
    return value


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{label}: expected a finite number in {minimum}..{maximum}")
    return float(value)


def load_policy(path: Path) -> tuple[dict, str]:
    """Validate the entire frozen policy before admitting any scoring evidence."""
    contents = path.read_bytes()
    policy = require_object(json.loads(contents), "tier policy")
    json.dumps(policy, allow_nan=False)
    if type(policy.get("schemaVersion")) is not int or policy["schemaVersion"] != 1:
        raise ValueError("tier policy: schemaVersion must be 1")
    require_text(policy.get("policyVersion"), "policyVersion")
    require_text(policy.get("interpretation"), "interpretation")
    if policy.get("selection") != SELECTION:
        raise ValueError("tier policy: unsupported selection")
    weights = require_object(policy.get("workloadWeights"), "workloadWeights")
    if set(weights) != set(WORKLOADS):
        raise ValueError("tier policy: exactly two workload weights required")
    for key in WORKLOADS:
        _number(weights[key], f"weight.{key}", 0, 100)
        if weights[key] <= 0:
            raise ValueError("tier policy: workload weights must be positive")
    if weights[WORKLOADS[0]] != weights[WORKLOADS[1]]:
        raise ValueError("tier policy: equal 50/50 workload weighting required")
    thresholds = _array(policy.get("tierThresholds"), "tierThresholds")
    if len(thresholds) != len(THRESHOLDS):
        raise ValueError("tier policy: complete ordered thresholds required")
    for raw, (tier, minimum) in zip(thresholds, THRESHOLDS, strict=True):
        entry = require_object(raw, "tier threshold")
        if (
            entry.get("tier") != tier
            or _number(entry.get("minIndex"), "minIndex", 0, 100) != minimum
        ):
            raise ValueError("tier policy: unsupported or unordered thresholds")
    minimum_size = policy.get("minimumReferenceSize")
    if type(minimum_size) is not int or minimum_size <= 0:
        raise ValueError("tier policy: minimumReferenceSize must be a positive integer")
    ids: set[str] = set()
    for raw in _array(policy.get("profiles"), "profiles"):
        profile = require_object(raw, "profile")
        profile_id = require_text(profile.get("id"), "profile.id")
        if profile_id in ids:
            raise ValueError("tier policy: duplicate profile id")
        ids.add(profile_id)
        if profile.get("sourceId") not in SOURCE_IDS:
            raise ValueError("profile: unsupported sourceId")
        require_text(profile.get("sourceFamily"), "profile.sourceFamily")
        if profile.get("workload") not in WORKLOADS:
            raise ValueError("profile: unsupported workload")
        if type(profile.get("priority")) is not int:
            raise ValueError("profile: priority must be an integer")
        cohorts = _array(profile.get("cohortIds"), "profile.cohortIds")
        if not cohorts or len(cohorts) != len(set(map(str, cohorts))):
            raise ValueError("profile: empty or duplicate cohortIds")
        for cohort in cohorts:
            require_text(cohort, "profile.cohortId")
        require_text(profile.get("metric"), "profile.metric")
        if profile.get("unit") not in {"percent", "score_0_100"}:
            raise ValueError("profile: unsupported unit")
        require_object(profile.get("recordConstraints", {}), "recordConstraints")
        scores = _array(profile.get("referenceScores"), "referenceScores")
        for score in scores:
            _number(score, "reference score", 0, 100)
        if len(scores) < minimum_size or scores != sorted(scores):
            raise ValueError("profile: undersized or unsorted frozen reference panel")
        records = _array(profile.get("referenceRecords"), "referenceRecords")
        record_ids: set[tuple[str, str]] = set()
        for raw_record in records:
            record = require_object(raw_record, "reference record")
            cohort = require_text(record.get("cohort"), "reference cohort")
            evaluation_id = require_text(
                record.get("evaluationId"), "reference evaluationId"
            )
            require_text(record.get("modelId"), "reference modelId")
            _number(record.get("score"), "reference record score", 0, 100)
            if cohort not in cohorts or (cohort, evaluation_id) in record_ids:
                raise ValueError(
                    "profile: unknown cohort or duplicate reference record"
                )
            record_ids.add((cohort, evaluation_id))
        if sorted(record["score"] for record in records) != scores:
            raise ValueError("profile: referenceScores do not match referenceRecords")
        provenance = require_object(profile.get("provenance"), "profile.provenance")
        require_text(provenance.get("revision"), "provenance.revision")
        require_text(provenance.get("sourceUrl"), "provenance.sourceUrl")
        require_text(
            provenance.get(
                "contentHash", provenance.get("hash", provenance.get("sha256"))
            ),
            "provenance.hash",
        )
        for assumption in _array(profile.get("assumptions"), "profile.assumptions"):
            require_text(assumption, "profile assumption")
    return policy, hashlib.sha256(contents).hexdigest()


def normalize_score(score: float, reference: list[float]) -> float:
    """Compute a frozen-panel midrank index, never a percent of tasks solved."""
    _number(score, "score", 0, 100)
    if not reference:
        raise ValueError("normalizer: empty reference panel")
    lower = bisect.bisect_left(reference, score)
    upper = bisect.bisect_right(reference, score)
    return 100 * (lower + 0.5 * (upper - lower)) / len(reference)


def _evaluation_time(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _selection_key(candidate: dict) -> tuple:
    time = _evaluation_time(candidate["evaluatedAt"])
    return (
        candidate["priority"],
        time is None,
        -time if time is not None else 0,
        candidate["evaluatedModelId"],
        candidate["evaluationId"],
        candidate["cohort"],
        candidate["evidenceId"],
        candidate["profileId"],
    )


def _aggregate(selected: dict[str, dict], policy: dict) -> dict:
    if not selected:
        return {
            "tier": "Unrated",
            "index": None,
            "basis": "no_usable_scoring_evidence",
            "weights": {},
        }
    total = sum(policy["workloadWeights"][key] for key in selected)
    weights = {key: policy["workloadWeights"][key] / total for key in selected}
    index = sum(selected[key]["index"] * weights[key] for key in selected)
    tier = next(tier for tier, minimum in THRESHOLDS if index >= minimum)
    basis = (
        "both_workloads"
        if len(selected) == 2
        else ("generation_only" if WORKLOADS[0] in selected else "editing_only")
    )
    return {"tier": tier, "index": index, "basis": basis, "weights": weights}


def score_models(
    rows: list[dict],
    evidence_details: list[dict],
    sources: list[dict],
    policy: dict,
    policy_hash: str,
) -> dict:
    """Attach one provisional overall tier and audit every admission and fallback."""
    details = {entry["evidenceId"]: entry for entry in evidence_details}
    records: dict[tuple[str, str, str], tuple[dict, dict, dict]] = {}
    for source in sources:
        for cohort in (source.get("snapshot") or {}).get("cohorts", []):
            for record in cohort["records"]:
                records[(source["sourceId"], cohort["id"], record["evaluationId"])] = (
                    source,
                    cohort,
                    record,
                )
    audits = []
    indices: dict[str, float | None] = {}
    for row in rows:
        accepted: dict[str, list[dict]] = {key: [] for key in WORKLOADS}
        rejected = []
        for workload in WORKLOADS:
            for evidence in row[workload]:
                detail = details.get(evidence["evidenceId"])
                base = {"evidenceId": evidence["evidenceId"], "workload": workload}
                original = (
                    records.get(
                        (detail["sourceId"], detail["cohort"], detail["evaluationId"])
                    )
                    if detail
                    else None
                )
                if original is None:
                    rejected.append({**base, "reason": "source_record_unavailable"})
                    continue
                source, cohort, record = original
                base.update(
                    {
                        "sourceId": source["sourceId"],
                        "cohort": cohort["id"],
                        "evaluationId": record["evaluationId"],
                        "evaluatedModelId": record["modelId"],
                        "rawScore": record["score"],
                        "evaluatedAt": record.get("evaluatedAt"),
                        "sourceStale": source["status"] != "success",
                        "configurationUncertainty": not bool(record["configuration"]),
                        "configuration": record["configuration"],
                        "provisional": True,
                    }
                )
                profiles = [
                    p
                    for p in policy["profiles"]
                    if p["sourceId"] == source["sourceId"] and p["workload"] == workload
                ]
                if not profiles:
                    rejected.append({**base, "reason": "no_admitted_profile"})
                for profile in profiles:
                    reference = profile["referenceScores"]
                    candidate = {
                        **base,
                        "profileId": profile["id"],
                        "priority": profile["priority"],
                        "sourceFamily": profile["sourceFamily"],
                        "referencePanelN": len(reference),
                        "referenceProvenance": profile["provenance"],
                        "outsideReferenceRange": record["score"] < reference[0]
                        or record["score"] > reference[-1],
                        "assumptions": profile["assumptions"],
                        "recordConstraints": profile.get("recordConstraints", {}),
                    }
                    reason = None
                    if cohort["id"] not in profile["cohortIds"]:
                        reason = "cohort_not_admitted"
                    elif (
                        cohort["metric"] != profile["metric"]
                        or cohort["unit"] != profile["unit"]
                    ):
                        reason = "metric_or_unit_not_admitted"
                    elif not configuration_matches(
                        profile.get("recordConstraints", {}), record
                    ):
                        reason = "record_constraints_mismatch"
                    if reason:
                        rejected.append({**candidate, "reason": reason})
                        continue
                    accepted[workload].append(
                        {
                            **candidate,
                            "index": normalize_score(record["score"], reference),
                        }
                    )
        for candidates in accepted.values():
            candidates.sort(key=_selection_key)
        selected = {
            key: candidates[0] for key, candidates in accepted.items() if candidates
        }
        for workload, candidates in accepted.items():
            rejected.extend(
                {**candidate, "reason": "lower_selection_preference"}
                for candidate in candidates[1:]
            )
        result = _aggregate(selected, policy)
        indices[row["modelId"]] = result["index"]
        confidence = "none" if not selected else "limited"
        if (
            len(selected) == 2
            and len({item["sourceFamily"] for item in selected.values()}) >= 2
            and all(
                not item["sourceStale"]
                and not item["configurationUncertainty"]
                and not item["outsideReferenceRange"]
                for item in selected.values()
            )
        ):
            confidence = "moderate"
        row.update(
            {
                "tier": result["tier"],
                "index": round(result["index"], 1)
                if result["index"] is not None
                else None,
                "basis": result["basis"],
                "confidence": confidence,
                "provisional": bool(selected),
            }
        )
        sensitivity = []
        for family in sorted({item["sourceFamily"] for item in selected.values()}):
            alternative = {}
            for workload, candidates in accepted.items():
                fallback = next(
                    (item for item in candidates if item["sourceFamily"] != family),
                    None,
                )
                if fallback:
                    alternative[workload] = fallback
            sensitivity.append(
                {
                    "omittedSourceFamily": family,
                    **_aggregate(alternative, policy),
                    "selectedEvidenceIds": {
                        key: item["evidenceId"] for key, item in alternative.items()
                    },
                    "interpretation": "Selection sensitivity only; not statistical confidence.",
                }
            )
        audits.append(
            {
                "modelId": row["modelId"],
                **result,
                "confidence": confidence,
                "provisional": bool(selected),
                "selected": selected,
                "rejected": sorted(
                    rejected,
                    key=lambda item: (
                        item["workload"],
                        item["evidenceId"],
                        item.get("profileId", ""),
                        item["reason"],
                    ),
                ),
                "omittedWorkloads": [key for key in WORKLOADS if key not in selected],
                "omittedWorkloadCaveat": "Missing workloads are omitted and weights renormalized, not scored zero. Single-workload tiers do not establish broad capability.",
                "leaveOneSourceFamilyOut": sensitivity,
            }
        )
    rows.sort(
        key=lambda row: (
            indices[row["modelId"]] is None,
            -(indices[row["modelId"]] or 0),
            row["modelId"],
        )
    )
    audits.sort(key=lambda item: item["modelId"])
    return {
        "policyVersion": policy["policyVersion"],
        "policyHash": policy_hash,
        "provisional": True,
        "indexInterpretation": "Frozen-panel relative midrank, not percentage solved or validated endpoint capability.",
        "policy": policy,
        "tierThresholds": policy["tierThresholds"],
        "normalizer": NORMALIZER,
        "selection": SELECTION,
        "interpretation": policy["interpretation"],
        "models": audits,
    }
