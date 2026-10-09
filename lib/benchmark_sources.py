"""Refresh bounded public benchmark exports into independent schema-v2 caches."""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import math
import os
import re
import shlex
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lib.http_client import MAX_RESPONSE_BYTES, get_url, one_line

SOURCE_IDS = (
    "livebench",
    "evalplus",
    "aider_polyglot",
    "bigcodebench",
    "aider_python",
)
_BENCHMARKS = {
    "livebench": "LiveBench",
    "evalplus": "EvalPlus",
    "aider_polyglot": "Aider",
    "aider_python": "Aider",
    "bigcodebench": "BigCodeBench",
}
_HISTORY = ("2026_01_08", "2025_05_30", "2024_11_25", "2024_06_24")
_SHA = re.compile(r"[0-9a-f]{40}")
_HASH = re.compile(r"[0-9a-f]{64}")
_TABLE = re.compile(r"public/table_(\d{4}_\d{2}_\d{2})\.csv")
_MAX_HF_ROWS = 1000
_MAX_RECORDS = 10000


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label}: expected an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: expected a nonempty string")
    return value


def _date(value: object, label: str) -> None:
    if value is not None:
        datetime.datetime.fromisoformat(_text(value, label).replace("Z", "+00:00"))


def _score(value: object) -> int | float:
    if type(value) not in (int, float) or not 0 <= value <= 100:
        raise ValueError("score: expected a finite number from 0 to 100")
    if not math.isfinite(value):
        raise ValueError("score: expected a finite number from 0 to 100")
    return value


def validate_source(payload: object) -> dict:
    """Validate a normalized source wrapper without guessing missing fields.

    Failed sources may have a null snapshot before their first successful capture.
    Otherwise every record has an exact identity, configuration and valid score.
    Unknown provenance, cohort and record fields are preserved unchanged.
    """
    source = _object(payload, "source")
    if type(source.get("schemaVersion")) is not int or source["schemaVersion"] != 2:
        raise ValueError("source: schemaVersion must be 2")
    source_id = source.get("sourceId")
    if source_id not in SOURCE_IDS or source.get("benchmark") != _BENCHMARKS[source_id]:
        raise ValueError("source: unsupported sourceId or benchmark")
    if source.get("status") not in ("success", "failed"):
        raise ValueError("source: invalid status")
    for key in ("updatedAt", "lastFailedAt", "lastFailedMessage", "snapshot"):
        if key not in source:
            raise ValueError(f"source: missing {key}")
    _date(source["updatedAt"], "updatedAt")
    _date(source["lastFailedAt"], "lastFailedAt")
    if source["lastFailedMessage"] is not None:
        _text(source["lastFailedMessage"], "lastFailedMessage")
    if source["status"] == "failed" and (
        source["lastFailedAt"] is None or source["lastFailedMessage"] is None
    ):
        raise ValueError("failed source: missing failure details")
    snapshot = source["snapshot"]
    if snapshot is None:
        if source["status"] != "failed" or source["updatedAt"] is not None:
            raise ValueError("source without snapshot must be failed and never updated")
        return source
    snapshot = _object(snapshot, "snapshot")
    if source["updatedAt"] is None:
        raise ValueError("snapshot: missing successful update timestamp")
    for key in ("revision", "sourceUrl", "capturedAt", "contentHash"):
        _text(snapshot.get(key), f"snapshot.{key}")
    if not snapshot["sourceUrl"].startswith("https://"):
        raise ValueError("snapshot: sourceUrl must be HTTPS")
    _date(snapshot["capturedAt"], "snapshot.capturedAt")
    if not _HASH.fullmatch(snapshot["contentHash"]):
        raise ValueError("snapshot: contentHash must be a SHA-256 hex digest")
    cohorts = snapshot.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts or len(cohorts) > 500:
        raise ValueError("snapshot: expected 1 to 500 cohorts")
    seen_cohorts: set[str] = set()
    for raw in cohorts:
        cohort = _object(raw, "cohort")
        cohort_id = _text(cohort.get("id"), "cohort.id")
        if not cohort_id.startswith(f"{source_id}:") or cohort_id in seen_cohorts:
            raise ValueError("cohort: duplicate or incorrectly namespaced id")
        seen_cohorts.add(cohort_id)
        if cohort.get("workload") not in ("generation_debugging", "repository_editing"):
            raise ValueError("cohort: invalid workload")
        for key in ("label", "metric"):
            _text(cohort.get(key), f"cohort.{key}")
        if "release" not in cohort:
            raise ValueError("cohort: missing release")
        if cohort["release"] is not None:
            _text(cohort["release"], "cohort.release")
        if cohort.get("unit") not in ("score_0_100", "percent"):
            raise ValueError("cohort: invalid unit")
        if cohort.get("direction") != "higher":
            raise ValueError("cohort: direction must be higher")
        records = cohort.get("records")
        if not isinstance(records, list) or not records or len(records) > _MAX_RECORDS:
            raise ValueError("cohort: expected a bounded nonempty records array")
        seen_evaluations: set[str] = set()
        for raw_record in records:
            record = _object(raw_record, "record")
            evaluation_id = _text(record.get("evaluationId"), "record.evaluationId")
            if evaluation_id in seen_evaluations:
                raise ValueError("record: duplicate evaluationId within cohort")
            seen_evaluations.add(evaluation_id)
            _text(record.get("modelId"), "record.modelId")
            for key in ("modelUrl", "evaluatedAt", "taskCount"):
                if key not in record:
                    raise ValueError(f"record: missing {key}")
            if record["modelUrl"] is not None:
                _text(record["modelUrl"], "record.modelUrl")
            _score(record.get("score"))
            _object(record.get("configuration"), "record.configuration")
            _date(record["evaluatedAt"], "record.evaluatedAt")
            count = record["taskCount"]
            if count is not None and (type(count) is not int or count <= 0):
                raise ValueError("record: taskCount must be positive integer or null")
    # Reject non-JSON values and nonfinite numbers, including unknown metadata.
    json.dumps(source, allow_nan=False)
    return source


def read_source(path: Path) -> dict:
    """Read and validate one schema-v2 seed or cache."""
    with path.open("rb") as stream:
        body = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("source cache exceeds the bounded input size")
    return validate_source(json.loads(body, object_pairs_hook=_unique_object))


def _json_bytes(body: bytes, label: str) -> dict:
    return _object(json.loads(body, object_pairs_hook=_unique_object), label)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON: duplicate key {key!r}")
        result[key] = value
    return result


def _github_revision(repository: str) -> str:
    response = _json_bytes(
        get_url(f"https://api.github.com/repos/{repository}/commits/main"), repository
    )
    revision = _text(response.get("sha"), "GitHub revision")
    if not _SHA.fullmatch(revision):
        raise ValueError("GitHub: invalid commit revision")
    return revision


def _raw_url(repository: str, revision: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repository}/{revision}/{path}"


def _capture(url: str, artifacts: list[dict], bodies: list[bytes]) -> bytes:
    body = get_url(url)
    artifacts.append(
        {"sourceUrl": url, "contentHash": hashlib.sha256(body).hexdigest()}
    )
    bodies.append(body)
    return body


def _snapshot(revision: str, artifacts: list[dict], bodies: list[bytes]) -> dict:
    return {
        "revision": revision,
        "sourceUrl": artifacts[0]["sourceUrl"],
        "capturedAt": _now(),
        "contentHash": hashlib.sha256(b"".join(bodies)).hexdigest(),
        "contentHashDefinition": "SHA-256 of raw artifact bodies concatenated in artifacts order",
        "artifacts": artifacts,
        "cohorts": [],
    }


def _cohort(
    cohort_id: str, label: str, metric: str, workload: str, release: str | None = None
) -> dict:
    return {
        "id": cohort_id,
        "workload": workload,
        "label": label,
        "release": release,
        "metric": metric,
        "unit": "percent"
        if metric == "pass_rate_2" or "pass@1" in metric
        else "score_0_100",
        "direction": "higher",
        "records": [],
    }


def _record(
    evaluation_id: str,
    model_id: str,
    score: float,
    configuration: dict,
    model_url: str | None = None,
    evaluated_at: str | None = None,
    task_count: int | None = None,
) -> dict:
    return {
        "evaluationId": evaluation_id,
        "modelId": model_id,
        "modelUrl": model_url,
        "score": _score(score),
        "configuration": configuration,
        "evaluatedAt": evaluated_at,
        "taskCount": task_count,
    }


def _links(text: str) -> dict[str, str]:
    # Read only literal, one-line entries. No JavaScript evaluation or alias inference.
    pattern = re.compile(
        r'^\s*"([^"\\]+)"\s*:\s*\{\s*url:\s*"(https://[^"\\]+)"', re.MULTILINE
    )
    return dict(pattern.findall(text))


def _livebench() -> dict:
    repository = "LiveBench/livebench.github.io"
    revision = _github_revision(repository)
    tree = _json_bytes(
        get_url(
            f"https://api.github.com/repos/{repository}/git/trees/{revision}?recursive=1"
        ),
        "LiveBench tree",
    )
    if tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
        raise ValueError("LiveBench: incomplete repository tree")
    paths = {_text(item.get("path"), "tree path") for item in tree["tree"]}
    dates = sorted(match[1] for path in paths if (match := _TABLE.fullmatch(path)))
    if not dates:
        raise ValueError("LiveBench: no table releases found")
    if f"public/categories_{dates[-1]}.json" not in paths:
        raise ValueError("LiveBench: latest table has no category metadata")
    dates = list(
        dict.fromkeys(
            [
                dates[-1],
                *(
                    date
                    for date in _HISTORY
                    if date in dates and f"public/categories_{date}.json" in paths
                ),
            ]
        )
    )
    artifacts: list[dict] = []
    bodies: list[bytes] = []
    links = _links(
        _capture(
            _raw_url(repository, revision, "src/Table/modelLinks.js"), artifacts, bodies
        ).decode("utf-8")
    )
    cohorts = []
    for date in dates:
        categories = _json_bytes(
            _capture(
                _raw_url(repository, revision, f"public/categories_{date}.json"),
                artifacts,
                bodies,
            ),
            "LiveBench categories",
        )
        raw = _capture(
            _raw_url(repository, revision, f"public/table_{date}.csv"),
            artifacts,
            bodies,
        )
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        rows = list(reader)
        if (
            not rows
            or len(rows) > _MAX_RECORDS
            or "model" not in (reader.fieldnames or [])
            or len(set(reader.fieldnames or [])) != len(reader.fieldnames or [])
            or any(None in row for row in rows)
        ):
            raise ValueError("LiveBench: invalid table")
        release = date.replace("_", "-")
        for category, suffix, workload in (
            ("Coding", "coding", "generation_debugging"),
            ("Agentic Coding", "agentic_coding", "repository_editing"),
        ):
            if category not in categories:
                if category == "Coding":
                    raise ValueError("LiveBench: missing Coding category")
                continue
            columns = categories[category]
            expected = (
                (
                    {"code_generation", "code_completion"}
                    if date >= "2025_05_30"
                    else {"LCB_generation", "coding_completion"}
                )
                if category == "Coding"
                else {"javascript", "typescript", "python"}
            )
            if (
                not isinstance(columns, list)
                or len(columns) != len(expected)
                or set(columns) != expected
            ):
                raise ValueError(f"LiveBench: unsupported {category} task columns")
            if not expected.issubset(reader.fieldnames or []):
                raise ValueError("LiveBench: category/table schema mismatch")
            cohort = _cohort(
                f"livebench:{release}:{suffix}",
                f"LiveBench {category} {release}",
                "category_mean",
                workload,
                release,
            )
            cohort["category"] = category
            cohort["taskColumns"] = columns
            cohort["aggregation"] = "arithmetic mean requiring all category columns"
            if category == "Agentic Coding":
                cohort["interpretation"] = (
                    "Agentic task surrogate; not a verified full-repository editing evaluation"
                )
            for row in rows:
                model = _text(row.get("model"), "LiveBench model")
                values = [row[column] for column in columns]
                if any(value in ("", "N/A", "null", "-", None) for value in values):
                    continue
                scores = [_score(float(value)) for value in values]
                record = _record(
                    model, model, sum(scores) / len(scores), {}, links.get(model)
                )
                record["taskScores"] = dict(zip(columns, scores, strict=True))
                record["sourceColumns"] = row
                cohort["records"].append(record)
            if cohort["records"]:
                cohorts.append(cohort)
    snapshot = _snapshot(revision, artifacts, bodies)
    snapshot["cohorts"] = cohorts
    snapshot["latestRelease"] = dates[0].replace("_", "-")
    snapshot["categories"] = (
        "Pinned per-release category artifacts; release denotes task version, not evaluation date"
    )
    snapshot["unavailableHistoricalReleases"] = [
        date.replace("_", "-") for date in _HISTORY if date not in dates
    ]
    return snapshot


def _partition(configuration: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            configuration, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()[:16]


def _evalplus() -> dict:
    repository = "evalplus/evalplus.github.io"
    revision = _github_revision(repository)
    artifacts: list[dict] = []
    bodies: list[bytes] = []
    rows = _json_bytes(
        _capture(_raw_url(repository, revision, "results.json"), artifacts, bodies),
        "EvalPlus results",
    )
    if not rows or len(rows) > _MAX_RECORDS:
        raise ValueError("EvalPlus: invalid result count")
    cohorts: dict[str, dict] = {}
    for model, raw in rows.items():
        _text(model, "EvalPlus model")
        row = _object(raw, "EvalPlus row")
        metrics = _object(row.get("pass@1"), "EvalPlus pass@1")
        if set(metrics) != {"humaneval", "humaneval+", "mbpp", "mbpp+"}:
            raise ValueError("EvalPlus: unsupported metric columns")
        prompted = row.get("prompted")
        if prompted is not None and type(prompted) is not bool:
            raise ValueError("EvalPlus: prompted must be boolean or unknown")
        configuration = {"prompted": prompted}
        group = "unknown" if prompted is None else str(prompted).lower()
        for metric, score in metrics.items():
            if score is None:
                continue
            cohort_id = f"evalplus:{metric}:prompted-{group}"
            cohort = cohorts.setdefault(
                cohort_id,
                _cohort(
                    cohort_id,
                    f"EvalPlus {metric}, prompted={group}",
                    f"{metric} pass@1",
                    "generation_debugging",
                ),
            )
            record = _record(model, model, score, configuration, row.get("link"))
            cohort["category"] = "Function correctness"
            record["sourceFields"] = {
                key: value
                for key, value in row.items()
                if key not in ("pass@1", "link")
            }
            cohort["records"].append(record)
    snapshot = _snapshot(revision, artifacts, bodies)
    snapshot["cohorts"] = list(cohorts.values())
    snapshot["interpretation"] = (
        "Function correctness; separate metrics and prompted configurations, not repository editing"
    )
    return snapshot


def _yaml_scalar(value: str) -> object:
    value = value.strip()
    if not value:
        return None
    if value.startswith("#"):
        return None
    if value.startswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError("Aider YAML: double quotes must enclose a string")
        return parsed
    if value.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", value):
            raise ValueError("Aider YAML: unsupported single-quoted scalar")
        return value[1:-1].replace("''", "'")
    value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
    if re.search(r"[\[\]{}]|(?:^|\s)[&*!|>]", value) or re.search(r":\s", value):
        raise ValueError(
            "Aider YAML: unsupported anchor, tag, collection or block syntax"
        )
    if value in ("null", "~"):
        return None
    if value in ("true", "false"):
        return value == "true"
    if re.fullmatch(r"-?(?:0|[1-9]\d*)", value):
        return int(value)
    if re.fullmatch(r"-?(?:0|[1-9]\d*)\.\d+(?:[eE][+-]?\d+)?", value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Aider YAML: nonfinite scalar")
        return result
    if value.lower() in (".nan", ".inf", "-.inf", "+.inf") or value.startswith(
        ("%", "---", "...")
    ):
        raise ValueError("Aider YAML: unsupported scalar")
    return value


def parse_aider_yaml(text: str) -> list[dict]:
    """Read only Aider's flat list of scalar mappings, rejecting other YAML.

    This is intentionally not a general YAML parser. It does not execute model
    commands, resolve tags or aliases, or accept nested/flow/block structures.
    """
    rows: list[dict] = []
    current = None
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(
            r"(- |  )([A-Za-z_][A-Za-z0-9_]*):(?: (.*))?", line.rstrip()
        )
        if not match or "\t" in line:
            raise ValueError(f"Aider YAML line {number}: unsupported syntax")
        if match[1] == "- ":
            current = {}
            rows.append(current)
        if current is None or match[2] in current:
            raise ValueError(f"Aider YAML line {number}: missing row or duplicate key")
        current[match[2]] = _yaml_scalar(match[3] or "")
        if match[2] == "commit_hash" and type(current[match[2]]) is int:
            # A digits-only commit abbreviation is still an identity, not a number.
            current[match[2]] = str(current[match[2]])
    if not rows or len(rows) > _MAX_RECORDS:
        raise ValueError("Aider YAML: invalid row count")
    return rows


def _command_options(command: object) -> list[str] | None:
    if command is None:
        return None
    tokens = shlex.split(_text(command, "Aider command"))
    options = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--model":
            if index + 1 >= len(tokens):
                raise ValueError("Aider command: missing --model argument")
            index += 2
        elif token.startswith("--model="):
            index += 1
        else:
            options.append(token)
            index += 1
    return options


def _aider_cohorts(rows: list[dict], suite: str, source_id: str) -> list[dict]:
    cohorts: dict[str, dict] = {}
    for row in rows:
        model = _text(row.get("model"), "Aider model")
        evaluation_id = _text(row.get("dirname"), "Aider run dirname")
        score = _score(row.get("pass_rate_2"))
        partition = {
            key: row.get(key)
            for key in (
                "test_cases",
                "total_tests",
                "versions",
                "commit_hash",
                "edit_format",
                "editor_edit_format",
                "editor_model",
                "reasoning_effort",
                "thinking_tokens",
            )
        }
        # Parse arguments as inert text, never execute a command. Preserve editor,
        # reasoning and other flags while excluding only the primary model identity.
        partition["commandOptions"] = _command_options(row.get("command"))
        observations = {
            "model",
            "dirname",
            "date",
            "command",
            "released",
            "_released",
            "pass_rate_1",
            "pass_rate_2",
            "pass_num_1",
            "pass_num_2",
            "percent_cases_well_formed",
            "error_outputs",
            "num_malformed_responses",
            "num_with_malformed_responses",
            "user_asks",
            "lazy_comments",
            "syntax_errors",
            "indentation_errors",
            "exhausted_context_windows",
            "test_timeouts",
            "seconds_per_case",
            "total_cost",
            "prompt_tokens",
            "completion_tokens",
        }
        additional = {
            key: value
            for key, value in row.items()
            if key not in partition and key not in observations
        }
        if additional:
            partition["additionalConfiguration"] = additional
        for key in ("versions", "commit_hash", "edit_format"):
            _text(partition[key], f"Aider {key}")
        count = row.get("total_tests")
        if count is not None and (type(count) is not int or count <= 0):
            raise ValueError("Aider: invalid total_tests")
        configuration = {**partition, "command": row.get("command")}
        cohort_id = f"{source_id}:{suite}:{_partition(partition)}"
        cohort = cohorts.setdefault(
            cohort_id,
            _cohort(
                cohort_id,
                f"Aider {suite}, {row['versions']}, {row['edit_format']}, harness {_partition(partition)}",
                "pass_rate_2",
                "repository_editing",
            ),
        )
        cohort["harnessConfiguration"] = partition
        cohort["interpretation"] = (
            "Published Aider editing harness; distinct suite/harness/editor/reasoning runs are not interchangeable"
        )
        cohort["suite"] = suite
        record = _record(
            evaluation_id,
            model,
            score,
            configuration,
            evaluated_at=row.get("date"),
            task_count=count,
        )
        record["sourceFields"] = row
        cohort["records"].append(record)
    return list(cohorts.values())


def _aider(suite: str, filename: str, source_id: str) -> dict:
    repository = "Aider-AI/aider"
    revision = _github_revision(repository)
    artifacts: list[dict] = []
    bodies: list[bytes] = []
    url = _raw_url(repository, revision, f"aider/website/_data/{filename}.yml")
    rows = parse_aider_yaml(_capture(url, artifacts, bodies).decode("utf-8"))
    snapshot = _snapshot(revision, artifacts, bodies)
    snapshot["cohorts"] = _aider_cohorts(rows, suite, source_id)
    return snapshot


def _aider_polyglot() -> dict:
    return _aider("polyglot", "polyglot_leaderboard", "aider_polyglot")


def _aider_python() -> dict:
    return _aider("python", "edit_leaderboard", "aider_python")


def _hf_revision() -> str:
    metadata = _json_bytes(
        get_url("https://huggingface.co/api/datasets/bigcode/bigcodebench-results"),
        "BigCodeBench dataset",
    )
    revision = _text(metadata.get("sha"), "dataset revision")
    if not _SHA.fullmatch(revision):
        raise ValueError("BigCodeBench: invalid dataset revision")
    return revision


def _bigcodebench() -> dict:
    revision = _hf_revision()
    endpoint = "https://datasets-server.huggingface.co/rows?dataset=bigcode%2Fbigcodebench-results&config=default&split=train"
    artifacts: list[dict] = []
    bodies: list[bytes] = []
    archive = []
    rows = []
    total = None
    offset = 0
    while total is None or offset < total:
        url = f"{endpoint}&offset={offset}&length=100"
        body = _capture(url, artifacts, bodies)
        page = _json_bytes(body, "BigCodeBench page")
        advertised = page.get("num_rows_total")
        if type(advertised) is not int or not 0 < advertised <= _MAX_HF_ROWS:
            raise ValueError("BigCodeBench: invalid or excessive total row count")
        if total is not None and advertised != total:
            raise ValueError("BigCodeBench: total changed during pagination")
        total = advertised
        if page.get("partial") is not False:
            raise ValueError("BigCodeBench: partial rows response")
        page_rows = page.get("rows")
        if not isinstance(page_rows, list) or not 0 < len(page_rows) <= 100:
            raise ValueError("BigCodeBench: stalled or excessive pagination")
        for index, raw in enumerate(page_rows):
            item = _object(raw, "BigCodeBench row wrapper")
            if (
                type(item.get("row_idx")) is not int
                or item["row_idx"] != offset + index
                or item.get("truncated_cells") != []
            ):
                raise ValueError("BigCodeBench: noncontiguous or truncated rows")
            rows.append(_object(item.get("row"), "BigCodeBench row"))
        archive.append({**artifacts[-1], "rawJson": body.decode("utf-8")})
        offset += len(page_rows)
        if offset > total:
            raise ValueError("BigCodeBench: rows exceed advertised count")
    if _hf_revision() != revision:
        raise ValueError("BigCodeBench: dataset revision changed during capture")
    cohorts: dict[str, dict] = {}
    for index, row in enumerate(rows):
        required = {"model", "link", "type", "complete", "instruct", "date", "prefill"}
        if not required.issubset(row):
            raise ValueError("BigCodeBench: missing leaderboard columns")
        model = _text(row["model"], "BigCodeBench model")
        if type(row["prefill"]) is not bool:
            raise ValueError("BigCodeBench: prefill must be boolean")
        configuration = {
            "type": _text(row["type"], "BigCodeBench type"),
            "prefill": row["prefill"],
            "benchmarkVersion": None,
        }
        for metric in ("complete", "instruct"):
            if row[metric] is None:
                continue
            cohort_id = f"bigcodebench:{metric}:{_partition(configuration)}"
            cohort = cohorts.setdefault(
                cohort_id,
                _cohort(
                    cohort_id,
                    f"BigCodeBench full {metric}, type={row['type']}, prefill={row['prefill']}",
                    "calibrated pass@1",
                    "generation_debugging",
                ),
            )
            cohort["benchmarkVersion"] = None
            cohort["category"] = metric
            cohort["harnessConfiguration"] = configuration
            cohort["interpretation"] = (
                "Full leaderboard reported calibrated pass@1; not BigCodeBench-Hard"
            )
            # The row index is an export identity, not a inferred checkpoint alias.
            record = _record(
                f"row:{index}",
                model,
                row[metric],
                configuration,
                row["link"],
            )
            record["rawSourceDate"] = row["date"]
            record["rawSourceDateNote"] = (
                "Upstream date semantics are unspecified; not treated as evaluation time"
            )
            record["sourceFields"] = row
            cohort["records"].append(record)
    snapshot = _snapshot(revision, artifacts, bodies)
    snapshot["cohorts"] = list(cohorts.values())
    snapshot["revisionBinding"] = (
        "Dataset HEAD identical before and after pagination; rows service does not expose/pin revision. Archived raw page bodies and hashes are authoritative capture evidence, not proof of server cache revision."
    )
    snapshot["rawArchive"] = archive
    return snapshot


def _atomic_write(path: Path, payload: dict) -> None:
    serialized = (
        json.dumps(payload, ensure_ascii=False, indent=4, allow_nan=False) + "\n"
    )
    if len(serialized.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("source cache exceeds the bounded output size")
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".json",
            delete=False,
        ) as stream:
            staging = Path(stream.name)
            stream.write(serialized)
        os.replace(staging, path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def _refresh_one(source_id: str, cache_path: Path, seed_sources: Path) -> dict:
    target = cache_path / f"{source_id}.json"
    previous = None
    initialization_issues = []
    try:
        previous = read_source(target)
        if previous["sourceId"] != source_id:
            raise ValueError("cache sourceId does not match its filename")
    except FileNotFoundError:
        previous = None
    except Exception as error:  # noqa: BLE001
        # Invalid cache evidence is not adopted; a validated seed can still recover it.
        initialization_issues.append(f"invalid cache: {one_line(error)[:300]}")
        previous = None
    if previous is None or previous["snapshot"] is None:
        if previous is not None:
            initialization_issues.append(
                "cache has no last-good snapshot; attempting validated seed baseline"
            )
        try:
            seed = read_source(seed_sources / f"{source_id}.json")
            if seed["sourceId"] != source_id:
                raise ValueError("seed sourceId does not match its filename")
            previous = seed
        except Exception as error:  # noqa: BLE001
            # Per-source fault boundary: invalid seeds are reported, never adopted.
            initialization_issues.append(
                f"invalid or missing seed: {one_line(error)[:300]}"
            )
    for issue in initialization_issues:
        print(f"{source_id}: {issue}", file=sys.stderr)
    previous = previous or {}
    try:
        snapshot = {
            "livebench": _livebench,
            "evalplus": _evalplus,
            "aider_polyglot": _aider_polyglot,
            "aider_python": _aider_python,
            "bigcodebench": _bigcodebench,
        }[source_id]()
        payload = {
            "schemaVersion": 2,
            "sourceId": source_id,
            "benchmark": _BENCHMARKS[source_id],
            "status": "success",
            "updatedAt": _now(),
            "lastFailedAt": previous.get("lastFailedAt"),
            "lastFailedMessage": previous.get("lastFailedMessage"),
            "snapshot": snapshot,
        }
        validate_source(payload)
    except Exception as error:  # noqa: BLE001
        # Top-level source isolation also covers unexpected upstream schema drift.
        message = f"{type(error).__name__}: {one_line(error)}"[:300]
        print(f"{source_id}: {message}", file=sys.stderr)
        payload = {
            "schemaVersion": 2,
            "sourceId": source_id,
            "benchmark": _BENCHMARKS[source_id],
            "status": "failed",
            "updatedAt": previous.get("updatedAt"),
            "lastFailedAt": _now(),
            "lastFailedMessage": message,
            "snapshot": previous.get("snapshot"),
        }
    if initialization_issues:
        payload["initializationIssues"] = initialization_issues
    persisted = True
    try:
        _atomic_write(target, payload)
    except Exception as error:  # noqa: BLE001
        # Cache I/O failure is separately reported; other sources still refresh.
        persisted = False
        print(f"{source_id}: cannot write cache: {one_line(error)}", file=sys.stderr)
        payload = {
            **payload,
            "status": "failed",
            "updatedAt": previous.get("updatedAt"),
            "lastFailedAt": _now(),
            "lastFailedMessage": f"cache_write_failed: {one_line(error)}"[:300],
            "snapshot": previous.get("snapshot"),
        }
        try:
            # An oversized new result can still report failure in a small wrapper.
            _atomic_write(target, payload)
        except Exception as record_error:  # noqa: BLE001
            # Fault boundary for reporting a failed cache write, not silent recovery.
            print(
                f"{source_id}: cannot record cache failure: {one_line(record_error)}",
                file=sys.stderr,
            )
        else:
            persisted = True
    return {
        **{key: value for key, value in payload.items() if key != "snapshot"},
        "cachePath": str(target),
        "persisted": persisted,
        "snapshotAvailable": payload["snapshot"] is not None,
        "cohortCount": len(payload["snapshot"]["cohorts"])
        if payload["snapshot"]
        else 0,
    }


def refresh_sources(cache_path: Path, seed_sources: Path) -> list[dict]:
    """Refresh each source independently and return bounded status summaries.

    cache_path contains sourceId.json files directly. seed_sources is the v2
    seed directory, not its schema-v1 parent. Missing, invalid and empty failed
    caches fall back to validated seeds, with initialization issues disclosed;
    failed refreshes preserve the last-good snapshot and success timestamp.
    persisted=False identifies an outcome that could not reach disk. No source
    failure prevents another source from refreshing. Deferred importers are not
    scheduled; their coverage limitations remain in the catalogue audit.
    """
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_refresh_one, source_id, cache_path, seed_sources)
            for source_id in SOURCE_IDS
        ]
        return [future.result() for future in futures]
