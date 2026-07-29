import type { Metadata } from "next";
import Link from "next/link";
import { ArticleHeader } from "@/components/ArticleHeader";
import {
  CorpusAuditFigure,
  LatencyFigure,
  OutcomeFigure,
  PipelineFigure,
  RetrievalFigure,
} from "@/components/EvidenceFigure";
import { ScopeStatement } from "@/components/ScopeStatement";
import { TraceGallery } from "@/components/TraceGallery";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteNav } from "@/components/SiteNav";
import { ARTICLE, RETRIEVAL_AUDIT } from "@/lib/evidence";

export const metadata: Metadata = {
  title: `${ARTICLE.title} · Delphi`,
  description: ARTICLE.dek,
  alternates: {
    canonical: `https://trydelphi.ai${ARTICLE.href}`,
  },
  openGraph: {
    title: ARTICLE.title,
    description: ARTICLE.dek,
    type: "article",
    url: `https://trydelphi.ai${ARTICLE.href}`,
    publishedTime: ARTICLE.publishedIso,
    authors: ["Synthetic Sciences"],
  },
};

const SECTIONS = [
  ["result", "The result"],
  ["fidelity", "The benchmark broke first"],
  ["fixed", "What we held fixed"],
  ["retrieval", "Retrieval is not correctness"],
  ["latency", "Latency changes behavior"],
  ["failures", "What failed in Delphi"],
  ["product", "What changed in the product"],
  ["claim", "What we can claim"],
  ["next", "Next evaluation"],
  ["traces", "Open the evidence"],
] as const;

export default function ContextEngineArticle() {
  return (
    <>
      <SiteNav />
      <main>
        <ArticleHeader />

        <div className="mx-auto grid w-full max-w-[1240px] gap-16 px-5 py-16 sm:px-8 md:py-24 lg:grid-cols-[220px_minmax(0,760px)] lg:justify-between">
          <aside className="hidden lg:block">
            <nav
              aria-label="Article contents"
              className="sticky top-28 border-t border-[var(--line-strong)] pt-5"
            >
              <p className="eyebrow text-[var(--fg-mute)]">Contents</p>
              <ol className="mt-5 space-y-3">
                {SECTIONS.map(([id, title], index) => (
                  <li key={id}>
                    <Link
                      className="grid grid-cols-[28px_1fr] gap-2 text-[12px] leading-5 text-[var(--fg-mute)] transition-colors hover:text-[var(--gold)]"
                      href={`#${id}`}
                    >
                      <span className="font-mono text-[9px]">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span>{title}</span>
                    </Link>
                  </li>
                ))}
              </ol>
            </nav>
          </aside>

          <article className="article-prose min-w-0">
            <p className="mt-0 text-[1.2em] leading-[1.7] text-[var(--fg-strong)]">
              Context engines are usually benchmarked as retrievers. A query
              goes in; ranked chunks come out; a metric decides whether the
              right file appeared near the top. That is useful. It is also
              incomplete. The user does not experience a ranked list. The user
              experiences whether an agent understood the task, found the
              evidence, wrote working code, and did it quickly enough to keep
              iterating.
            </p>

            <p>
              We reran Delphi from that end of the chain. We held the language
              model fixed, changed the context condition, and scored the code
              that actually executed. Then we audited the retrieval benchmark
              we intended to use as an explanation. The audit changed the
              story: Delphi won the developer pilot, lost several early-rank
              retrieval metrics, and exposed a corpus problem large enough to
              invalidate most of the planned retrieval comparison.
            </p>

            <h2 id="result">The result</h2>
            <p>
              On a 40-task development slice of{" "}
              <Link href="https://ds1000-code-gen.github.io/">
                DS-1000
              </Link>
              , Delphi full context reached <strong>95.0% pass@1</strong>. The
              next-best tested condition reached <strong>90.0%</strong>. The
              model—Claude Opus 5—was fixed across conditions, as were the task
              prompts and execution-based scoring path.
            </p>

            <OutcomeFigure />

            <p>
              Two mistakes are easy to make here. The first is to treat five
              percentage points on 40 tasks as a universal ranking. The second
              is to dismiss the result because the slice is small. We do
              neither. It is a descriptive pilot with a meaningful product
              signal: under a fixed capable model, the context condition
              changed which programs passed.
            </p>

            <h2 id="fidelity">The benchmark broke before the engines did</h2>
            <p>
              We planned a 75-query repository-retrieval comparison. Before
              scoring, we checked whether each target file named by the
              benchmark existed, in scoreable form, in each indexed corpus.
              Fifty-seven did not. The available copies were truncated at the
              exact files the benchmark expected the engine to retrieve.
            </p>

            <CorpusAuditFigure />

            <p>
              Scoring all 75 anyway would have produced a clean table and a
              false conclusion. A system cannot retrieve bytes that were never
              indexed. More subtly, corpus damage can favor one engine over
              another when their ingestion paths reconstruct or omit content
              differently. We therefore reduced the strict comparison to the
              18 cases whose scored targets existed on both sides.
            </p>

            <p>
              This was not a provider-availability artifact: the hosted
              repository condition completed all 75 queries without a provider
              failure. The exclusion is about target fidelity, not uptime.
            </p>

            <h2 id="fixed">What we held fixed</h2>
            <p>
              The downstream experiment asks a deliberately narrow causal
              question: when the model and tasks stay fixed, does changing the
              supplied context change executable correctness?
            </p>

            <ul>
              <li>
                <strong>Model:</strong> Claude Opus 5 for every developer-work
                condition, using the same generation path.
              </li>
              <li>
                <strong>Tasks:</strong> the same 40 DS-1000 development
                problems, scored by their execution tests.
              </li>
              <li>
                <strong>Outcome:</strong> pass@1—one generated answer, counted
                only when the program satisfies the benchmark.
              </li>
              <li>
                <strong>Changed variable:</strong> the context available to the
                model before it wrote the solution.
              </li>
            </ul>

            <p>
              DS-1000 contains realistic data-science questions across seven
              Python libraries and uses execution plus surface-form constraints.
              It is a useful test of API grounding. It is not a complete
              simulation of repository-scale software engineering, and our
              40-task development slice is not its full thousand-task suite.
            </p>

            <h2 id="retrieval">Retrieval is not downstream correctness</h2>
            <p>
              On the 18 strict-valid repository cases, the hosted comparator
              led Delphi on MRR, recall@5, recall@10, and budgeted context yield.
              Delphi&apos;s point estimate moved ahead only at recall@20:
              0.667 versus 0.639.
            </p>

            <RetrievalFigure />

            <p>
              Even that late-recall difference is not evidence of superiority.
              The paired recall@20 delta was +0.028 with a 95% interval of{" "}
              {RETRIEVAL_AUDIT.recall20Ci}. The interval crosses zero. The
              honest reading is that Delphi reaches useful evidence deeper in
              the result set while the comparator ranks the first useful result
              better. The sample is too small to say more.
            </p>

            <p>
              Why, then, did Delphi lead downstream? Retrieval metrics observe
              file discovery. Developer work also depends on how chunks are
              expanded, whether an enclosing body is reconstructed, whether
              tests and imports arrive together, how duplicates spend the
              context budget, and whether the final evidence is legible to the
              model. A context engine can lose MRR and still provide a better
              working set. The reverse is also possible.
            </p>

            <h2 id="latency">Latency changes agent behavior</h2>
            <p>
              Delphi&apos;s mean query latency on the strict-valid subset was
              1.25 seconds. The hosted repository comparator averaged 26.58
              seconds. That is a 21.3× difference in the observed query path.
            </p>

            <LatencyFigure />

            <p>
              Latency is not a decorative systems metric. Agents retrieve in
              loops. They ask a broad question, inspect an answer, follow a
              symbol, pull a file, then revise the plan. At 1.25 seconds, a
              five-query investigation costs roughly the time of one slow
              request. At 26.58 seconds, the same loop changes how aggressively
              the agent explores—or whether it explores at all.
            </p>

            <p>
              The comparison does not make the systems operationally
              equivalent: one is self-hosted and one is a hosted API. It does
              show why context quality cannot be reduced to ranking quality.
              The usable product lives on a quality–latency frontier.
            </p>

            <h2 id="failures">What failed in Delphi</h2>
            <p>
              The run gave us three failure classes worth keeping visible.
            </p>

            <h3>Early-rank relevance</h3>
            <p>
              Delphi&apos;s broad hybrid retrieval preserves candidates, but
              the first few ranks can spend too much weight on semantic
              similarity or branch agreement. For a human scanning five hits,
              that is a quality regression even if the target appears at rank
              twelve. Better late recall does not excuse worse first contact.
            </p>

            <h3>Corpus identity</h3>
            <p>
              A benchmark target is meaningful only against a specified source
              version. Repository name and commit metadata are not enough when
              an ingestion path can truncate, transform, or skip the target.
              The scored bytes need a content identity, and the evaluation
              needs to verify it before ranking systems.
            </p>

            <h3>Pilot size</h3>
            <p>
              Forty tasks can find a product bug or a promising direction. It
              cannot establish broad leadership across languages, model
              families, repositories, or long-running agent workflows. We are
              publishing the number because it changes what we should test
              next, not because it ends the evaluation.
            </p>

            <h2 id="product">What changed in the product</h2>
            <p>
              The failures reinforce a particular architecture for Delphi. The
              retrieval layer now has to be judged as one part of an auditable
              context pipeline:
            </p>

            <PipelineFigure />

            <p>
              In practical terms, Delphi combines vector retrieval with BM25,
              exact-symbol, exact-path, and trigram branches; fuses them with
              stable file diversity; and exposes the branches that surfaced
              each result. Context packs then expand a hit into enclosing
              bodies, adjacent chunks, imports, linked tests, documentation,
              examples, and configuration under a token budget.
            </p>

            <p>
              Source snapshots make the indexed version explicit. Freshness
              checks distinguish a retrieval miss from a stale index. Failure
              classification gives us a stable way to record whether a bad
              answer came from absence, ranking, assembly, model reasoning, or
              evaluation. None of these guarantees a correct agent. Together,
              they make a failure inspectable.
            </p>

            <h2 id="claim">What we can claim</h2>
            <ScopeStatement />
            <p>
              The phrase “state of the art” is useful only when the state and
              the art are named. Here, the state is a fixed-model DS-1000
              development pilot. The art is downstream executable correctness
              with a context engine in the loop. Change the task distribution,
              model, context budget, or operational envelope and the ranking
              may change.
            </p>

            <h2 id="next">Next evaluation</h2>
            <p>
              The next round should make the claim harder to earn and easier to
              reproduce:
            </p>

            <ul>
              <li>
                run a larger held-out developer slice instead of extending the
                development set until the number looks good;
              </li>
              <li>
                repeat the fixed-context comparison across multiple model
                families and capability levels;
              </li>
              <li>
                publish a repaired, content-addressed repository corpus with
                preflight fidelity checks;
              </li>
              <li>
                report uncertainty for paired downstream outcomes and
                retrieval metrics;
              </li>
              <li>
                measure multi-query agent workflows—correctness, elapsed time,
                context spend, and recovery after a bad first retrieval.
              </li>
            </ul>

            <p>
              The central bet behind Delphi is straightforward: context engines
              should be evaluated by the work they enable, with retrieval,
              assembly, latency, and source fidelity available as explanations.
              A leaderboard is useful. A system that can tell you why the agent
              succeeded—or why it failed—is the product.
            </p>

            <h2 id="traces">Open the evidence</h2>

            <p>
              Every number above comes from queries that were recorded in
              full. Below are real traces from the benchmarked build, two per
              workflow, taken by position in the split rather than picked for
              how they turned out. Expand one to see the exact query the engine
              received, the ranked files it returned, which retrieval branch
              found each one, and the raw response record.
            </p>

            <p>
              They are worth reading for the failures as much as the hits. The
              first <code>code2test</code> trace puts changelog files above the
              regression test it was asked for: the query mentions a version
              bump, changelogs are dense with version strings, and BM25 has no
              way to know that a changelog can never be an answer to “which
              test covers this?”. That is a live weakness, not a rounding
              error.
            </p>

            <TraceGallery />

            <div className="mt-20 border-t border-[var(--line-strong)] pt-7">
              <p className="eyebrow text-[var(--fg-mute)]">References</p>
              <ol className="mt-5 space-y-3 text-[13px] leading-6 text-[var(--fg-mute)]">
                <li>
                  1. Lai et al.,{" "}
                  <Link href="https://arxiv.org/abs/2211.11501">
                    “DS-1000: A Natural and Reliable Benchmark for Data Science
                    Code Generation”
                  </Link>
                  .
                </li>
                <li>
                  2. Anthropic,{" "}
                  <Link href="https://platform.claude.com/docs/en/about-claude/models/overview">
                    Claude model overview
                  </Link>
                  .
                </li>
                <li>
                  3. Synthetic Sciences,{" "}
                  <Link href="https://github.com/synthetic-sciences/delphi">
                    Delphi source and implementation documentation
                  </Link>
                  .
                </li>
              </ol>
            </div>
          </article>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
