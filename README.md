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

`providers.json` also carries a `nvidia` entry that has no fetcher module yet. It is kept on
purpose while that provider is being designed, and it means every scheduled run ends red with
`nvidia: unsupported provider: nvidia`. Read that one line as expected until
`providers/nvidia.py` and its `REGISTRY` entry land; any other failing provider is a real
incident.

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

The exit code is `0` only when every provider succeeded. A provider that fails is reported
on stderr and the remaining providers still run, so one broken API never discards the work
of the others. Each file is written atomically, and a provider that returns no free models
at all is treated as a failure so the previous file survives untouched.

## Output

`data/<provider id>.json` holds the provider's own model objects, so the shape differs per
provider:

- `openrouter`, `requesty` and `routeway` entries are the upstream objects, keyed by `id`.
- `googleai` entries are keyed by `name` (`models/gemini-2.5-flash`) and get a `rate_limits`
  object added when the saved snapshot covers that model. The object holds `rpm`, `tpm` and
  `rpd`, where `null` means unlimited. A missing `rate_limits` key means unknown, not
  unrestricted, so treat it as "no quota information" rather than a zero.

Google's `rate_limits` come from `data/google_rate_limits.html`, a hand-saved capture of the
signed-in rate-limit page, because that page cannot be fetched with an API key. The file goes
stale on its own: refresh it by opening <https://aistudio.google.com/rate-limit> while signed
in, saving the rendered page over that path and committing it. The script prints the free
models the capture does not cover.

## Adding a provider

1. Add an entry to `providers.json` with a lowercase `id`, `api.baseUrl` and
   `api.models.endpoint`.
2. Add `providers/<id>.py` exposing `fetch(provider_config: dict) -> list[dict]`.
3. Register the module in `REGISTRY` in `providers/__init__.py`. An id listed in
   `providers.json` without a registered module fails the run.

## Automation

`.github/workflows/fetch-models.yml` runs daily and on demand. It needs the repository
secret `GOOGLE_API_KEY`. It fetches into a temporary directory, then commits whatever the run
produced to the orphan branch `models-data`, which holds nothing but `data/`. Files for
providers that failed stay at their last published version instead of disappearing.
