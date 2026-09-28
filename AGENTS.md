# AGENTS.md

Guidance for AI coding agents working in this repository. Read this file before making changes.

---

## Project Overview

**Fetch Models** collects the free model catalogues of several LLM providers and writes one JSON file per provider into `data/`. A daily GitHub Actions run executes the script and publishes the results to the orphan branch `models-data`, which is what downstream projects read.

Core stack:

- Python 3.11, standard library only. No runtime dependency may be added.
- `uv` / `uvx` for every Python command, `ruff` for lint and format.
- `prettier` (via `npx`) for JSON, YAML and Markdown.
- GitHub Actions with a scheduled trigger and a repository secret.

## Commands

| Purpose            | Command                         |
| ------------------ | ------------------------------- |
| Lint (Python)      | `uvx ruff check --fix <file>`   |
| Format (Python)    | `uvx ruff format <file>`        |
| Format (JSON, etc) | `npx prettier --write <file>`   |
| Run script         | `uv run python fetch_models.py` |

**Always** run linting and formatting on every changed file before considering a change finished. Use `uv` / `uvx` for all Python tooling - never use `py -m pip`, `py -m ruff`, `.venv\Scripts\pip`, or any other Python/package manager.

All conditions MUST pass before a change is considered finished. There is no test framework configured in this repo. Do not invent or run a test command.

## Repository Layout

| Path                                 | Description                                                                               |
| ------------------------------------ | ----------------------------------------------------------------------------------------- |
| `fetch_models.py`                    | CLI entry point: provider dispatch, atomic JSON writing, per-provider failure isolation.  |
| `providers.json`                     | Provider catalogue and quotas. Every `id` here needs a module registered in the registry. |
| `providers/__init__.py`              | `REGISTRY` mapping provider ids to fetching modules.                                      |
| `providers/base.py`                  | `Provider` protocol plus the shared `models_url` config helper.                           |
| `providers/http_client.py`           | Shared `get_url` with the HTTPS-only check and transient-failure retries.                 |
| `providers/<id>.py`                  | One module per provider exposing `fetch(provider_config)`.                                |
| `data/`                              | Generated JSON files (gitignored) plus the committed rate-limit snapshot.                 |
| `.github/workflows/fetch-models.yml` | Daily fetch and publish to the `models-data` branch.                                      |

`data/google_rate_limits.html` is a hand-saved capture of the signed-in Google AI Studio
rate-limit page. Nothing fetches it, so it goes stale: refresh it by saving that page in a
browser and overwriting the file, and expect the script to warn about models it does not cover.

For end user documentation see [README.md](README.md).

## Coding Conventions

Read the relevant file before editing code in that area. Do not rely on general knowledge of a language or framework instead, because this repo intentionally diverges from common defaults in several places (strict typography rules and 4-space indentation are two examples). Formatting is also enforced by `.prettierrc.json` and `ruff`. All conventions are located in `~/.agents/conventions`.

| Area       | Doc                                   |
| ---------- | ------------------------------------- |
| Python     | `~/.agents/conventions/python.md`     |
| JavaScript | `~/.agents/conventions/javascript.md` |
