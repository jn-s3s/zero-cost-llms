# Fetch Models

Collects the free model catalogues of several LLM providers into one JSON file per
provider, and publishes them from a daily GitHub Actions run to the `models-data` branch.

The script needs Python 3.11 and nothing else: it runs on the standard library only.

## Providers

| Id           | How a model is judged free                                                        |
| ------------ | --------------------------------------------------------------------------------- |
| `openrouter` | `id` ends with `:free` or starts with `stealth`                                   |
| `requesty`   | `input_price` and `output_price` are both exactly zero                            |
| `routeway`   | `id` ends with `:free`                                                            |
| `googleai`   | Standard input and output prices read "free of charge" on the Google pricing page |
| `nvidia`     | Its id appears on the "Free Endpoint" filtered page on build.nvidia.com           |

The `nvidia` free list comes from one unpaginated catalogue request (`pageSize=100` in
`providers.json`), so it can only cover the first 100 free endpoints. Card links and API ids
differ in how they write a dot (`glm-5.3` versus `glm-5-3`), so the two are matched on a key
that folds dots, underscores and hyphens together.

## Setup

```powershell
uv run python fetch_models.py
```

`GOOGLE_API_KEY` must be present in the environment for the `googleai` provider; every
other provider is read without a key. In VS Code the key is picked up from `.env` through
`.vscode/launch.json`.

| Flag          | Default            | Purpose                                    |
| ------------- | ------------------ | ------------------------------------------ |
| `--providers` | `./providers.json` | Provider catalogue to fetch.               |
| `--output`    | `./data`           | Directory the JSON files are written into. |

The script exits `0` when every provider's outcome reached its file, even when one or more
providers fail: each failure is reported on stderr and recorded in the provider's file with
`"status": "failed"`, keeping the models of the last success, so consumers always see the
latest outcome instead of a stale success. The remaining providers still run, so one broken
API never discards the work of the others. It exits `1` when it cannot report what happened:
a catalogue it cannot read, parse or treat as a list of providers, an entry whose `id` is
missing, unsafe as a file name or repeated, or a result it could not write.

## Output

`data/<provider id>.json` holds a wrapper object that describes the provider's latest fetch.
Every key is always present, and `null` marks a value the provider never had:

| Field               | Meaning                                                                                             |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `status`            | `"success"` or `"failed"` for the latest fetch.                                                     |
| `count`             | Number of entries in `data`, so it also matches a failed fetch.                                     |
| `updatedAt`         | ISO 8601 UTC timestamp of the latest success, `null` before the first one.                          |
| `lastFailedAt`      | ISO 8601 UTC timestamp of the latest failure, `null` when none happened yet.                        |
| `lastFailedMessage` | Exception type and the first 300 characters of the failure text, on one line, `null` when none yet. |
| `data`              | The model objects of the latest success, empty before the first one.                                |

On a successful fetch `count`, `updatedAt` and `data` are refreshed while any previous
`lastFailedAt` and `lastFailedMessage` are kept. On a failed fetch `lastFailedAt` and
`lastFailedMessage` are refreshed while `count`, `updatedAt` and `data` keep the values of the
last success, so a provider that has never succeeded publishes an empty list. A fetch that
returns no free models at all counts as a failure, so an empty result never replaces a good
list.

Files published before the wrapper existed hold the bare model array as the whole file, so
read the list from `data` and treat a top-level array as the older shape. That costs one
transitional case: a file adopted from the old shape can show a non-empty `data` next to
`updatedAt: null` until that provider's next success.

The `data` array holds the provider's own model objects, so the shape differs per provider:

- `openrouter`, `requesty`, `routeway` and `nvidia` entries are the upstream objects, keyed
  by `id`.
- `googleai` entries are keyed by `name` (`models/gemini-2.5-flash`) and get a `rate_limits`
  object added when the saved snapshot covers that model. The object holds `rpm`, `tpm` and
  `rpd`, where `null` means unlimited or simply not shown in the capture. A missing
  `rate_limits` key means unknown, not
  unrestricted, so treat it as "no quota information" rather than a zero.

Google's `rate_limits` come from `data/google_rate_limits.html`, a hand-saved capture of the
signed-in rate-limit page, because that page cannot be fetched with an API key. The file goes
stale on its own: refresh it by opening <https://aistudio.google.com/rate-limit> while signed
in, saving the rendered page over that path and committing it. The script prints the free
models the capture does not cover.

## Adding a provider

1. Add an entry to `providers.json` with `api.baseUrl` and `api.models.endpoint`, and an `id`
   matching `[a-z0-9][a-z0-9_-]*`: it is also the file name `data/<id>.json`, so an `id` with
   a dot, a space or a capital letter is refused as an unusable catalogue entry.
2. Add `providers/<id>.py` exposing `fetch(provider_config: dict) -> list[dict]`. Every model
   it returns must carry an `id` that no other model shares once case is folded, because the
   writer rejects a duplicate; `googleai` is the one exception, matched on `name`.
3. Add the module to the `from . import ...` line in `providers/__init__.py` and register it
   in `REGISTRY` there. An id listed in `providers.json` without a registered module is
   published as a failed fetch for that provider.

## Automation

`.github/workflows/fetch-models.yml` runs daily and on demand. It needs the repository
secret `GOOGLE_API_KEY`. Before fetching it unpacks the current `data/` from the orphan branch
`models-data` into the output directory, so a provider that fails today republishes the models
of its last success with `"status": "failed"` and the reason, letting downstream consumers
show the list and the failure at the same time. Each failed provider is also raised as a
warning annotation on the run, since a provider failure alone no longer turns the job red, and
a seed step that cannot reach the branch stops the run rather than publishing a half-read
tree. The branch holds nothing but `data/`.
