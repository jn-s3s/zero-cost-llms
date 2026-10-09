# AGENTS.md

Guidance for AI coding agents working in this repository. Read this file before making changes.

---

## Project Overview

**Fetch Models** collects the free model catalogues of several LLM providers and writes one JSON file per provider into `data/`. A daily GitHub Actions run executes the script and publishes the results to the orphan branch `models-data`, which is what downstream projects read.

Core stack:

- Python 3.11, standard library only. No runtime dependency may be added.
- `uv` / `uvx` for every Python command, `ruff` for lint and format.
- `prettier` (via `npx`) for JSON, YAML and Markdown.
- GitHub Actions with a scheduled trigger and one repository secret per provider that needs a key.

## Commands

| Purpose            | Command                         |
| ------------------ | ------------------------------- |
| Lint (Python)      | `uvx ruff check --fix <file>`   |
| Format (Python)    | `uvx ruff format <file>`        |
| Format (JSON, etc) | `npx prettier --write <file>`   |
| Run script         | `uv run python fetch_models.py` |

`uv run python fetch_models.py` exits `0` when every provider's outcome reached its file. That is not the same as every provider succeeding: read each `data/<id>.json` `status`, because a provider failure is stored in the data rather than in the exit code.

**Always** run linting and formatting on every changed file before considering a change finished. Use `uv` / `uvx` for all Python tooling - never use `py -m pip`, `py -m ruff`, `.venv\Scripts\pip`, or any other Python/package manager.

All conditions MUST pass before a change is considered finished. There is no test framework configured in this repo. Do not invent or run a test command.

## Repository Layout

| Path                                 | Description                                                                                        |
| ------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `fetch_models.py`                    | CLI entry point: provider dispatch, atomic JSON writing, per-provider failure isolation.           |
| `config/providers.json`              | Provider catalogue and quotas. Every `id` here needs a module registered in the registry.          |
| `config/skip_providers.json`         | Providers considered but not fetched, each with the reason it was skipped; not read by the script. |
| `config/benchmarks/`                 | Benchmark model identities, tier policy and curated SWE-bench/LiveCodeBench mappings.              |
| `providers/__init__.py`              | `REGISTRY` mapping provider ids to fetching modules.                                               |
| `providers/base.py`                  | `Provider` protocol plus the shared `models_url` config helper.                                    |
| `lib/__init__.py`                    | Shared utilities package.                                                                          |
| `lib/http_client.py`                 | Shared HTTP fetching with HTTPS-only checks and transient-failure retries.                         |
| `lib/html_tree.py`                   | Shared HTML element tree used by the providers that scrape a rendered page.                        |
| `lib/rate_limits.py`                 | Shared plumbing the quota-carrying providers use to scrape and attach per-model rate limits.       |
| `lib/limit_value.py`                 | Parses a scraped rate-limit cell that may carry a `K` or `M` suffix.                               |
| `lib/repo_root.py`                   | Absolute repository root, used to locate `config/providers.json`, `data/` and `data_templates/`.   |
| `providers/<id>.py`                  | One module per provider exposing `fetch(provider_config)`.                                         |
| `data/`                              | Generated JSON files, all gitignored.                                                              |
| `data_templates/`                    | Hand-saved pages the providers that cannot fetch them read as snapshots.                           |
| `.github/workflows/fetch-models.yml` | Daily fetch and publish to the `models-data` branch.                                               |

`data_templates/google_rate_limits.html` is a hand-saved capture of the signed-in Google AI Studio
rate-limit page. Nothing fetches it, so it goes stale: refresh it by saving that page in a
browser and overwriting the file, and expect the script to warn about models it does not cover.
`mistral_rate_limits.html`, `zai_rate_limits.html` and `ollama_cloud_free_models.html` are the
same kind of capture for those providers. `mistral` and `ollama-cloud` read theirs to decide
which models count as free at all, so a stale one quietly changes published results instead of
failing loudly.

For end user documentation see [README.md](README.md).

## Coding Conventions

Read the relevant file before editing code in that area. Do not rely on general knowledge of a language or framework instead, because this repo intentionally diverges from common defaults in several places (strict typography rules and 4-space indentation are two examples). Formatting is also enforced by `.prettierrc.json` and `ruff`. All conventions are located in `~/.agents/conventions`.

| Area       | Doc                                   |
| ---------- | ------------------------------------- |
| Python     | `~/.agents/conventions/python.md`     |
| JavaScript | `~/.agents/conventions/javascript.md` |
