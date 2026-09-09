import type { Metadata } from "next";
import Link from "next/link";

const TITLE = "Where Do Context-Engine Gains Come From?";
const SUBTITLE =
  "A Component-Level Decomposition of Repository Retrieval Under Matched Baselines and Audited Exposure";
const DESCRIPTION =
  "Decomposing the Delphi context engine against conventional retrieval built from its own parts, on SWE-bench Verified instances its development never saw: the gains sit in candidate generation, not reranking, and only for issue-style queries.";

const PDF = "/papers/context-engine-gains.pdf";
// Set once arXiv assigns the identifier, e.g. "https://arxiv.org/abs/2609.XXXXX".
const ARXIV: string | null = null;
const BENCHMARK = "https://github.com/aayambansal/delphi-benchmark";
const DATASET = "https://huggingface.co/datasets/aayambansall/delphi-benchmark-traces";
const DELPHI = "https://github.com/synthetic-sciences/delphi";
const FROZEN = `${DELPHI}/commit/91d76c1`;
const CANONICAL = "https://trydelphi.ai/research";

export const metadata: Metadata = {
  title: `${TITLE} | Delphi research`,
  description: DESCRIPTION,
  alternates: { canonical: CANONICAL },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "article",
    url: CANONICAL,
    siteName: "Delphi",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
};

const FINDINGS: [string, string][] = [
  [
    "The advantage is the candidate pool, not the reranker.",
    "Before any reranking, Delphi's candidates lead the full conventional stack by +0.19 MRR and +0.07 Recall@20. The shared rerankers add +0.34 MRR to conventional candidates but +0.19 to Delphi's, so after reranking MRR ties while the recall gap (+0.09) persists.",
  ],
  [
    "The pool advantage is chunking, index, and weighting.",
    "The branch ablation attributes +0.15 MRR to Delphi's chunking and index (same two-branch fusion) and +0.06 to its vector-heavy weighting; the four structural branches add +0.06 jointly, none more than 0.03.",
  ],
  [
    "It depends on query style.",
    "On repository-disjoint commit-to-files queries the pattern inverts: Delphi's pool has lower recall than two-branch fusion and the rerankers add nothing to either pool.",
  ],
  [
    "Exposure changes the evidence class.",
    "A case-level ledger reclassifies Delphi's 220-case ARB partition from held-out to validation evidence. Confirmatory results rest on 238 cases scored once and never before, with intervals adjusted for three looks.",
  ],
  [
    "Matched contracts remove a hosted lead.",
    "Routing every engine's evidence through one frozen synthesis stage turns an apparent hosted-engine lead on documentation into a four-way tie. Re-indexing a corpus from scratch reproduced Delphi's ordered top-20 on 1 of 18 cases.",
  ],
  [
    "No seed effect in the executable pilot.",
    "62 instances, four seed conditions, two repeats, one fixed mini-SWE-agent: a retrieval seed resolves no more verified repairs than a random-file seed, and repeats disagree by more than the effects under study. The pilot audits its own seed and yields a precision target for a decisive study.",
  ],
];

const ARTIFACTS: [string, React.ReactNode][] = [
  ["Paper", <a key="pdf" href={PDF}>PDF, 30 pages</a>],
  [
    "Code and results",
    <>
      <a key="bench" href={BENCHMARK}>
        aayambansal/delphi-benchmark
      </a>
      : protocols, every run artifact, the harness, the exposure ledger, journals, and the paper source
    </>,
  ],
  [
    "Agent trajectories",
    <>
      <a key="hf" href={DATASET}>
        Hugging Face dataset
      </a>
      : 620 mini-SWE-agent runs with every model call, harness verdicts and logs, and a browsable index
    </>,
  ],
  [
    "Evaluated engine",
    <>
      Delphi at revision <a key="frozen" href={FROZEN}><code>91d76c1</code></a>
    </>,
  ],
];

const BIBTEX = `@article{bansal2026contextengine,
  title   = {Where Do Context-Engine Gains Come From? A Component-Level Decomposition of
             Repository Retrieval Under Matched Baselines and Audited Exposure},
  author  = {Bansal, Aayam and Gangwani, Ishaan},
  year    = {2026},
  url     = {${CANONICAL}},
  note    = {Preprint}
}`;

export default function Research() {
  return (
    <>
      <a className="skip-link" href="#abstract">
        Skip to content
      </a>

      <main className="paper">
        <header className="titleblock">
          <p className="eyebrow">Research &middot; Preprint, September 2026</p>
          <h1 className="paper-title">
            Where Do <span className="whitespace-nowrap">Context-Engine</span> Gains Come From?
          </h1>
          <p className="subtitle paper-subtitle">{SUBTITLE}</p>
          <p className="authors">Aayam Bansal, Ishaan Gangwani</p>
          <p className="affiliation">
            <a href="https://syntheticsciences.ai">Synthetic Sciences</a>
          </p>
          <nav className="links" aria-label="Paper links">
            <a href={PDF}>PDF</a>
            {ARXIV ? <a href={ARXIV}>arXiv</a> : null}
            <a href={BENCHMARK}>Code</a>
            <a href={DATASET}>Trajectories</a>
            <Link href="/">Delphi</Link>
          </nav>
        </header>

        <section className="abstract" id="abstract">
          <h2>Abstract</h2>
          <p>
            Context engines that index a repository and return files to a coding agent report
            large gains over lexical baselines, but the gains are rarely decomposed: how much is a
            learned reranker that would help any candidate pool, how much is the engine&apos;s own
            candidate generation, and how much was selected on the evaluation data? We answer this
            for one open-source engine, Delphi, with a protocol that records for every evaluation
            case whether development could have seen it, builds a ladder of conventional retrievers
            from the same embedding model with Delphi&apos;s own rerankers and query expansion
            attached, varies candidate generation and learned reranking factorially, and ablates
            Delphi&apos;s candidate branches one at a time on a fresh, never-scored draw. On three
            SWE-bench Verified draws that development never saw (62, 98, and 60 instances; sizes
            fixed before scoring), Delphi&apos;s advantage over the full conventional stack lies in
            its candidate pool: before any reranking its candidates lead by +0.19 MRR and +0.07
            Recall@20; the shared rerankers add +0.34 MRR to conventional candidates but +0.19 to
            Delphi&apos;s, so after reranking the MRR gap closes to a tie while the recall gap
            (+0.09) persists; pooled over the three draws, Delphi&apos;s yield-metric leads
            (+0.06 to +0.09) exclude zero at a three-look-adjusted level and its MRR lead (+0.065)
            at 95% only. A branch-level ablation on the fresh draw attributes the candidate-pool
            advantage mostly to Delphi&apos;s chunking and index (+0.15 MRR for the same two-branch
            fusion) and its vector-heavy weighting (+0.06), with the four structural branches
            adding +0.06 jointly and no single branch more than 0.03. On a repository-disjoint
            commit-to-files set the pattern inverts: Delphi&apos;s pool has lower recall than
            two-branch fusion and the rerankers add nothing to either pool, so the reading
            &ldquo;the reranker does the work&rdquo; holds only for issue queries. Matched output
            contracts turn an apparent hosted-engine lead on documentation into a four-way tie;
            re-indexing a corpus from scratch reproduced Delphi&apos;s ordered top-20 on 1 of 18
            cases; and a preregistered executable pilot (62 instances, two trajectories each)
            resolves no seed effect and audits its own seed. We release code, per-case artifacts,
            agent trajectories, and the exposure ledger.
          </p>
        </section>

        <section id="protocol">
          <h2>
            <span className="num">1</span>
            <span>What the protocol does</span>
          </h2>
          <p>
            A margin over BM25 does not say whether an engine&apos;s design or a learned reranker
            that would help any candidate pool produced it, nor how much of it was selected on the
            evaluation data. The protocol separates these by
          </p>
          <ul>
            <li>
              recording for every evaluation case whether development could have seen it, in an
              exposure ledger with three classes, and pooling only cases scored once and never
              before;
            </li>
            <li>
              building a ladder of conventional retrievers from Delphi&apos;s own embedding model,
              attaching Delphi&apos;s rerankers and query expansion one rung at a time with the same
              prompts and parsers;
            </li>
            <li>
              varying candidate generation and learned reranking factorially, so the two factors
              the ladder confounds can be told apart; and
            </li>
            <li>
              ablating Delphi&apos;s six candidate branches one at a time on a fresh draw that no
              development decision could see.
            </li>
          </ul>
          <p>
            Every number is generated from persisted run artifacts by scripts in the released
            repository, and failed or invalidated runs are kept for the audit trail.
          </p>
        </section>

        <section id="findings">
          <h2>
            <span className="num">2</span>
            <span>Findings</span>
          </h2>
          <p>
            Measured on three SWE-bench Verified draws that development never saw (62, 98, and 60
            instances; sizes fixed before scoring) and one repository-disjoint commit-to-files set.
          </p>
          <ul>
            {FINDINGS.map(([lead, detail]) => (
              <li key={lead}>
                <b>{lead}</b> {detail}
              </li>
            ))}
          </ul>
          <p>
            The paper claims no state of the art; several findings are null or negative for the
            engine we built, and they are reported with the same prominence as the positive ones.
          </p>
        </section>

        <section id="artifacts">
          <h2>
            <span className="num">3</span>
            <span>Artifacts</span>
          </h2>
          <div className="table-wrap">
            <table className="booktabs">
              <thead>
                <tr>
                  <th scope="col">Artifact</th>
                  <th scope="col">Where</th>
                </tr>
              </thead>
              <tbody>
                {ARTIFACTS.map(([name, where]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{where}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Repository corpora (58 repositories, 425 snapshots) are re-cloned from public GitHub at
            the recorded commits by a script in the repository rather than redistributed. The
            trajectories, results, and analyses are released under CC BY 4.0.
          </p>
        </section>

        <section id="citation">
          <h2>Citation</h2>
          <pre className="codeblock">{BIBTEX}</pre>
        </section>

        <footer className="colophon">
          <div>
            <span>
              Delphi is a <a href="https://syntheticsciences.ai">Synthetic Sciences</a>
              {" project. "}
            </span>
            <span>&copy; {new Date().getFullYear()} InkVell Inc.</span>
          </div>
          <ul>
            <li>
              <Link href="/">Delphi</Link>
            </li>
            <li>
              <a href={DELPHI}>GitHub</a>
            </li>
            <li>
              <a href="mailto:team@syntheticsciences.ai">Contact</a>
            </li>
            <li>
              <a href="https://syntheticsciences.ai/privacy">Privacy</a>
            </li>
            <li>
              <a href="https://syntheticsciences.ai/terms">Terms</a>
            </li>
          </ul>
        </footer>
      </main>
    </>
  );
}
