# Contributing

## Setup

Clone the repository and run the fetcher from its root:

```powershell
uv run python fetch_models.py
```

The supported runtime is Python 3.11 with the standard library only. Do not add a runtime
dependency. Install `uv` and Node.js 24 or newer, then run `npm ci --ignore-scripts` for
the locked Prettier dependency. CI uses Node.js 24 and uv 0.11.1; Ruff is pinned to 0.16.10.
For providers whose fetch needs credentials, put the variables listed in
`.env.example` in your local `.env`. VS Code reads `.env` through `.vscode/launch.json`.

## Making a change

Read the relevant file and its neighboring provider or shared helper before editing. This
repository deliberately differs from common defaults in places. Follow `AGENTS.md` and its
conventions pointer rather than assuming a familiar project layout or style.

## Adding or updating a provider

Follow the five steps in [Adding a provider](README.md#adding-a-provider). In brief, add or
update the catalogue entry in `providers.json`, implement a `providers/<id>.py` module exposing
`fetch(provider_config: dict) -> list[dict]`, register the module in
`providers/__init__.py`, describe any source pages in `other_source`, and wire up credentials
if the fetch needs them. A provider id must match `[a-z0-9][a-z0-9_-]*`. Model ids must be
unique after case folding; `googleai` is matched on `name` instead of `id`.

A new keyed provider needs all of these coordinated pieces:

1. Add `keyEnvVar` to its `providers.json` entry and read the environment variable named by
   `provider_config["keyEnvVar"]` in its module, never by a hardcoded name.
2. Add `<NAME>: ${{ secrets.<NAME> }}` to the Fetch models step's `env:` block in
   `.github/workflows/fetch-models.yml`.
3. Create the matching repository secret.
4. Add the name to `.env.example` in the existing placeholder style.

Without the workflow entry or repository secret, scheduled runs publish
`"status": "failed"` indefinitely even when a local run works using `.env`.

## Refreshing snapshots

`data_templates/*.html` are hand-saved captures and go stale without a code change. Find the
snapshot's `auth: true` `other_source` URL in `providers.json`, open it while signed in, save
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
every changed Python file with `uvx ruff@0.16.10 check --fix <file>` and
`uvx ruff@0.16.10 format <file>`, and format every changed JSON, YAML and Markdown file with
`npx prettier --write <file>`. A completed change has a successful provider status when a
fetch is applicable, an output list consistent with the documented free-model rule, and
formatted changed files. Run the complete mandatory quality gate before submitting:

```powershell
npm run check
```

This runs Ruff linting, Ruff's format check and Prettier's format check, without rewriting
files. CI and release use this same command through `.github/actions/project-checks`.
Hand-saved captures and generated output are excluded from Prettier. There is no test
framework or type-checking gate in this repository; quality checks do not call provider APIs
or require provider secrets.

## Commits and pull requests

Read the existing commit style with `git log --oneline`. History uses the conventional-commit
prefixes `feat`, `fix`, `docs`, `refactor` and `chore`, sometimes with a scope. Start feature
and fix branches from the updated remote `dev` branch. Target `dev` with your pull request
and describe the observable change in the provider
output, not just the code diff. Include the provider ids and the top-level output `status`
from verification when applicable. Squash a short, single-purpose feature or fix PR; use a
merge commit when preserving individual commits matters.

`main` accepts only same-repository release PRs from `dev`, merged with a merge commit.
Keep both permanent branches. Synchronize `main` back into `dev` through a merge PR after
a release; that PR needs quality checks but no new release version. Do not squash merges
between permanent branches. Ordinary fixes follow `dev`; an urgent production hotfix
requires an explicitly agreed source-branch exception in the release gate first.

## Releases and repository protections

`package.json` is the canonical project version, not a published npm package: it is private
and otherwise only manages formatting tools. Prepare a dated Keep a Changelog entry and
update this version and the lockfile together on a preparation branch targeting `dev`.
Leave `## [Unreleased]` empty before opening `dev` into `main`. If more changes merge into
`dev` during preparation, refresh the pending entry before the release PR is merged.

The `CI` workflow reports `Quality checks` for both permanent branches and a separate
`Changelog gate` for PRs into `main`. The gate verifies the source repository and branch,
version/changelog equality, meaningful release notes, valid dates, descending stable
versions, a version newer than existing stable tags and the absence of its `v<version>` tag.
The first release is supported without a previous tag. The existing `v1.0.0` is preserved;
the next release requires a newer version rather than retagging 1.0.0.

After a release merge, `Tag release` validates the triggering commit and creates its tag
with the built-in `GITHUB_TOKEN`. A tag push with that token would not trigger another
workflow, so the workflow writes the ref through the REST API and calls `Release` directly
as a reusable workflow in the same run, passing the tag and commit explicitly. No
repository secret is needed. Tag creation stays unrestricted in the release-tag ruleset so
the automation token can write the ref, while updates, deletions and force pushes still
require the Admin bypass. Checkout credentials are not persisted.

`Release` validates the tagged version, runs shared checks, builds and verifies a ZIP of
tracked source and saved snapshots, then creates an empty-body draft and attaches the ZIP.
It does not fetch provider data, publish a package or publish the GitHub release. Fill notes
from the tagged changelog and review the draft separately before publishing. A retry reuses
an existing draft without changing its notes; an already public release stops the run
without changing publication status or assets. An existing tag is reusable only when it
identifies the same triggering commit. Never move or delete released tags for recovery.

The daily/on-demand `Fetch models` workflow remains separate and continues publishing to
the unprotected orphan `models-data` branch. GitHub Pages settings are unchanged.

### Ruleset policy and bootstrap

Reviewable desired API payloads are in `.github/rulesets/`. The setup snapshot on
2026-10-09 verified all three rulesets as active:

| Ruleset                    | ID       | Target                        | Required checks after bootstrap    | Bypass                       |
| -------------------------- | -------- | ----------------------------- | ---------------------------------- | ---------------------------- |
| Protect main branch        | 24309551 | `main` and the default branch | `Quality checks`, `Changelog gate` | None                         |
| Protect integration branch | 24775543 | `dev`                         | `Quality checks`                   | Maintain and Admin, `always` |
| Protect release tags       | 24775546 | `v*` tags                     | None                               | Admin, `always`              |

At that snapshot, main and dev had no registered required checks because these workflows
had not run yet. Full setup remains incomplete until the bootstrap steps below are finished.

Both branches require PRs with zero approvals, block deletions and force pushes, and do not
require linear history. Main permits merge commits only. Dev permits the existing merge
methods, but use merge commits for synchronization. Tag updates, deletions and force pushes
require bypass; tag creation stays unrestricted because the automation token must be able
to write the ref. Maintain/Admin bypass is an exception, not the normal dev
merge path. Keep merge commits enabled in repository settings and never delete `dev`.

Up-to-date checks are required once check registration is complete. Checks are bound to the
GitHub Actions App (15368), not the scheduled `fetch-models` job. No merge queue is enabled;
adding one requires adapting workflow events and source validation first.

New check contexts are not required during bootstrap until their workflows can run:

1. Install these files through a feature PR into `dev`. Observe `Quality checks` before
   merging, then apply `.github/rulesets/dev.json` to the integration ruleset with a PUT.
2. Merge a newer changelog/version preparation into `dev` and open the first release PR
   into `main`. Observe both quality and changelog jobs, then apply
   `.github/rulesets/main.json` to the existing main ruleset with a PUT before merging.
3. Verify effective branch rules and nonempty required-check lists in GitHub. The
   release-tag ruleset must show no creation rule, so the built-in token can tag, while
   its update, deletion and non-fast-forward rules remain. Do not create a real release
   tag as a setup test.

For an authorized ruleset update, first re-read the selected ruleset and preserve any
unrelated settings. Always pair its ID with its matching payload and verify that same ID;
never substitute only the ID in a command copied from a different ruleset:

```powershell
gh api repos/jn-s3s/zero-cost-llms/rulesets/24775543
gh api --method PUT repos/jn-s3s/zero-cost-llms/rulesets/24775543 --input .github/rulesets/dev.json
if ($LASTEXITCODE -ne 0) { throw "Ruleset update failed." }
gh api repos/jn-s3s/zero-cost-llms/rulesets/24775543
if ($LASTEXITCODE -ne 0) { throw "Ruleset verification failed." }
```

Use `24309551` with `.github/rulesets/main.json` for main, or `24775546` with
`.github/rulesets/release-tags.json` for release tags; verify each using its own ruleset ID.

## Out of scope

Changes that add a runtime dependency, weaken the HTTPS-only fetching or unique-id
guarantees in the writer, or hand-edit generated files under `data/` will be rejected.
`data/` is gitignored; commit source changes and hand-saved `data_templates/` captures
instead.
