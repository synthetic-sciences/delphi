# Delphi Repository Trust and Evidence Design

## Purpose

Make the Delphi repository easier to trust, evaluate, and contribute to without
turning the README into a paper or publishing raw benchmark artifacts.

## Scope

This work changes only the public repository surface:

- add a code of conduct, security policy, and contributor guide;
- add a compact product timeline to the main README;
- publish the latest benchmark findings with explicit experimental scope;
- link the repository and the public website to the same methodology language.

The old memos, research reports, paper drafts, and benchmark output files remain
untouched. Raw benchmark results are not committed.

## Evidence and Claim Rules

The strongest supported public claim is:

> Delphi is state of the art in the tested developer-work setting.

That claim is limited to a fixed-model, 40-task DS-1000 pilot in which Delphi
full-context retrieval reached 95.0% pass@1 and the next-best tested condition
reached 90.0%. It must never be shortened to an unqualified universal SOTA
claim.

The public evidence block reports:

| Measurement | Delphi | Next-best tested condition | Interpretation |
| --- | ---: | ---: | --- |
| DS-1000 dev40 pass@1 | 95.0% | 90.0% | Fixed Claude Opus 5; 40-task descriptive pilot |
| Strict-valid ARB mean query latency | 1.25 s | 26.58 s | 18 comparable cases; 21.3× lower |
| Strict-valid ARB recall@20 | 0.667 | 0.639 | Point estimate only; paired confidence interval crosses zero |

The README must also disclose that 57 of 75 ARB cases had truncated scored
target files, leaving 18 strict-valid cases. Early-ranking metrics are not
presented as wins: the hosted comparator led MRR, recall@5, recall@10, and
budgeted context yield in that subset.

Competitors are described as "next-best tested condition" or "hosted repository
comparator." Specific competitor names do not appear in the new results block.

## README Information Architecture

The existing quick start and technical reference remain intact. A new section
appears after the opening product description:

1. **Latest results** — one restrained, high-signal statement and a three-row
   evidence table.
2. **Timeline** — four dated milestones showing the path from open-source MCP
   server to measured developer-work performance.
3. **Method note** — the model lock, task count, strict-valid subset, and
   limitations in plain language.
4. **Research link** — a link to
   `https://trydelphi.ai/blog/context-engine-is-the-product`.

The timeline follows the compact release-history pattern used by technical
research repositories: date, milestone, and one consequence per row. It does
not imply that every Delphi feature was introduced on the benchmark date.

## Governance Files

### Code of Conduct

Use Contributor Covenant 2.1 language. Set the enforcement contact to
`hello@syntheticsciences.ai`. The policy must cover project spaces and
officially represented public spaces.

### Security Policy

Direct vulnerability reports to GitHub private vulnerability reporting first,
with `hello@syntheticsciences.ai` as the fallback. Ask reporters not to open
public issues. Promise acknowledgement targets rather than guaranteed fixes:
three business days for acknowledgement and ongoing status updates for
validated reports.

The supported-version table covers the latest release line and `master`.

### Contributing Guide

Document:

- the Docker and manual development paths already present in the repository;
- backend, frontend, landing, CLI, and MCP proxy validation commands;
- focused pull requests and conventional, descriptive commit messages;
- the private security-reporting route;
- an evidence rule for new benchmark or performance claims;
- the Apache-2.0 contribution license expectation.

No CLA, DCO, or new governance mechanism is invented.

## Acceptance Criteria

- The three governance files render correctly on GitHub and contain no
  placeholder contacts.
- README numbers match the fixed benchmark record above.
- Every SOTA claim includes its developer-work scope nearby.
- The limitations paragraph is visible without opening a separate artifact.
- No raw benchmark output, secret, competitor name, SynsciContextBench
  reference, old memo, blog, or paper file is added or modified.

