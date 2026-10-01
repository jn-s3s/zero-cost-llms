# Changelog

This changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-01

First release. Nothing shipped under a version before this one, so everything
listed here is new rather than a change to an earlier release. `models-data`
has been publishing untagged output since before the tag, so treat that branch
as 1.0.0's data.

### Added

- Start a Python 3.11 standard-library fetcher that writes one JSON file per
  provider and publishes `data/` daily and on demand to the orphan
  `models-data` branch.
- Describe each provider in `providers.json` with `keyEnvVar`, `quota`,
  `other_source` and `channels`. Fetchers read the declared source type and
  snapshot path instead of inferring them from URL text or hardcoded
  locations.
- Add free-model fetching for `openrouter`, `requesty`, `routeway`,
  `googleai` and `nvidia`. `googleai` selects free models from its pricing page
  rather than assuming its models API includes prices, and `nvidia` matches API
  model ids against the filtered catalogue page, folding dots, underscores and
  hyphens to accommodate different spellings in card links.
- Add free-model fetching for `agnes`, `cerebras`, `cline`, `cloudflare`,
  `cohere`, `groq`, `kilo`, `llm7`, `mistral`, `ollama-cloud`, `opencode-zen`,
  `orcarouter`, `pollinations`, `qoder` and `zai`. Provider-specific API,
  pricing and free-tier checks expand the published catalogue to 20 providers.
  `requesty` treats a past retirement timestamp as retired alongside its zero
  input and output prices.
- Supply the keyed providers' credentials, including `CLOUDFLARE_ACCOUNT_ID`,
  through `.env.example` and the daily workflow so local and scheduled fetches
  can reach their authenticated endpoints.
- Add hand-saved pages under `data_templates/` for the signed-in `googleai`,
  `mistral`, `ollama-cloud` and `zai` sources. These supply quotas or free-model
  membership when the pages cannot be fetched directly; the captures need
  manual refreshes to stay current.
- Add per-model `rate_limits` from public quota pages for `groq` and `cerebras`
  and from saved pages for `mistral` and `zai`. Models without matching quota
  data remain available without a `rate_limits` field.
- Publish provider-level `status`, `count`, `updatedAt`, `lastFailedAt` and
  `lastFailedMessage` beside the `data` list. A failed fetch keeps the last
  successful models and records its failure, with configured credential values
  redacted from the recorded text, so consumers can distinguish a stale list
  from a current one without the failure leaking a key.
- Track model `presence`, `firstSeen`, `lastSeen` and `removedDate` in published
  data. Disappearing models stay marked as removed until the 90-day
  `REMOVED_RETENTION_DAYS` window expires, while `count` includes only active
  models.
- Add the repeatable `--provider` flag to fetch selected catalogue ids; unknown
  ids cause an error rather than an apparently successful partial run.
- Share HTTP fetching, HTML parsing and quota-value parsing through `lib/`,
  keeping provider filtering and quota extraction consistent.
- Seed each scheduled run from the existing `models-data` branch before
  fetching. Provider failures produce workflow warnings rather than discarding
  other providers' results; an unreportable outcome still fails the run.
- Ignore local credentials, Python caches and operating-system scratch files
  so they do not enter source control.

### Documentation

- Document each provider's free-model rule, keyed setup, snapshot refreshes,
  `rate_limits` coverage and the published model lifecycle in `README.md`.
- Name the project Zero Cost LLMs in `README.md`.
- Add `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, this changelog and
  an MIT `LICENSE` covering both the script and the published `data/` files.
- Add issue forms for new providers and stale snapshots, a pull request
  template and an issue chooser configuration.
