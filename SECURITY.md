# Security Policy

Delphi indexes source material, stores credentials for optional providers, and
exposes tools to AI agents. We take reports about authorization boundaries,
secret handling, data isolation, dependency vulnerabilities, and unsafe source
processing seriously.

## Supported Versions

| Version | Supported |
| --- | --- |
| `master` and the latest published release | Yes |
| Older releases and historical commits | Best effort |

Security fixes are made against `master` first and are included in the next
available release. We may provide a backport when the affected deployment is
widely used and a safe backport is practical.

## Reporting a Vulnerability

Please report vulnerabilities privately:

1. Use [GitHub private vulnerability
   reporting](https://github.com/synthetic-sciences/delphi/security/advisories/new)
   for this repository.
2. If that is unavailable, email
   [hello@syntheticsciences.ai](mailto:hello@syntheticsciences.ai).
3. Do not open a public issue before a fix or coordinated disclosure.

Include the affected version or commit, deployment configuration, impact,
reproduction steps, and any proof-of-concept material that can be shared
safely. Remove API keys, access tokens, personal data, and proprietary source
content from the report.

We aim to acknowledge a report within three business days. For validated
reports, we will share status updates as we investigate, develop a fix, and
coordinate disclosure. Remediation time depends on severity, exploitability,
and the complexity of a safe fix.

## Disclosure

We ask reporters to give the project a reasonable opportunity to investigate
and remediate before public disclosure. We will credit reporters who want to be
credited and will coordinate the timing and content of an advisory when
appropriate.

Good-faith research that follows this policy, avoids privacy violations and
service disruption, and does not access more data than necessary will be
treated as authorized security research by the project.
