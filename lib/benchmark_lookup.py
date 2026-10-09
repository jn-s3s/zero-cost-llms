"""Shared exact-match lookup over the hand-written benchmark mappings.

Every mapping file is keyed by hand-written model spellings, so a lookup has to
tolerate spelling differences without ever guessing. Substring matching is
deliberately unsupported here: a bare family key such as ``deepseek`` then
matches every model in that family, which published a V3.2 score for unrelated
releases, and the winner depended on key order in the JSON. Both sides are
normalized the same way and matched exactly instead, so a published score comes
from one explicit key, or from the key of the base model when only a trailing
release qualifier such as a date or ``preview`` differs.

A mapping file that cannot be read, or that lists the same model twice with two
different scores, is reported on stderr rather than resolved silently, because
the alternative is publishing a score chosen by file order.
"""

from __future__ import annotations

import json
import re
import sys
from functools import cache

from lib.http_client import one_line
from lib.repo_root import REPO_ROOT

# A trailing release qualifier such as -2025-01-31, -2508 or -preview. Dropping
# one lets a dated or preview release fall back to the score of the base model.
# The spelling as given is always tried first, so an explicit dated or preview
# key in the mapping wins.
_RELEASE_QUALIFIER = re.compile(
    r"[-_@.]*(?:v?\d{8}|\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{2}-\d{4}"
    r"|\d{2}-\d{2}|v?\d{4}|previews?)$",
    re.IGNORECASE,
)


def normalize(spelling: str) -> str:
    """Return the canonical comparison form of a single model spelling."""
    cleaned = spelling.lower()
    for separator in "-_/":
        cleaned = cleaned.replace(separator, " ")
    return " ".join(cleaned.split())


def _identity(spelling: str) -> str:
    """Return the separator-free form a spelling shares with its aliases."""
    return normalize(spelling).replace(" ", "")


def _spelling_forms(spelling: str) -> list[str]:
    """Return the forms one raw spelling can be written as.

    A model id carries a provider namespace before one or two slashes, so every
    leading segment is dropped in turn and the remainder normalized:
    ``@cf/openai/gpt-oss-120b`` and ``openai/gpt-oss-120b`` both have to reach
    ``gpt oss 120b``. The spelling as written comes first, so a key that really
    does carry a namespace still wins, and a slash that is part of the model
    name itself, as in ``qwen3-coder-480b/a35b-instruct``, is reached after the
    provider prefix is dropped.
    """
    forms = []
    remainder = spelling
    while True:
        forms.append(normalize(remainder))
        if "/" not in remainder:
            break
        remainder = remainder.split("/", 1)[1]
    forms += [_identity(form) for form in forms]
    return [form for form in forms if form]


def _forms(spelling: str) -> list[str]:
    """Return every normalized form of a spelling, most specific first.

    Each spelling contributes all of its forms before the next one is tried, and
    a trailing release qualifier is only dropped once every form of the spelling
    carrying it has missed. So ``openai/o3-mini-2025-01-31`` resolves against
    ``o3 mini`` rather than a shorter key for a different model, while
    ``gemini-3-pro-preview`` still resolves against an explicit preview key.

    Each dropped qualifier shortens the spelling, so the walk always ends.
    """
    forms = []
    variant = spelling
    while variant:
        forms += _spelling_forms(variant)
        stripped = _RELEASE_QUALIFIER.sub("", variant)
        if stripped == variant:
            break
        variant = stripped
    return list(dict.fromkeys(forms))


@cache
def _read_mapping(filename: str) -> tuple[dict[str, float], dict[str, str]]:
    """Read one mapping file, naming it on stderr instead of swallowing a fault.

    A missing, unparseable or misshaped file would otherwise quietly delete
    every benchmark from the published data, so the failure is reported here
    and the file contributes nothing until it is repaired. A single row whose
    score is not a number is skipped for the same reason: one bad row should
    not cost the reader the whole file, and it should still be visible.

    An ``_meta`` object is read out first rather than as a spelling, and is
    where a file records where its numbers came from and when they were taken.

    Args:
        filename: The mapping file name, relative to the repository root.

    Returns:
        The spellings mapped to their scores, and the file's ``_meta`` block.
        Both are empty when the file could not be used at all.
    """
    path = REPO_ROOT / filename
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as error:
        print(f"{filename}: {one_line(error)}, publishing no scores", file=sys.stderr)
        return {}, {}
    except json.JSONDecodeError as error:
        print(f"{filename}: {one_line(error)}, publishing no scores", file=sys.stderr)
        return {}, {}
    if not isinstance(data, dict):
        print(
            f"{filename}: expected an object of spellings to scores, got "
            f"{type(data).__name__}, publishing no scores",
            file=sys.stderr,
        )
        return {}, {}
    raw_meta = data.get("_meta")
    meta = (
        {str(key): str(value) for key, value in raw_meta.items()}
        if isinstance(raw_meta, dict)
        else {}
    )
    mapping: dict[str, float] = {}
    for spelling, value in data.items():
        if str(spelling).startswith("_"):
            continue
        try:
            mapping[str(spelling).lower()] = float(value)
        except (TypeError, ValueError):
            print(
                f"{filename}: skipping {spelling!r}, score {value!r} is not a number",
                file=sys.stderr,
            )
    return mapping, meta


def _describe(tally: dict[float, int]) -> str:
    """Render one model's competing scores and how many spellings back each."""
    return " vs ".join(
        f"{value} ({count} spelling{'' if count == 1 else 's'})"
        for value, count in sorted(tally.items())
    )


def build_index(mapping: dict[str, float], source: str = "mapping") -> dict[str, float]:
    """Expand a raw mapping into normalized lookup keys.

    The mapping files repeat each model under several spellings, and a few
    models are spelled twice with two different scores. Group the spellings by
    model first, let the score most of them agree on win, and register every
    spelling of the model under that one score. A genuine tie stays out of the
    index rather than being published as the outcome of key order. Every
    disagreement is named on stderr, because a collapsed or dropped model is a
    mapping file that needs editing, not a result to quietly ship.

    Args:
        mapping: Spellings mapped to scores, as read from a mapping file.
        source: The file name, used only to say where the disagreement is.

    Returns:
        Normalized lookup keys mapped to one score each.
    """
    votes: dict[str, dict[float, int]] = {}
    for spelling, value in mapping.items():
        identity = _identity(spelling)
        if not identity:
            continue
        tally = votes.setdefault(identity, {})
        tally[value] = tally.get(value, 0) + 1

    resolved: dict[str, float] = {}
    disagreements: list[str] = []
    for identity, tally in sorted(votes.items()):
        top = max(tally.values())
        winners = sorted(value for value, count in tally.items() if count == top)
        if len(winners) != 1:
            disagreements.append(f"{identity} -> {_describe(tally)}, left unscored")
            continue
        resolved[identity] = winners[0]
        if len(tally) > 1:
            disagreements.append(f"{identity} -> {_describe(tally)}")

    if disagreements:
        print(
            f"{source}: one model listed with several scores: "
            + "; ".join(disagreements),
            file=sys.stderr,
        )

    index: dict[str, float] = {}
    for spelling in mapping:
        identity = _identity(spelling)
        if identity not in resolved:
            continue
        index[normalize(spelling)] = resolved[identity]
        index[identity] = resolved[identity]
    return index


@cache
def load_score_index(filename: str) -> dict[str, float]:
    """Load a mapping file and expand it into a normalized lookup index.

    Cached per file name, so each file is read and each warning printed once
    per run.
    """
    mapping, _ = _read_mapping(filename)
    return build_index(mapping, source=filename)


@cache
def load_score_metadata(filename: str) -> dict[str, str]:
    """Return the ``_meta`` block a mapping file records about its numbers.

    This is where a file says where its scores came from and when they were
    captured, so the published attribution can quote it instead of asserting a
    provenance the file never recorded. Empty when the file has no ``_meta``.
    """
    _, meta = _read_mapping(filename)
    return meta


def lookup_score(index: dict[str, float], *spellings: str | None) -> float | None:
    """Return the score for the first spelling that matches an index key.

    Spellings are tried in the order given and each one exhausts its forms
    before the next is considered, so a model id always outranks its display
    name.
    """
    for spelling in spellings:
        if not spelling:
            continue
        for form in _forms(spelling):
            if form in index:
                return index[form]
    return None
