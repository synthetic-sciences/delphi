# Landing and Research Blog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Delphi's old benchmark-centric landing page with a cinematic product narrative and a native, evidence-led research blog.

**Architecture:** Keep the existing Next.js App Router application and split the redesign into reusable editorial components, immutable benchmark data, and three routes: `/`, `/blog`, and `/blog/context-engine-is-the-product`. Reuse Delphi's existing theme-paired artwork and implement all figures in semantic HTML/CSS.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Tailwind CSS 4, `next/image`, `next/font`

## Global Constraints

- Work only in the monorepo `landing/` app; do not update the stale standalone repository.
- Do not add dependencies, a CMS, client analytics, or runtime data fetching.
- Do not modify old memos, blog files, research reports, or paper drafts.
- Do not name tested competitors.
- Do not include a SynsciContextBench reference.
- Qualify the 95.0% result as a fixed-model, 40-task descriptive pilot.
- Respect reduced motion, keyboard focus, semantic structure, and 390 px mobile width.

---

### Task 1: Shared evidence model and editorial primitives

**Files:**
- Create: `landing/src/lib/evidence.ts`
- Create: `landing/src/components/SiteNav.tsx`
- Create: `landing/src/components/SiteFooter.tsx`
- Create: `landing/src/components/InstallCommand.tsx`
- Create: `landing/src/components/EvidenceFigure.tsx`
- Modify: `landing/src/app/globals.css`

**Interfaces:**
- Produces: `DEVELOPER_PILOT`, `RETRIEVAL_AUDIT`, `TIMELINE`, `ARTICLE`
- Produces: `SiteNav({ mode?: "overlay" | "solid" })`
- Produces: `SiteFooter()`, `InstallCommand({ compact?: boolean })`
- Produces: `OutcomeFigure()`, `CorpusAuditFigure()`, `RetrievalFigure()`, `LatencyFigure()`, `PipelineFigure()`

- [ ] **Step 1: Create immutable evidence constants**

Define:

```ts
export const DEVELOPER_PILOT = {
  tasks: 40,
  model: "Claude Opus 5",
  delphiPassAtOne: 95.0,
  nextBestPassAtOne: 90.0,
} as const;

export const RETRIEVAL_AUDIT = {
  attempted: 75,
  strictValid: 18,
  excludedTruncated: 57,
  delphiLatencySeconds: 1.25,
  comparatorLatencySeconds: 26.58,
  latencyRatio: 21.3,
  delphiRecall20: 0.667,
  comparatorRecall20: 0.639,
  recall20Ci: "[-0.094, 0.139]",
} as const;
```

Export the article slug, title, dek, publication date, and reading time from
the same file so metadata and links cannot drift.

- [ ] **Step 2: Create shared navigation and footer**

`SiteNav` must link to `/#product`, `/#results`, `/blog`, the README
documentation, and GitHub. `SiteFooter` must link to `/blog`, GitHub, Apache
2.0, and `mailto:hello@syntheticsciences.ai`.

- [ ] **Step 3: Create semantic evidence figures**

Each figure uses `<figure>`, `<figcaption>`, visible numeric labels, and CSS
bars or grids. No chart library or canvas is used. The corpus figure renders
75 small cells, with 57 visually marked excluded and 18 marked strict-valid.

- [ ] **Step 4: Establish the editorial CSS system**

Add named component classes for:

```css
.display-title
.eyebrow
.measure
.hairline-grid
.hero-veil
.article-prose
.evidence-figure
.focus-ring
```

Define warm-gold tokens and `:focus-visible`. Under
`@media (prefers-reduced-motion: reduce)`, disable nonessential transitions and
transforms.

- [ ] **Step 5: Type-check through a production build**

Run:

```bash
cd landing
pnpm build
```

Expected: build succeeds.

- [ ] **Step 6: Commit shared foundations**

```bash
git add landing/src/lib/evidence.ts landing/src/components \
  landing/src/app/globals.css
git commit -m "feat(landing): add editorial evidence system"
```

### Task 2: Cinematic homepage

**Files:**
- Modify: `landing/src/app/page.tsx`
- Create: `landing/src/components/HomeHero.tsx`
- Create: `landing/src/components/ResultsSpread.tsx`
- Create: `landing/src/components/ContextPipeline.tsx`
- Create: `landing/src/components/ProductTimeline.tsx`
- Create: `landing/src/components/OpenSourceInstall.tsx`
- Create: `landing/src/components/ResearchTeaser.tsx`
- Modify: `landing/src/components/HeroImage.tsx`

**Interfaces:**
- Consumes: shared evidence constants and shared site components from Task 1
- Produces: the complete `/` route with anchors `product`, `results`, and `install`

- [ ] **Step 1: Turn `sacred-way` into the full-viewport hero**

`HomeHero` renders `SiteNav` over the image, the headline:

```text
The context engine for agents that have to get the code right.
```

and the visible measurement:

```text
95.0% pass@1 · fixed model · 40 developer tasks
```

The primary CTA links to `#install`; the secondary CTA links to
`/blog/context-engine-is-the-product`.

- [ ] **Step 2: Build the results spread**

Render 95.0%, 90.0%, 1.25 s, and 21.3× as large editorial measurements.
Include the 18/75 strict-valid disclosure and the early-rank limitation in
ordinary body text directly below the measurements.

- [ ] **Step 3: Build the five-stage context pipeline**

Render:

```ts
[
  ["01", "Index", "Immutable source versions"],
  ["02", "Retrieve", "Semantic, lexical, symbol, path, structural"],
  ["03", "Fuse", "Rank and diversify evidence"],
  ["04", "Assemble", "Token-bounded context with provenance"],
  ["05", "Act", "Write and verify the change"],
]
```

The mobile layout stacks; desktop uses a ruled five-column sequence.

- [ ] **Step 4: Add timeline, install, and research teaser**

The final timeline entry includes the full scoped phrase "state of the art in
the tested developer-work setting." The install section renders
`npx @synsci/delphi`. The research teaser leads with the 57/75 fidelity
finding.

- [ ] **Step 5: Use `archive` as the closing visual**

Update `HeroImage.tsx` so the closing image can carry overlaid copy and links
without duplicating the theme-paired image logic.

- [ ] **Step 6: Replace the homepage composition**

`page.tsx` imports only the new homepage sections and shared footer. Delete old
homepage-only components after confirming no route imports them.

- [ ] **Step 7: Build and commit**

Run:

```bash
cd landing && pnpm build
```

Then:

```bash
git add landing/src
git commit -m "feat(landing): rebuild Delphi homepage"
```

### Task 3: Native research blog

**Files:**
- Create: `landing/src/app/blog/page.tsx`
- Create: `landing/src/app/blog/context-engine-is-the-product/page.tsx`
- Create: `landing/src/components/ArticleHeader.tsx`
- Create: `landing/src/components/ScopeStatement.tsx`

**Interfaces:**
- Consumes: `ARTICLE` and evidence figures from Task 1
- Produces: `/blog` and `/blog/context-engine-is-the-product`

- [ ] **Step 1: Create the blog index**

Render one featured entry with title, dek, date, reading time, labels
`Evaluation`, `Retrieval`, and `Developer agents`, and a direct article link.
Do not create empty category pages or fake future posts.

- [ ] **Step 2: Add route metadata**

Use Next.js `Metadata` exports with canonical URLs:

```text
https://trydelphi.ai/blog
https://trydelphi.ai/blog/context-engine-is-the-product
```

- [ ] **Step 3: Write the nine-section article**

Use the section order in the design spec. The claim box must say:

```text
Delphi is state of the art in this tested developer-work setting: a fixed
Claude Opus 5 model on a 40-task DS-1000 development pilot. We do not claim
universal retrieval superiority, statistical significance from this pilot, or
leadership on every retrieval metric.
```

Include all five evidence figures next to the sections they support.

- [ ] **Step 4: Add citations and methodology links**

Link DS-1000 to its official repository or paper, Claude Opus 5 to the official
model documentation, and Delphi methods to the canonical repository. Do not
cite benchmark artifacts that are not public.

- [ ] **Step 5: Build and commit**

Run:

```bash
cd landing && pnpm build
```

Then:

```bash
git add landing/src/app/blog landing/src/components
git commit -m "feat(landing): publish Delphi research field note"
```

### Task 4: Metadata, cleanup, and responsive verification

**Files:**
- Modify: `landing/src/app/layout.tsx`
- Modify: `landing/src/app/opengraph-image.tsx`
- Delete: old homepage components no longer imported

**Interfaces:**
- Consumes: the final routes from Tasks 2–3
- Produces: canonical metadata and a clean production app

- [ ] **Step 1: Update site metadata**

Set `metadataBase` to `https://trydelphi.ai` and use the homepage headline in
Open Graph and Twitter descriptions. Update the generated OG image footer to
`trydelphi.ai`.

- [ ] **Step 2: Remove obsolete components and references**

Run:

```bash
rg -n 'SynsciContextBench|delphi\.syntheticsciences\.ai|Benchmarks' landing/src
```

Delete obsolete components after confirming no imports. Expected final search:
no matches for the first two patterns.

- [ ] **Step 3: Verify routes in production mode**

Run:

```bash
cd landing
pnpm build
pnpm start --hostname 127.0.0.1
```

In another shell:

```bash
for route in / /blog /blog/context-engine-is-the-product; do
  curl --fail --silent --show-error "http://127.0.0.1:3000$route" >/dev/null
done
```

Expected: every route returns success.

- [ ] **Step 4: Verify responsive screenshots**

Inspect all three routes at 390×844, 768×1024, and 1440×1000. Confirm no
horizontal overflow, clipped labels, unreadable image text, or hidden keyboard
focus.

- [ ] **Step 5: Commit final metadata and cleanup**

```bash
git add -A landing
git commit -m "chore(landing): finish metadata and obsolete-content cleanup"
```

### Task 5: Pull request, CI, merge, and production verification

**Files:**
- Verify: all changed files under `landing/`

**Interfaces:**
- Consumes: Tasks 1–4
- Produces: merged website PR and successful production deployment

- [ ] **Step 1: Run final local gates**

Run:

```bash
git diff --check origin/master...HEAD
rg -n 'SynsciContextBench|Nia|Context7' landing
cd landing && pnpm audit --prod && pnpm build
```

Expected: no forbidden-name matches, no audit failure, successful build.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin codex/delphi-landing-field-notes
gh pr create --base master --head codex/delphi-landing-field-notes \
  --title "Rebuild the Delphi landing page and research blog" \
  --body-file /tmp/delphi-landing-pr.md
```

- [ ] **Step 3: Wait for CI and preview deployment**

Run:

```bash
gh pr checks --watch
```

Expected: landing build, repository CI, and Vercel preview pass.

- [ ] **Step 4: Squash merge and inspect production**

```bash
gh pr merge --squash --delete-branch
```

Wait for the production deployment on the merge commit, then check `/`,
`/blog`, and `/blog/context-engine-is-the-product` at `https://trydelphi.ai`.

