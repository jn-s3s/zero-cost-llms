## Observable change

Describe what changes in the published free-model list, rate limits or provider status.

## Provider ids

List the affected ids from `providers.json`, or state that none were changed.

## Verification

List the commands run, including `uv run python fetch_models.py --provider <id>` when
applicable. Give the top-level `status` from each affected `data/<id>.json` and any relevant
output. An exit code of `0` alone does not mean the provider succeeded.

## Submission checks

- [ ] I formatted every changed file using the repository commands.
- [ ] For a new keyed provider, I added the workflow `env:` entry, matching repository secret
      and `.env.example` placeholder, or this is not applicable.
- [ ] I did not commit generated `data/` files.
