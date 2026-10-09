# Contributing

## Setup

Clone the repository and run the fetcher from its root:

```powershell
uv run python fetch_models.py
```

The supported runtime is Python 3.11 with the standard library only. Do not add a runtime
dependency. For providers whose fetch needs credentials, put the variables listed in
`.env.example` in your local `.env`. VS Code reads `.env` through `.vscode/launch.json`.

## Making a change

Read the relevant file and its neighboring provider or shared helper before editing. This
repository deliberately differs from common defaults in places. Follow `AGENTS.md` and its
conventions pointer rather than assuming a familiar project layout or style.

## Adding or updating a provider

Follow the five steps in [Adding a provider](README.md#adding-a-provider). In brief, add or
update the catalogue entry in `config/providers.json`, implement a `providers/<id>.py` module exposing
`fetch(provider_config: dict) -> list[dict]`, register the module in
`providers/__init__.py`, describe any source pages in `other_source`, and wire up credentials
if the fetch needs them. A provider id must match `[a-z0-9][a-z0-9_-]*`. Model ids must be
unique after case folding; `googleai` is matched on `name` instead of `id`.

A new keyed provider needs all of these coordinated pieces:

1. Add `keyEnvVar` to its `config/providers.json` entry and read the environment variable named by
   `provider_config["keyEnvVar"]` in its module, never by a hardcoded name.
2. Add `<NAME>: ${{ secrets.<NAME> }}` to the Fetch models step's `env:` block in
   `.github/workflows/fetch-models.yml`.
3. Create the matching repository secret.
4. Add the name to `.env.example` in the existing placeholder style.

Without the workflow entry or repository secret, scheduled runs publish
`"status": "failed"` indefinitely even when a local run works using `.env`.

## Refreshing snapshots

`data_templates/*.html` are hand-saved captures and go stale without a code change. Find the
snapshot's `auth: true` `other_source` URL in `config/providers.json`, open it while signed in, save
the rendered page over the corresponding path in `data_templates/`, and commit the capture.
For `googleai`, the page is <https://aistudio.google.com/rate-limit>. The script prints the
free models a capture does not cover. `mistral` and `ollama-cloud` decide which models count
as free from their captures, so stale snapshots can silently change the published lists.

## Verifying a change

Run only the affected provider while working:

```powershell
uv run python fetch_models.py --provider <id>
```

Then read the top-level `status` in `data/<id>.json`. An exit code of `0` means the outcome
was written, not that the provider succeeded. Inspect `count`, `data` and any
`lastFailedMessage` to explain the observable result. Before submitting, lint and format
every changed Python file with `uvx ruff check --fix <file>` and
`uvx ruff format <file>`, and format every changed JSON, YAML and Markdown file with
`npx prettier --write <file>`. A completed change has a successful provider status when a
fetch is applicable, an output list consistent with the documented free-model rule, and
formatted changed files. There is no test framework in this repository.

## Commits and pull requests

Read the existing commit style with `git log --oneline`. History uses the conventional-commit
prefixes `feat`, `fix`, `docs`, `refactor` and `chore`, sometimes with a scope. Target the
default branch with your pull request and describe the observable change in the provider
output, not just the code diff. Include the provider ids and the top-level output `status`
from verification.

## Out of scope

Changes that add a runtime dependency, weaken the HTTPS-only fetching or unique-id
guarantees in the writer, or hand-edit generated files under `data/` will be rejected.
`data/` is gitignored; commit source changes and hand-saved `data_templates/` captures
instead.
