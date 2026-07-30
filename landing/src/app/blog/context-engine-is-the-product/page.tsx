import type { Metadata } from "next";
import Link from "next/link";
import { ArticleHeader } from "@/components/ArticleHeader";
import {
  AblationFigure,
  ComparisonFigure,
  MismatchFigure,
  PipelineFigure,
  RerankerFigure,
} from "@/components/EvidenceFigure";
import { HeadlineResults } from "@/components/HeadlineResults";
import { ScopeStatement } from "@/components/ScopeStatement";
import { TraceGallery } from "@/components/TraceGallery";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteNav } from "@/components/SiteNav";
import {
  ARTICLE,
  BENCHMARK,
  EMBEDDING_MISMATCH,
  HEAD_TO_HEAD,
  HELD_OUT,
  HELD_OUT_WORKFLOWS,
  INTERVALS,
  QUERY_EXPANSION,
  RETRIEVAL_COMPARISON,
} from "@/lib/evidence";

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
  ["result", "Results"],
  ["orthogonal", "Case study 1: a corpus orthogonal to itself"],
  ["check", "The check that found it"],
  ["fusion", "Case study 2: comparing incomparable numbers"],
  ["paths", "The path nobody indexed"],
  ["rerank", "Case study 3: ranking is comparative"],
  ["worth", "What each change was worth"],
  ["claim", "What we can and cannot claim"],
  ["traces", "Open the evidence"],
  ["next", "What comes next"],
] as const;

const DELPHI = RETRIEVAL_COMPARISON.find((row) => row.ours)!;
const GREP = RETRIEVAL_COMPARISON.find((row) => row.system === "grep")!;
const RECALL20 = INTERVALS.find((row) => row.metric === "Recall@20")!;
const MRR_ROW = INTERVALS.find((row) => row.metric === "MRR")!;

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
              We are publishing the retrieval results behind Delphi, the
              corpora they were measured on, and the per-query traces they came
              from. On {BENCHMARK.name}, the shipped build returns more of the
              answer set than the leading hosted context engine and does it{" "}
              {HEAD_TO_HEAD.latencyRatio.toFixed(1)} times faster on a laptop.
              It does not lead on every metric, and this piece is specific
              about which.
            </p>

            <h2 id="result">Results</h2>

            <p>
              Delphi is an open-source context engine: it indexes
              repositories, documentation, papers, and datasets, and answers an
              agent&apos;s question with the files that answer it. The number
              that matters for an agent is whether the file it needs is in the
              window it gets, which is what these measure.
            </p>

            <HeadlineResults />

            <p>
              Recall@20 is the difference that survives:{" "}
              {RECALL20.diff.toFixed(3)} in Delphi&apos;s favour, 95% interval{" "}
              [{RECALL20.lo.toFixed(3)}, {RECALL20.hi.toFixed(3)}], winning{" "}
              {RECALL20.wins} cases to {RECALL20.losses}. Latency is the other:
              {" "}{(HEAD_TO_HEAD.delphi.latencyMs / 1000).toFixed(1)}s against{" "}
              {(HEAD_TO_HEAD.nia.latencyMs / 1000).toFixed(1)}s.
            </p>

            <p>
              MRR reads {HEAD_TO_HEAD.delphi.mrr.toFixed(3)} against{" "}
              {HEAD_TO_HEAD.nia.mrr.toFixed(3)}, which looks like a loss and is
              not one we can claim: the interval runs from{" "}
              {MRR_ROW.lo.toFixed(3)} to {MRR_ROW.hi.toFixed(3)} and the cases
              split {MRR_ROW.wins} to {MRR_ROW.losses} with {MRR_ROW.ties}{" "}
              ties. At sixty cases that is a coin flip. We say so rather than
              reporting it either way.<sup>1</sup>
            </p>

            <p>
              The two engines also answer differently. The comparator returns
              about {HEAD_TO_HEAD.nia.meanPaths.toFixed(0)} files per query and
              Delphi returns {HEAD_TO_HEAD.delphi.meanPaths.toFixed(0)}. Short
              lists concentrate on rank one, long lists cover more of the
              answer. Which you want depends on whether your agent gets one
              shot or can keep reading.
            </p>

            <p>
              Against the benchmark&apos;s own published baselines on the
              development split, scored by the same code:
            </p>

            <ComparisonFigure />

            <p>
              Delphi does not lead Recall@20 outright either. Plain grep gets{" "}
              {GREP.recall20.toFixed(3)}. We would rather print that than drop
              the column. If your engine finds the right file somewhere in
              twenty results, you have not beaten <code>grep -r</code>. The
              argument has to be won at the top of the list, and that is where
              we still have work to do.
            </p>

            <ScopeStatement />

            <h2 id="orthogonal">A corpus orthogonal to itself</h2>

            <p>
              The symptom was that semantic queries returned nonsense. We asked
              a 68-repository corpus about TLS configuration in a gRPC proxy and
              got back an interval tree, a systemd journal wrapper, and some
              file-locking utilities. Exact symbol lookups worked perfectly.
              Anything that went through the embedding did not.
            </p>

            <p>
              Two embedding models can produce vectors of the same width. When
              they do, pgvector will compute a cosine between them without
              complaining. The query succeeds, results come back ranked, and the
              ranking is noise, because the two spaces have nothing to do with
              each other. There is no error to catch. The only thing wrong is
              the answer.
            </p>

            <h2 id="check">The check that found it</h2>

            <p>
              The check is embarrassingly simple. Take a chunk out of the index.
              Embed its own content with whatever model answers queries today.
              Compare that vector against the one already stored. If the two
              sides agree, a chunk has to be nearly identical to itself.
            </p>

            <MismatchFigure />

            <p>
              It scored {EMBEDDING_MISMATCH.cosineBefore.toFixed(4)}. That is
              orthogonal, the number you get from two random vectors.
              Pointing the query path at{" "}
              <code>{EMBEDDING_MISMATCH.indexedWith}</code>, the model that had
              actually built the index, moved the same comparison to{" "}
              {EMBEDDING_MISMATCH.cosineAfter.toFixed(3)}. The vector branch was
              weighted 0.5, the largest weight in the pipeline. Half the ranking
              signal had been random for the entire evaluation.
            </p>

            <p>
              The database had known all along.{" "}
              <code>repositories.embedding_model</code> records which model
              indexed each repository; it simply was never compared against the
              model answering queries. Delphi now makes that comparison on every
              search and reports it on <code>/backend-health</code>, because an
              engine that returns confident nonsense is worse than one that
              returns an error.
            </p>

            <h2 id="fusion">Comparing incomparable numbers</h2>

            <p>
              With the embedding fixed, a second problem surfaced. Delphi fans a
              query out across vector, BM25, symbol, path, and trigram branches,
              then fuses the results. Each branch normalised its own scores by
              dividing by that branch&apos;s top score. So the best hit of every
              branch got pinned to exactly 1.0, however bad it was.
            </p>

            <p>
              A query with no good semantic match still produces a vector
              branch, and its first result is rank one by definition. Rescaled,
              that least-bad hit became a perfect 1.0, and at weight 0.5 it
              outranked chunks that three branches independently agreed on. The
              fingerprint was a suspiciously round <code>0.5000</code> at the
              top of result lists: weight times a manufactured perfect score.
            </p>

            <p>
              Reciprocal rank fusion exists for this reason. Ranks compare
              across branches. Raw scores do not. A cosine and a{" "}
              <code>ts_rank_cd</code> were never the same unit. Fusion now
              scores position instead of magnitude.
            </p>

            <h2 id="paths">The path nobody indexed</h2>

            <p>
              The third problem was the most mundane. BM25 indexes chunk
              content. Nothing indexed <code>file_path</code>. A query naming a
              file could not retrieve that file&apos;s neighbours lexically at
              all. Searching for <code>etcd_grpcproxy_test</code> returned{" "}
              <code>fileutil.go</code>, because the filename existed nowhere in
              the searchable text.
            </p>

            <p>
              This matters because agents anchor on paths constantly: “what
              tests cover <code>grpc_proxy.go</code>”, “why did{" "}
              <code>tokens.py</code> change”. Delphi now has a path-affinity
              branch that matches on separator-stripped lowercase, so an anchor
              of <code>grpc_proxy</code> reaches{" "}
              <code>etcd_grpcproxy_test.go</code>, which underscore-sensitive
              comparison misses. Results are capped per
              directory, because a stem like <code>grpc_proxy</code> matches
              thirty sibling files at a perfect score and would otherwise fill
              the branch before the one test in <code>tests/e2e/</code> ever
              appeared.
            </p>

            <h2 id="rerank">The reranker that never ran</h2>

            <p>
              Delphi had a cross-encoder reranker. It had never once executed
              during the evaluation. The model loaded lazily on first query, the
              load was a multi-hundred-megabyte download, and the call site
              wrapped it in a <code>try/except</code> that fell back silently to
              fused ranking. Every query took the fallback.
            </p>

            <p>
              Warming it at startup and reporting readiness on the health
              endpoint fixed the availability problem and produced a genuinely
              surprising result once we could measure it.
            </p>

            <RerankerFigure />

            <p>
              The 22M-parameter <code>ms-marco-MiniLM</code> model beats
              278M-parameter <code>bge-reranker-base</code> on every metric while
              running about seven times faster. Preferring the larger,
              code-aware model, which is what the default did, cost latency and
              quality at the same time. Reranking depth behaves the same way:
              at a window of 100 with the cross-encoder deciding the order
              outright, Recall@20 collapses to 0.444, because the model
              confidently promotes plausible-looking files from the tail.
              Blending it over the fused score, shallowly, is what makes it
              useful.
            </p>

            <h2 id="worth">What each fix was worth</h2>

            <AblationFigure />

            <p>
              The first row is what the previous evaluation actually measured.
              Almost the entire improvement comes from the embedding fix; rank
              fusion and the path branch add a little on top; the cross-encoder
              buys the top of the list. It would be more flattering to present
              this as four clever retrieval improvements. It was one
              configuration bug and three modest engineering fixes, and the
              honest version is more useful to anyone running a similar stack.
            </p>

            <PipelineFigure />

            <h2 id="claim">What we can claim</h2>

            <p>
              On {BENCHMARK.name}, {BENCHMARK.cases} development cases: Delphi
              leads every published baseline on MRR and Recall@5, and trails
              grep on Recall@20. On the held-out split, all {HELD_OUT.scored}{" "}
              positive cases with every corpus provisioned and{" "}
              {HELD_OUT.failures} failed queries, it scores{" "}
              {HELD_OUT.mrr.toFixed(3)} MRR, {HELD_OUT.recall5.toFixed(3)}{" "}
              Recall@5 and {HELD_OUT.recall20.toFixed(3)} Recall@20 at{" "}
              {(HELD_OUT.latencyMsMean / 1000).toFixed(2)}s mean latency. Those
              come out slightly ahead of the split the pipeline was tuned on,
              which is the direction you want: no sign of having fit the
              tuning set.
            </p>

            <p>
              The per-workflow spread says more than the average does.
              Retrieval is close to solved when the query names things that
              exist in the code, and barely works when it does not.
            </p>

            <div className="not-prose mt-8">
              <div className="figure-heading">
                <span>Held-out, by workflow</span>
                <span>{HELD_OUT.scored} cases</span>
              </div>
              <div className="divide-y divide-[var(--line)]">
                <div className="grid grid-cols-[1fr_44px_60px_60px_64px] gap-3 py-3 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
                  <span>Workflow</span>
                  <span className="text-right">n</span>
                  <span className="text-right">MRR</span>
                  <span className="text-right">R@5</span>
                  <span className="text-right">R@20</span>
                </div>
                {HELD_OUT_WORKFLOWS.map((row) => (
                  <div
                    className="grid grid-cols-[1fr_44px_60px_60px_64px] gap-3 py-4 text-[14px]"
                    key={row.workflow}
                  >
                    <span className="font-mono">{row.workflow}</span>
                    <span className="text-right font-mono text-[var(--fg-mute)]">
                      {row.cases}
                    </span>
                    <span className="text-right font-mono text-[var(--fg-strong)]">
                      {row.mrr.toFixed(3)}
                    </span>
                    <span className="text-right font-mono text-[var(--fg-mute)]">
                      {row.recall5.toFixed(3)}
                    </span>
                    <span className="text-right font-mono text-[var(--fg-mute)]">
                      {row.recall20.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <p>
              A failure trace hands the retriever real symbols, real file
              names, real stack frames, and Delphi finds the root-cause file in
              the top five 76% of the time. A review comment hands it English,
              something like &ldquo;this should probably be extracted&rdquo;, and
              the same engine manages 17%. The gap between those two rows is not a
              ranking problem. It is the difference between a query that
              contains evidence and one that does not, and no amount of fusion
              tuning closes it.
            </p>

            <p>
              What does close some of it is giving the embedding something in
              its own vocabulary to match. A code index is written in code; the
              question is written in English. Asking a small model to draft the
              code it thinks the answer looks like, and embedding that
              alongside the question, moves every metric on the held-out split:
            </p>

            <div className="not-prose mt-8">
              <div className="figure-heading">
                <span>Hypothetical-document expansion</span>
                <span>held-out, {HELD_OUT.scored} cases</span>
              </div>
              <div className="divide-y divide-[var(--line)]">
                <div className="grid grid-cols-[1fr_60px_60px_64px_64px] gap-3 py-3 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
                  <span>Configuration</span>
                  <span className="text-right">MRR</span>
                  <span className="text-right">R@5</span>
                  <span className="text-right">R@20</span>
                  <span className="text-right">Latency</span>
                </div>
                {QUERY_EXPANSION.map((row) => (
                  <div
                    className="grid grid-cols-[1fr_60px_60px_64px_64px] gap-3 py-4 text-[14px]"
                    key={row.label}
                  >
                    <span>{row.label}</span>
                    <span className="text-right font-mono text-[var(--fg-strong)]">
                      {row.mrr.toFixed(3)}
                    </span>
                    <span className="text-right font-mono text-[var(--fg-mute)]">
                      {row.recall5.toFixed(3)}
                    </span>
                    <span className="text-right font-mono text-[var(--fg-mute)]">
                      {row.recall20.toFixed(3)}
                    </span>
                    <span className="text-right font-mono text-[var(--fg-mute)]">
                      {(row.latencyMs / 1000).toFixed(1)}s
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <p>
              The snippet does not have to be right. It has to be written the
              way the corpus is written, which is enough to land the query
              vector in the right neighbourhood. Only the vector branch sees
              it. BM25, symbol, and path still get the caller&apos;s literal
              words, because inventing terms for an exact-match branch
              manufactures precision that is not there. Queries already full of
              identifiers are skipped entirely, and their scores are unchanged,
              which is the shape you would expect if the mechanism works for
              the reason claimed.
            </p>

            <p>
              What we cannot claim is that Delphi is state of the art at the
              top of the list. On this benchmark it is not: the hosted
              comparator ranks better at MRR and Recall@5, and we publish that
              alongside the metrics we do lead. The claim we can defend is
              narrower. Delphi finds more of the answer set than the comparator,
              beats every published baseline on early precision, and does it
              much faster, on your own hardware.
            </p>

            <p>
              The broader lesson is not about any one engine. A retrieval system
              can be completely broken and still return ranked, plausible,
              confident results, and every metric downstream of it will move
              smoothly and mean nothing. If you run a vector index, embed a
              chunk&apos;s own content and check it against its stored vector.
              It takes one query and it is the cheapest assertion in the stack.
            </p>

            <h2 id="traces">Open the evidence</h2>

            <p>
              Every number above comes from queries that were recorded in full.
              Below are real traces from the benchmarked build, two per
              workflow, taken by position in the split rather than picked for
              how they turned out. Expand one to see the exact query the engine
              received, the ranked files it returned, which retrieval branch
              found each one, and the raw response record.
            </p>

            <p>
              They are worth reading for the failures as much as the hits. Three
              of the eight miss the gold file entirely. The first{" "}
              <code>code2test</code> trace puts five changelog files above the
              regression test it was asked for: the query mentions a version
              bump, changelogs are dense with version strings, and BM25 has no
              way to know that a changelog can never be an answer to “which test
              covers this?”. The gold file appears at rank 9, found by the path
              branch. That is a live weakness, not a rounding error.
            </p>

            <TraceGallery />

            <h2 id="next">What comes next</h2>

            <p>
              The comparison above rests on {HEAD_TO_HEAD.cases} cases because
              that is how many the hosted comparator completed. The run against
              all {HELD_OUT.scored} failed every query on an HTTP error, so the
              larger paired sample does not exist yet. Re-indexing those corpora
              into the comparator and running it again is the single thing that
              would settle MRR, and until it happens we are not going to
              describe that metric as won or lost.
            </p>

            <p>
              On our own side the open problem is rank one. Across the
              held-out split the gold file is inside the top twenty
              far more often than it is inside the top five, so the candidate
              is usually retrieved and then not promoted. That is a judgement
              problem in the reranking stage rather than a coverage problem in
              retrieval, and widening the pool makes it worse rather than
              better. Two directions we have not tried: fitting a reranker to
              this task instead of using an off-the-shelf one, and routing by
              query shape so that a question asking &ldquo;which test covers
              this&rdquo; is ranked by a different rule than one asking where
              something is implemented.
            </p>

            <p>
              Every artifact behind these numbers is in the repository: the
              corpus lock file, the per-query records, the summaries, and the
              measured-and-rejected list of everything that did not work.
            </p>

            <div className="mt-20 border-t border-[var(--line-strong)] pt-7">
              <p className="eyebrow text-[var(--fg-mute)]">Footnotes</p>
              <ol className="mt-5 space-y-3 text-[13px] leading-6 text-[var(--fg-mute)]">
                <li>
                  1. Intervals are a paired bootstrap over the per-case
                  difference, 4000 resamples, 95% percentile interval. We treat
                  a difference as real only when the interval excludes zero. An
                  earlier version of this page reported the comparison at 135
                  cases with a {BENCHMARK.name} configuration that had query
                  expansion and listwise reranking disabled, which are the two
                  stages that order the head of the list. Those numbers
                  described a build we do not ship and have been replaced.
                </li>
              </ol>
            </div>

            <div className="mt-10 border-t border-[var(--line-strong)] pt-7">
              <p className="eyebrow text-[var(--fg-mute)]">References</p>
              <ol className="mt-5 space-y-3 text-[13px] leading-6 text-[var(--fg-mute)]">
                <li>
                  1.{" "}
                  <Link href="https://github.com/eyuansu62/agent-retrieval-bench">
                    Agent Retrieval Bench
                  </Link>
                  , commit <code>{BENCHMARK.commit.slice(0, 12)}</code>.
                </li>
                <li>
                  2. Cormack, Clarke, and Buettcher, “Reciprocal Rank Fusion
                  Outperforms Condorcet and Individual Rank Learning Methods”,
                  SIGIR 2009.
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
