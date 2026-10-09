# Zero Cost LLMs

Free model catalogues from 20 providers, collected daily and published as JSON.

This page is the reference for the published data. For how the collector works, how to
add a provider, and how the files are structured, see the
[repository](https://github.com/jn-s3s/zero-cost-llms).

## Endpoints

One file per provider, refreshed by a scheduled run once a day:

```
https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/<provider id>.json
```

The `<provider id>` is the id in the table below, and it is also the file name. There is no
single combined file, so a consumer that wants every provider fetches the 20 files it needs.

### GitHub raw

```
https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/openrouter.json
```

The authoritative source, served by GitHub with `Cache-Control: max-age=300`, so a fetch
sees a new publish within about 5 minutes. It sends
`Access-Control-Allow-Origin: *`, so a browser can read it directly. This is the default
choice.

### jsDelivr

```
https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/openrouter.json
```

A CDN in front of the same file, useful for spreading load or avoiding GitHub rate limits. It
sends `Access-Control-Allow-Origin: *` as well, but it caches branch URLs for 12 hours
(`s-maxage=43200`), so it can serve data from before the last publish. Use it when a CDN
matters more than having today's data, and check `updatedAt` when freshness matters.

The `@models-data` suffix is required. Without it jsDelivr resolves the default branch, which
is `main` and does not hold `data/`.

## Providers

| Id                                                                                                           | Provider        | Key                    | Reads a snapshot                | Data                                                                                         |
| ------------------------------------------------------------------------------------------------------------ | --------------- | ---------------------- | ------------------------------- | -------------------------------------------------------------------------------------------- |
| [`openrouter`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/openrouter.json)     | OpenRouter      | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/openrouter.json)   |
| [`requesty`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/requesty.json)         | Requesty        | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/requesty.json)     |
| [`routeway`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/routeway.json)         | Routeway        | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/routeway.json)     |
| [`googleai`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/googleai.json)         | Google AI       | `GOOGLE_API_KEY`       | `google_rate_limits.html`       | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/googleai.json)     |
| [`nvidia`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/nvidia.json)             | NVIDIA NIM      | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/nvidia.json)       |
| [`groq`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/groq.json)                 | Groq            | `GROQ_API_KEY`         | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/groq.json)         |
| [`ollama-cloud`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/ollama-cloud.json) | Ollama Cloud    | no                     | `ollama_cloud_free_models.html` | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/ollama-cloud.json) |
| [`cloudflare`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/cloudflare.json)     | Cloudflare AI   | `CLOUDFLARE_API_TOKEN` | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/cloudflare.json)   |
| [`zai`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/zai.json)                   | ZAI             | no                     | `zai_rate_limits.html`          | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/zai.json)          |
| [`orcarouter`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/orcarouter.json)     | OrcaRouter      | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/orcarouter.json)   |
| [`kilo`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/kilo.json)                 | Kilo            | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/kilo.json)         |
| [`pollinations`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/pollinations.json) | Pollinations AI | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/pollinations.json) |
| [`opencode-zen`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/opencode-zen.json) | OpenCode Zen    | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/opencode-zen.json) |
| [`mistral`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/mistral.json)           | Mistral LP      | `MISTRAL_API_KEY`      | `mistral_rate_limits.html`      | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/mistral.json)      |
| [`cohere`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/cohere.json)             | Cohere          | `COHERE_API_KEY`       | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/cohere.json)       |
| [`llm7`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/llm7.json)                 | LLM7            | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/llm7.json)         |
| [`agnes`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/agnes.json)               | Agnes AI        | `AGNES_API_KEY`        | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/agnes.json)        |
| [`cline`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/cline.json)               | Cline           | no                     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/cline.json)        |
| [`qoder`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/qoder.json)               | Qoder           | `QODER_ACCESS_TOKEN`   | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/qoder.json)        |
| [`cerebras`](https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/data/cerebras.json)         | Cerebras        | `CEREBRAS_API_KEY`     | no                              | [json](https://cdn.jsdelivr.net/gh/jn-s3s/zero-cost-llms@models-data/data/cerebras.json)     |

`Key` is the environment variable the daily run needs to collect that provider, not a key a
consumer of the data needs. The published files are public and unauthenticated. Twelve
providers are collected without a key at all.

`Reads a snapshot` marks a provider whose free status comes from a hand-saved page under
`data_templates/` rather than a live one, so its list only changes when that capture is
refreshed in the repository. `ollama-cloud` and `mistral` decide free status from the capture
itself, so a stale one silently changes their results.

## Upstream endpoints

Where each provider's models are collected from. These are the provider APIs, not this
project's, and most need a key of your own to call.

| Id             | Models endpoint                                                                          |
| -------------- | ---------------------------------------------------------------------------------------- |
| `openrouter`   | `https://openrouter.ai/api/v1/models`                                                    |
| `requesty`     | `https://router.requesty.ai/v1/models`                                                   |
| `routeway`     | `https://api.routeway.ai/v1/models`                                                      |
| `googleai`     | `https://generativelanguage.googleapis.com/v1beta/models`                                |
| `nvidia`       | `https://integrate.api.nvidia.com/v1/models`                                             |
| `groq`         | `https://api.groq.com/openai/v1/models`                                                  |
| `ollama-cloud` | `https://ollama.com/v1/models`                                                           |
| `cloudflare`   | `https://api.cloudflare.com/client/v4/accounts/<CLOUDFLARE_ACCOUNT_ID>/ai/models/search` |
| `zai`          | `https://api.z.ai/api/coding/paas/v4/models`                                             |
| `orcarouter`   | `https://api.orcarouter.ai/v1/models`                                                    |
| `kilo`         | `https://api.kilo.ai/api/gateway/models`                                                 |
| `pollinations` | `https://gen.pollinations.ai/v1/models`                                                  |
| `opencode-zen` | `https://opencode.ai/zen/v1/models`                                                      |
| `mistral`      | `https://api.mistral.ai/v1/models`                                                       |
| `cohere`       | `https://api.cohere.ai/compatibility/v1/models`                                          |
| `llm7`         | `https://api.llm7.io/v1/models`                                                          |
| `agnes`        | `https://apihub.agnes-ai.com/v1/models`                                                  |
| `cline`        | `https://api.cline.bot/api/v1/models`                                                    |
| `qoder`        | `https://api.qoder.com/api/v1/forward/models`                                            |
| `cerebras`     | `https://api.cerebras.ai/v1/models`                                                      |

`cloudflare` builds its URL from `CLOUDFLARE_ACCOUNT_ID`, so the path segment is a
placeholder rather than a literal.

## Reading a file

Each file is a wrapper object. Every key is always present, and `null` marks a value the
provider never had:

| Field               | Meaning                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| `status`            | `"success"` or `"failed"` for the latest fetch.                         |
| `count`             | Number of active entries in `data`, excluding retired ones.             |
| `updatedAt`         | ISO 8601 UTC timestamp of the latest success, `null` before the first.  |
| `lastFailedAt`      | ISO 8601 UTC timestamp of the latest failure, `null` if none.           |
| `lastFailedMessage` | Exception type and the first 300 characters of it, or `null`.           |
| `data`              | Model objects of the latest success plus retired ones kept for history. |

Check `status` before using a list. A failed fetch keeps the models of the last success and
records the failure beside them, so a stale list and a current one look alike unless
`status` is read. `updatedAt` says how old the models are; `lastFailedAt` says whether the
latest attempt succeeded.

Files published before this wrapper existed hold a bare array. Treat a top-level array as the
older shape and read the list from `data`.

Every entry in `data` also carries five fields the writer adds:

| Field         | Meaning                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| `presence`    | `"active"` when the latest success listed it, `"removed"` when it dropped out and is kept for history. |
| `firstSeen`   | ISO 8601 UTC timestamp of the first fetch that listed it.                                              |
| `lastSeen`    | ISO 8601 UTC timestamp of the last success that listed it, frozen once removed.                        |
| `removedDate` | ISO 8601 UTC timestamp of the success that first found it missing, `null` while active.                |
| `status`      | Always `null`: the writer replaces whatever the provider returned.                                     |

Filter on `presence` to get the live catalogue, because `count` is the live total while the
array holds active and retired entries together. Retired entries are dropped once they are
90 days old, so churn does not grow a file without bound.

The remaining fields come from the provider, so their shape differs per provider:

- Entries are keyed by `id`, except `googleai`, which is keyed by `name`
  (`models/gemini-2.5-flash`).
- `rate_limits` appears only where a quota source covers that model, and its keys differ by
  provider: `googleai` uses `rpm`, `rpd` and `tpm`; `groq` uses `asd`, `ash`, `rpm`, `rpd`,
  `tpd` and `tpm`; `cerebras` uses `rpm`, `tpd`, `tph`, `total_tpm` and `uncached_tpm`;
  `mistral` uses `rps` and `tpm`; `zai` uses `concurrency`. A `null` inside one means
  unlimited or not shown, and a missing `rate_limits` means unknown, not unrestricted.

## Example

```python
import json
import urllib.request

url = "https://raw.githubusercontent.com/jn-s3s/zero-cost-llms/models-data/openrouter.json"

with urllib.request.urlopen(url) as response:
    payload = json.load(response)

if payload["status"] != "success":
    raise SystemExit("fetch failed: " + str(payload["lastFailedMessage"]))

for model in payload["data"]:
    if model["presence"] == "active":
        print(model["id"])
```

## Guarantees and limits

- The data is best-effort and moves at most once a day. There is no uptime or freshness
  guarantee, and a provider can change how it prices a model between runs.
- "Free" is decided per provider by that provider's own public signal, recorded in
  `config/providers.json` and listed in the repository README. It is not a contractual promise that
  a model stays free.
- Reading the published files needs no key and no rate-limit etiquette beyond ordinary
  politeness. Politeness matters here: 20 files fetched per consumer per day adds up.
- Providers are added and removed over time, so a fetch of an unknown id returns 404 rather
  than an empty list. Treat that as the provider being gone.

## Related

- [Repository](https://github.com/jn-s3s/zero-cost-llms) for how collection works
- [Contributing](https://github.com/jn-s3s/zero-cost-llms/blob/main/CONTRIBUTING.md)
- [Security policy](https://github.com/jn-s3s/zero-cost-llms/blob/main/SECURITY.md)
