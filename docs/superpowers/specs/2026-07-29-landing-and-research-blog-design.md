# Delphi Landing and Research Blog Design

## Purpose

Rebuild `trydelphi.ai` as a simple, distinctive public surface for Delphi:
cinematic enough to feel like Synthetic Sciences, precise enough to survive
technical scrutiny, and focused on what better context changes for real agent
work.

## Design Direction

The selected direction is **Delphi Field Notes**.

It combines the full-bleed, painterly pacing of `tryatlas.sh` and
`openscience.sh` with the editorial argument structure of serious research
labs. Delphi's existing `sacred-way` and `archive` artwork remains the visual
anchor. The design does not imitate another site's exact layout or components.

Rejected alternatives:

- a minimal launch memo would undersell the product and provide too little
  methodological context;
- a product-dashboard landing page would add interface chrome and animation
  without improving the central argument.

## Visual System

- Retain the existing Next.js, TypeScript, Tailwind, and local font stack.
- Use a near-black, warm ivory, oxidized gold, and muted stone palette.
- Use the existing serif face for display typography and a compact sans face
  for labels and measurement annotations.
- Build the homepage around two full-width images: `sacred-way` opens the
  narrative and `archive` closes it.
- Use hairline rules, large editorial numerals, generous vertical space, and
  restrained motion. Avoid rounded-card grids, gradients, floating pills, and
  generic startup illustrations.
- Respect `prefers-reduced-motion`, keyboard focus, semantic headings, and
  mobile reading widths.
- Preserve light/dark artwork parity where the existing paired images support
  it.

## Homepage Structure

### Navigation

Wordmark on the left. Links on the right:

- Product
- Results
- Blog
- Docs
- GitHub

The Blog link points to `/blog`. The primary action is "Install Delphi."

### Hero

The `sacred-way` image becomes a full-viewport opening field with a dark
readability veil. The copy is:

> The context engine for agents that have to get the code right.

Supporting copy describes Delphi as open-source, self-hosted infrastructure for
indexing, retrieving, and assembling code, documentation, papers, and datasets.
The primary CTA is the one-command install; the secondary CTA opens the
research article.

A compact evidence line states:

> 95.0% pass@1 in a fixed-model, 40-task developer pilot.

It does not say universal SOTA.

### Results

The results section is an editorial measurement spread rather than a dashboard:

- `95.0%` Delphi downstream pass@1;
- `90.0%` next-best tested condition;
- `1.25 s` mean query latency on the strict-valid retrieval subset;
- `21.3×` lower latency than the hosted repository comparator.

Directly beneath it, the methodology note says:

- fixed Claude Opus 5 across conditions;
- 40 DS-1000 development tasks;
- retrieval audit reduced 75 cases to 18 strict-valid cases because 57 targets
  were truncated;
- descriptive pilot, not a universal ranking;
- early-rank retrieval remains open work.

The section links to the full blog article.

### How Delphi Works

A five-stage horizontal narrative replaces generic feature cards:

1. Index immutable source versions.
2. Search through lexical, semantic, symbol, path, and structural branches.
3. Fuse and diversify evidence.
4. Assemble a token-bounded context pack with provenance.
5. Let the agent write and verify the change.

On narrow screens, the stages stack without horizontal scrolling.

### Timeline

A compact timeline mirrors the repository timeline:

- open-source MCP foundation;
- multi-source, local-first indexing;
- hybrid developer retrieval and context packs;
- July 2026 fixed-model developer pilot.

The final entry says "state of the art in the tested developer-work setting."

### Open Source and Install

Keep the one-command install and Apache-2.0 positioning. Explain self-hosting,
optional hosted embeddings, and data ownership without claiming that every
configuration requires zero credentials.

### Research Teaser and Closing

Introduce the field note with the benchmark-fidelity finding:

> Before asking who won retrieval, we had to ask whether the benchmark still
> contained the files it said it was scoring.

The `archive` artwork then closes the page with links to the blog, GitHub, docs,
and install command.

## Blog Information Architecture

### `/blog`

A quiet research index, not a marketing card grid. It contains one featured
entry, its date, reading time, abstract, methods labels, and a direct link.
The page is ready for future posts without adding a CMS.

### `/blog/context-engine-is-the-product`

Title:

> The context engine is the product

Subtitle:

> What a fixed-model developer benchmark taught us about retrieval, latency,
> corpus fidelity, and the difference between finding a file and helping an
> agent finish the work.

The article follows this structure:

1. **The result** — 95.0% vs 90.0% next-best tested condition.
2. **The benchmark broke before the engines did** — 57/75 truncated target
   files and the strict-valid 18-case retrieval subset.
3. **What we held fixed** — model, prompt family, task slice, and pass@1
   evaluation.
4. **Retrieval is not downstream correctness** — early-rank comparator wins,
   Delphi recall@20 point estimate, and the non-significant paired interval.
5. **Latency changes agent behavior** — 1.25 seconds vs 26.58 seconds and why
   iterative retrieval matters.
6. **What failed in Delphi** — early-rank relevance, metadata and corpus
   fidelity, and the limits of a small pilot.
7. **What changed in the product** — hybrid fusion, path-aware retrieval,
   stable diversity, context-pack assembly, provenance, and failure
   classification.
8. **What we can claim** — a boxed scope statement and explicit non-claims.
9. **Next evaluation** — larger held-out tasks, multiple model families,
   developer workflow studies, and a repaired public corpus.

The article uses native HTML/CSS figures:

- a 95 vs 90 outcome comparison;
- a 75-case corpus-fidelity diagram showing 57 excluded and 18 strict-valid;
- an early-rank versus deep-recall comparison;
- a latency comparison;
- a context-engine pipeline diagram.

No invented screenshots, citations, statistical significance, or results are
introduced. Specific competitor names do not appear.

## Metadata and Sharing

- Update homepage title, description, canonical URL, and Open Graph image copy.
- Add route-specific metadata for `/blog` and the article.
- Add a visible publication date and "Synthetic Sciences" byline.
- Use semantic `<article>`, `<header>`, `<nav>`, `<figure>`, and `<aside>`
  structure.

## Repository and Deployment Boundaries

The canonical production app is `landing/` in
`synthetic-sciences/delphi`. The stale standalone `delphi-landing` repository is
not changed.

No SynsciContextBench references remain in the landing app. Old memo, blog,
paper, and external report files remain untouched.

## Acceptance Criteria

- `/`, `/blog`, and `/blog/context-engine-is-the-product` build as static or
  server-rendered Next.js routes without runtime errors.
- The homepage contains the scoped results, methodology caveat, timeline,
  install path, and Blog navigation.
- The article contains all nine sections and five evidence figures.
- Search across `landing/` finds no SynsciContextBench references.
- All internal links resolve; external links point to canonical Delphi,
  documentation, and license destinations.
- Layout works at 390 px, 768 px, and 1440 px widths with no horizontal
  overflow.
- Reduced-motion and keyboard-focus behavior remain usable.
- `pnpm build` and the repository landing CI smoke test pass.
