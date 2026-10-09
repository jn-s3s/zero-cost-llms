# Zero Cost LLMs

Collects the free model catalogues of several LLM providers into one JSON file per
provider, and publishes them from a daily GitHub Actions run to the `models-data` branch.

The script needs Python 3.11 and nothing else: it runs on the standard library only.

## Providers

| Id             | How a model is judged free                                                                                 |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `openrouter`   | `id` ends with `:free` or starts with `stealth`                                                            |
| `requesty`     | `input_price` and `output_price` are both exactly zero and `retires` (when numeric) is still in the future |
| `routeway`     | `id` ends with `:free`                                                                                     |
| `googleai`     | Standard input and output prices read "free of charge" on the Google pricing page                          |
| `nvidia`       | Its id appears on the "Free Endpoint" filtered page on build.nvidia.com                                    |
| `groq`         | Every model its keyed `/models` endpoint lists, with no price filter applied                               |
| `ollama-cloud` | Its id is listed in the `#free-plan-models` section of the saved settings snapshot                         |
| `cloudflare`   | Its `/models` entry lacks the `require_workers_paid` property                                              |
| `zai`          | Its row on the pricing page has both the Input and Output cells reading "Free"                             |
| `orcarouter`   | `id` ends with `-free` or `/free`                                                                          |
| `kilo`         | `isFree` is true and `expiration_date` is absent or still in the future                                    |
| `pollinations` | `id` ends with `:free`                                                                                     |
| `opencode-zen` | `id` ends with `-free`                                                                                     |
| `mistral`      | Its id appears in the saved rate-limits snapshot that lists the free tier                                  |
| `cohere`       | Its id starts with a name taken from the Cohere rate-limits page, lowercased and hyphenated                |
| `llm7`         | `tier` is `"turbo"`                                                                                        |
| `agnes`        | Its id appears on the Agnes pricing page at a current price of $0                                          |
| `cline`        | `id` ends with `:free` or starts with `stealth`                                                            |
| `qoder`        | `price_factor` is `0`                                                                                      |
| `cerebras`     | Every model its keyed `/models` endpoint lists, with no price filter applied                               |

The `nvidia` free list comes from one unpaginated catalogue request (`pageSize=100` in
`config/providers.json`), so it can only cover the first 100 free endpoints. Card links and API ids
differ in how they write a dot (`glm-5.3` versus `glm-5-3`), so the two are matched on a key
that folds dots, underscores and hyphens together.

## Setup

```powershell
uv run python fetch_models.py
```

Eight providers read an authenticated endpoint, so they need their key in the environment:
`googleai`, `groq`, `agnes`, `cerebras`, `cloudflare`, `cohere`, `mistral` and `qoder`.
`cloudflare` also needs `CLOUDFLARE_ACCOUNT_ID` beside its token. The other twelve providers are
read without a key, and `zai` is one of them: it scrapes the public pricing page and a committed
snapshot, so its `keyEnvVar` in `config/providers.json` describes the provider's own API rather than a
key the fetch needs. The variable each keyed provider uses is its `keyEnvVar` in `config/providers.json`.
In VS Code the keys are picked up from `.env` through `.vscode/launch.json`.

| Flag          | Default                      | Purpose                                                                                             |
| ------------- | ---------------------------- | --------------------------------------------------------------------------------------------------- |
| `--providers` | `./config/providers.json`    | Provider catalogue to fetch.                                                                        |
| `--output`    | `./data`                     | Directory the JSON files are written into.                                                          |
| `--provider`  | every entry in the catalogue | Fetch only this id, repeatable. An id the catalogue does not list is refused and the run exits `1`. |

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

| Field               | Meaning                                                                                                                                   |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `status`            | `"success"` or `"failed"` for the latest fetch.                                                                                           |
| `count`             | Number of active entries in `data`, those whose `presence` is not `"removed"`, so it drops below the array length once any model retires. |
| `updatedAt`         | ISO 8601 UTC timestamp of the latest success, `null` before the first one.                                                                |
| `lastFailedAt`      | ISO 8601 UTC timestamp of the latest failure, `null` when none happened yet.                                                              |
| `lastFailedMessage` | Exception type and the first 300 characters of the failure text, on one line, `null` when none yet.                                       |
| `data`              | The model objects of the latest success plus the retired ones kept for history, empty before the first success.                           |

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

Every entry in `data` also carries five fields the writer adds, which is how a model that
disappears upstream stays in the file instead of vanishing:

| Field         | Meaning                                                                                                            |
| ------------- | ------------------------------------------------------------------------------------------------------------------ |
| `presence`    | `"active"` when the latest success listed the model, `"removed"` when it dropped out and is kept only for history. |
| `firstSeen`   | ISO 8601 UTC timestamp of the first fetch that listed the model.                                                   |
| `lastSeen`    | ISO 8601 UTC timestamp of the latest success that listed the model, frozen at the last listing once removed.       |
| `removedDate` | ISO 8601 UTC timestamp of the success that first found the model missing, `null` while it is active.               |
| `status`      | Always `null`: the writer replaces whatever the provider returned under that key.                                  |

Read `presence` to separate the live catalogue from the retired leftovers, since `count` is the
live total while the array itself holds both.

Retired entries are not kept forever: a successful fetch drops every model whose `removedDate`
is older than 90 days (`REMOVED_RETENTION_DAYS` in `fetch_models.py`), so a provider with heavy
catalogue churn stops its file and daily commit diff from growing without bound.

The other fields on an entry come from the provider, so the shape differs per provider:

- `googleai` entries are keyed by `name` (`models/gemini-2.5-flash`), every other provider keys
  by `id`.
- `zai` entries hold only `id`, `object` and `owned_by`, because the pricing page they are read
  from publishes no model object to copy.
- `rate_limits` is added when a quota source covers that model, and its keys are not the same
  across providers: `googleai` uses `rpm`, `rpd` and `tpm`, `groq` uses `asd`, `ash`, `rpm`,
  `rpd`, `tpd` and `tpm`, `cerebras` uses `rpm`, `tpd`, `tph`, `total_tpm` and `uncached_tpm`,
  `mistral` uses `rps` and `tpm` and `zai` uses `concurrency`. No other provider adds it. A
  `null` inside one means unlimited or simply not shown in the source, and a missing
  `rate_limits` key means unknown, not unrestricted, so treat it as "no quota information"
  rather than a zero.

Four providers read a saved page rather than a live one, so their results only move when the
capture is refreshed: `googleai` from `data_templates/google_rate_limits.html`, `mistral` from
`data_templates/mistral_rate_limits.html`, `ollama-cloud` from
`data_templates/ollama_cloud_free_models.html` and `zai` from
`data_templates/zai_rate_limits.html`. `ollama-cloud` and `mistral` decide free status from that
file, so a stale capture silently shrinks or grows their lists. The captures go stale on their own:
refresh one by opening its `auth: true` `other_source` url while signed in, saving the rendered
page over that path and committing it. Google's is <https://aistudio.google.com/rate-limit>, and
the script prints the free models a capture does not cover.

## Adding a provider

1. Add an entry to `config/providers.json` with `api.baseUrl` and `api.models.endpoint`, and an `id`
   matching `[a-z0-9][a-z0-9_-]*`: it is also the file name `data/<id>.json`, so an `id` with
   a dot, a space or a capital letter is refused as an unusable catalogue entry.
2. Add `providers/<id>.py` exposing `fetch(provider_config: dict) -> list[dict]`. Every model
   it returns must carry an `id` that no other model shares once case is folded, because the
   writer rejects a duplicate; `googleai` is the one exception, matched on `name`.
3. Add the module to the `from . import ...` line in `providers/__init__.py` and register it
   in `REGISTRY` there. An id listed in `config/providers.json` without a registered module is
   published as a failed fetch for that provider.
4. If the fetch needs a key, give the catalogue entry a `keyEnvVar` naming the environment
   variable, and read it through `provider_config["keyEnvVar"]` in the module rather than a
   hardcoded name. If the fetch reads pages to decide free status or limits, add them to
   `other_source` with the `type` the module selects (`"pricing"`, `"quota"`, `"models"` or
   `"settings"`, while `"reference"` marks a source no module reads, recorded only so the catalogue
   documents where a claim came from): a live page carries `url`, an auth-gated one carries
   `snapshot`, the committed capture under `data_templates/` the module reads instead.
5. For a keyed provider, wire that variable through the pipeline before the first scheduled
   run: add `<NAME>: ${{ secrets.<NAME> }}` to the `env:` block of the Fetch models step in
   `.github/workflows/fetch-models.yml`, create the matching repository secret, and list the
   name in `.env.example`, in the same placeholder style as the entries already listed there.
   Miss the workflow entry or the secret and the daily run sees the variable unset and publishes
   `"status": "failed"` forever, while a local run still works through `.env`.

## Automation

`.github/workflows/fetch-models.yml` runs daily and on demand. It needs the nine repository
secrets `AGNES_API_KEY`, `CEREBRAS_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
`COHERE_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY` and
`QODER_ACCESS_TOKEN`, one per keyed provider plus Cloudflare's account id. A provider whose
secret is missing publishes `"status": "failed"` for every run, so its file stops refreshing
while the job still exits `0`. Before fetching it unpacks the current `data/` from the orphan
branch `models-data` into the output directory, so a provider that fails today republishes the
models of its last success with `"status": "failed"` and the reason, letting downstream consumers
show the list and the failure at the same time. Each failed provider is also raised as a
warning annotation on the run, since a provider failure alone no longer turns the job red, and
a seed step that cannot reach the branch stops the run rather than publishing a half-read
tree. The branch holds nothing but `data/`.

## Contributing and governance

| Document                                 | Covers                                                                    |
| ---------------------------------------- | ------------------------------------------------------------------------- |
| [API reference](docs/index.md)           | Published endpoints per provider, served as the GitHub Page               |
| [CONTRIBUTING.md](CONTRIBUTING.md)       | Setup, adding or updating a provider, refreshing a snapshot, verification |
| [SECURITY.md](SECURITY.md)               | Reporting a vulnerability or a leaked provider key                        |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Expected behaviour in project spaces                                      |
| [CHANGELOG.md](CHANGELOG.md)             | Dated history, derived from commits while the project is untagged         |
| [LICENSE](LICENSE)                       | MIT terms covering the script and the published `data/` files             |

The two ways a provider's list can be wrong have different routes. A provider that silently
publishes paid models as free, or a leaked key, is a security report. A stale capture in
`data_templates/` that makes a list shrink or grow is an ordinary bug, reported through the
stale-snapshot issue form.
