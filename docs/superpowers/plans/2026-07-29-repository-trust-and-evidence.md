# Repository Trust and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Delphi's public governance policies and a scoped, reproducible evidence summary to the main README.

**Architecture:** Keep the governance policies as conventional root Markdown files so GitHub discovers them automatically. Add a compact evidence section near the README introduction while preserving the existing quick start and technical reference.

**Tech Stack:** GitHub-flavored Markdown, shell validation with `rg`, Git

## Global Constraints

- Do not commit raw benchmark artifacts.
- Do not modify old memos, blogs, research reports, or paper drafts.
- Do not name tested competitors in the new evidence block.
- Qualify every SOTA statement as "in the tested developer-work setting."
- Do not add a SynsciContextBench reference.
- Target the repository's canonical `master` branch.

---

### Task 1: Repository governance policies

**Files:**
- Create: `CODE_OF_CONDUCT.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: existing development commands from `README.md` and package manifests
- Produces: GitHub-discoverable community health files

- [ ] **Step 1: Write the policy files**

Use Contributor Covenant 2.1 in `CODE_OF_CONDUCT.md`, ending with:

```markdown
Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the project team at hello@syntheticsciences.ai.
```

Use this disclosure hierarchy in `SECURITY.md`:

```markdown
1. Use GitHub's private vulnerability reporting for this repository.
2. If that is unavailable, email hello@syntheticsciences.ai.
3. Do not open a public issue before a fix or coordinated disclosure.
```

In `CONTRIBUTING.md`, include exact validation commands for:

```bash
cd backend && uv sync --locked --extra dev
uv run ruff check synsc tests
uv run mypy synsc
uv run pytest -q
cd ../frontend && npm ci && npm run lint && npm run build
cd ../landing && corepack enable && pnpm install --frozen-lockfile && pnpm build
```

- [ ] **Step 2: Validate contacts, links, and placeholders**

Run:

```bash
rg -n 'T[B]D|T[O]DO|example\.com|your.email|SynsciContextBench' \
  CODE_OF_CONDUCT.md SECURITY.md CONTRIBUTING.md
```

Expected: no matches.

- [ ] **Step 3: Validate Markdown whitespace**

Run:

```bash
git diff --check
```

Expected: exit code 0.

- [ ] **Step 4: Commit the policies**

```bash
git add CODE_OF_CONDUCT.md SECURITY.md CONTRIBUTING.md
git commit -m "docs: add community health policies"
```

### Task 2: Scoped benchmark results and timeline

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: fixed benchmark record in `docs/superpowers/specs/2026-07-29-repository-trust-and-evidence-design.md`
- Produces: public evidence block and blog link used by contributors and readers

- [ ] **Step 1: Add the evidence block after “What is Delphi?”**

The lead statement must be exactly scoped:

```markdown
In a fixed-model, 40-task developer pilot, Delphi produced the strongest tested
downstream result: **95.0% pass@1**, compared with **90.0%** for the next-best
tested condition. This is state-of-the-art performance in the tested
developer-work setting, not a claim of universal context-engine superiority.
```

Add rows for DS-1000 pass@1, strict-valid ARB mean query latency, and
strict-valid ARB recall@20. Include the 57/75 truncation disclosure and the
non-significant recall@20 confidence interval.

- [ ] **Step 2: Add the four-entry timeline**

Use a compact Markdown table with these milestones:

```text
2026-07-29 — 95.0% pass@1 in the fixed-model developer pilot
2026-07-29 — 1.25 s strict-valid mean query latency
2026-07-29 — corpus-fidelity audit excludes 57 truncated targets
Open source — local-first MCP context engine under Apache 2.0
```

The dated entries must say what was measured rather than imply feature release
dates.

- [ ] **Step 3: Add the research article link**

Link the methodology sentence to:

```text
https://trydelphi.ai/blog/context-engine-is-the-product
```

- [ ] **Step 4: Validate claim language**

Run:

```bash
rg -n -i 'state.of.the.art|sota|95\.0|90\.0|57 of 75|18 strict' README.md
rg -n 'Nia|Context7|SynsciContextBench' README.md
```

Expected: the first command finds the scoped evidence; the second finds no new
competitor or removed-benchmark references.

- [ ] **Step 5: Review and commit**

Run:

```bash
git diff --check
git diff -- README.md
```

Then:

```bash
git add README.md
git commit -m "docs: publish scoped developer benchmark results"
```

### Task 3: Pull request verification and merge

**Files:**
- Verify: `README.md`
- Verify: `CODE_OF_CONDUCT.md`
- Verify: `SECURITY.md`
- Verify: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: Tasks 1–2 commits
- Produces: merged repository-trust PR on `master`

- [ ] **Step 1: Verify the branch**

Run:

```bash
git status --short
git diff --check origin/master...HEAD
rg -n 'SynsciContextBench|Nia|Context7' \
  README.md CODE_OF_CONDUCT.md SECURITY.md CONTRIBUTING.md
```

Expected: clean status, no whitespace errors, no matches from the final search.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin codex/repository-trust-benchmarks
gh pr create --base master --head codex/repository-trust-benchmarks \
  --title "Add repository policies and scoped benchmark results" \
  --body-file /tmp/delphi-repository-pr.md
```

The PR body must list the evidence scope and state that raw results are not
included.

- [ ] **Step 3: Wait for required checks**

Run:

```bash
gh pr checks --watch
```

Expected: every required check passes.

- [ ] **Step 4: Squash merge**

```bash
gh pr merge --squash --delete-branch
```

Expected: the PR is merged into `master`.
