# Security Policy

## Reporting

Use the repository's Security tab and select "Report a vulnerability" to send a
private GitHub Security Advisory. If that is unavailable, email
jn.s3s.github@gmail.com. Report a leaked provider API key privately. Do not open
a public issue for a key leak, and do not include the key in the report.

Include the affected file or provider, what you observed, the likely impact,
and steps to reproduce with sensitive values removed. For a leaked key, include
where it was exposed and when you found it, but not the key itself. Reports will
be reviewed and followed up as volunteer time permits; no response or fix time
is guaranteed.

## Scope

Security reports include exposure of provider credentials stored in a local
`.env` file or accidentally saved in committed `data_templates/*.html` captures.
The daily workflow supplies provider keys through repository secrets, so a
possible leak through the fetch or publish path is also relevant. Report a
provider being classified as free when it now serves paid models, especially if
the published `models-data` catalogue could lead consumers to incur charges.
Vulnerabilities in shared HTTP or scraping code are also in scope.

Provider outages and stale rate-limit snapshots are ordinary bugs, not security
reports. Problems in third-party provider APIs are outside this project's
scope; report those to the provider.
