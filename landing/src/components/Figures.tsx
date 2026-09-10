/*
  SVG figures for the site. Each drawing is laid out at the width it is shown
  at on a desktop screen, so its labels render at their nominal size; on
  narrow screens the figure scrolls sideways rather than shrinking. Colors
  come from the page's CSS variables, so the same drawing works in the light
  and dark themes and on the paper-white research page.
*/

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.1 } as const;
const muted = { fill: "currentColor", opacity: 0.62 } as const;

function Arrow() {
  return (
    <defs>
      <marker
        id="arrow"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M0 0.8 9.2 5 0 9.2" fill="none" stroke="currentColor" strokeWidth="1.1" />
      </marker>
    </defs>
  );
}

export function ArchitectureFigure() {
  return (
    <svg viewBox="0 0 860 392" role="img" aria-labelledby="fig-arch-title">
      <title id="fig-arch-title">
        An agent talks to Delphi over MCP; Delphi indexes sources into PostgreSQL with pgvector
        and answers searches from it.
      </title>
      <Arrow />

      {/* Dashboard */}
      <rect x="375" y="10" width="150" height="36" {...stroke} />
      <text x="450" y="33" textAnchor="middle" fontSize="14">
        Dashboard
      </text>
      <line x1="450" y1="46" x2="450" y2="69" {...stroke} markerEnd="url(#arrow)" />

      {/* Delphi */}
      <rect x="300" y="70" width="300" height="250" {...stroke} strokeWidth="1.4" />
      <text x="450" y="96" textAnchor="middle" fontSize="17" fontWeight="700">
        Delphi
      </text>

      <rect x="318" y="110" width="264" height="48" {...stroke} />
      <text x="450" y="130" textAnchor="middle" fontSize="14">
        HTTP API and MCP server
      </text>
      <text x="450" y="147" textAnchor="middle" fontSize="12" {...muted}>
        localhost:8742
      </text>

      <rect x="318" y="168" width="264" height="48" {...stroke} />
      <text x="450" y="188" textAnchor="middle" fontSize="14">
        Hybrid retrieval and context packs
      </text>
      <text x="450" y="205" textAnchor="middle" fontSize="12" {...muted}>
        vectors, BM25, trigrams, symbols, paths
      </text>

      <rect x="318" y="226" width="264" height="48" {...stroke} />
      <text x="450" y="246" textAnchor="middle" fontSize="14">
        Indexing workers
      </text>
      <text x="450" y="263" textAnchor="middle" fontSize="12" {...muted}>
        tree-sitter parsers, chunking, embeddings
      </text>

      {/* Agent */}
      <rect x="20" y="99" width="200" height="70" {...stroke} />
      <text x="120" y="125" textAnchor="middle" fontSize="15" fontWeight="700">
        Coding agent
      </text>
      <text x="120" y="144" textAnchor="middle" fontSize="12" {...muted}>
        Claude Code, Cursor, Windsurf,
      </text>
      <text x="120" y="159" textAnchor="middle" fontSize="12" {...muted}>
        or any MCP client
      </text>
      <line x1="220" y1="134" x2="299" y2="134" {...stroke} markerEnd="url(#arrow)" />
      <text x="260" y="126" textAnchor="middle" fontSize="12" {...muted}>
        MCP
      </text>

      {/* Database */}
      <path d="M670 150 a70 14 0 0 1 140 0 v110 a70 14 0 0 1 -140 0 z" {...stroke} />
      <path d="M670 150 a70 14 0 0 0 140 0" {...stroke} />
      <text x="740" y="210" textAnchor="middle" fontSize="15" fontWeight="700">
        PostgreSQL
      </text>
      <text x="740" y="230" textAnchor="middle" fontSize="12" {...muted}>
        with pgvector
      </text>
      <line
        x1="601"
        y1="205"
        x2="669"
        y2="205"
        {...stroke}
        markerEnd="url(#arrow)"
        markerStart="url(#arrow)"
      />

      {/* Sources */}
      <line x1="450" y1="352" x2="450" y2="321" {...stroke} markerEnd="url(#arrow)" />
      <text x="458" y="341" fontSize="12" {...muted}>
        index
      </text>
      <text x="450" y="376" textAnchor="middle" fontSize="13.5">
        repositories, documentation, papers, datasets, local folders
      </text>
    </svg>
  );
}

/* ------------------------------------------------------------------ Hero */

const SOURCES = [
  "dense vectors",
  "BM25 full text",
  "trigram symbols",
  "exact symbol",
  "path and glob",
  "path tokens",
];

const RESULTS: [string, number][] = [
  ["auth/callback.py", 1],
  ["auth/session.py", 0.74],
  ["routes/oauth.py", 0.58],
  ["tests/test_auth.py", 0.41],
  ["docs/auth.md", 0.27],
];

/**
 * One query fans out to six candidate sources, the six rankings fuse into
 * one list, and the same query replayed returns the same list. Composed as
 * a portrait to sit beside the hero copy. Draws itself once on load;
 * `prefers-reduced-motion` shows the finished drawing.
 */
export function HeroFigure() {
  const W = 440;
  const cx = W / 2;

  const queryW = 208;
  const queryH = 42;
  const queryY = 22;
  const queryX = cx - queryW / 2;

  const colW = 196;
  const colX = [14, W - 14 - colW];
  const rowH = 32;
  const rowTop = 118;
  const rowGap = 14;

  const fuseW = 164;
  const fuseH = 48;
  const fuseY = 286;
  const fuseX = cx - fuseW / 2;

  const listX = 40;
  const listW = W - 2 * listX;
  const listTop = 392;
  const listGap = 38;
  const noteY = listTop + RESULTS.length * listGap + 12;

  return (
    <svg
      className="hero-figure"
      viewBox={`0 0 ${W} ${noteY + 40}`}
      role="img"
      aria-labelledby="hero-title hero-desc"
    >
      <title id="hero-title">How Delphi answers a search</title>
      <desc id="hero-desc">
        A query for handleAuthCallback is sent to six candidate sources at once: dense vectors,
        BM25 full text, trigram symbols, exact symbol lookup, path and glob lookup, and path
        tokens. Their rankings are fused by reciprocal rank into one ranked list of files, and
        replaying the same query returns the same list.
      </desc>

      {/* Query */}
      <g className="hf-fade" style={{ animationDelay: "0ms" }}>
        <text x={queryX} y={queryY - 8} fontSize="11" className="hf-muted">
          query
        </text>
        <rect x={queryX} y={queryY} width={queryW} height={queryH} rx="2" className="hf-box hf-box-strong" />
        <text x={cx} y={queryY + queryH / 2 + 4.5} textAnchor="middle" fontSize="13.5">
          handleAuthCallback
        </text>
      </g>

      {/* Fan-out to a 2 x 3 grid of candidate sources */}
      {SOURCES.map((label, i) => {
        const col = i % 2;
        const row = Math.floor(i / 2);
        const x = colX[col];
        const y = rowTop + row * (rowH + rowGap);
        const mid = x + colW / 2;
        return (
          <g key={label}>
            <path
              d={`M${cx} ${queryY + queryH} C ${cx} ${queryY + queryH + 30}, ${mid} ${y - 30}, ${mid} ${y}`}
              pathLength={1}
              className="hf-path"
              style={{ animationDelay: `${180 + i * 70}ms` }}
            />
            <g className="hf-fade" style={{ animationDelay: `${480 + i * 70}ms` }}>
              <rect x={x} y={y} width={colW} height={rowH} rx="2" className="hf-box" />
              <text x={mid} y={y + rowH / 2 + 4.5} textAnchor="middle" fontSize="12.5">
                {label}
              </text>
            </g>
            <path
              d={`M${mid} ${y + rowH} C ${mid} ${y + rowH + 26}, ${cx} ${fuseY - 26}, ${cx} ${fuseY}`}
              pathLength={1}
              className="hf-path"
              style={{ animationDelay: `${900 + i * 60}ms` }}
            />
          </g>
        );
      })}

      {/* Fusion */}
      <g className="hf-fade" style={{ animationDelay: "1400ms" }}>
        <rect x={fuseX} y={fuseY} width={fuseW} height={fuseH} rx="2" className="hf-box" />
        <text x={cx} y={fuseY + 20} textAnchor="middle" fontSize="13" fontWeight="700">
          rank fusion
        </text>
        <text x={cx} y={fuseY + 36} textAnchor="middle" fontSize="11" className="hf-muted">
          reciprocal rank
        </text>
      </g>
      <path
        d={`M${cx} ${fuseY + fuseH} L${cx} ${listTop - 26}`}
        pathLength={1}
        className="hf-path"
        style={{ animationDelay: "1700ms" }}
      />

      {/* Ranked results */}
      <text
        x={listX}
        y={listTop - 10}
        fontSize="11"
        className="hf-muted hf-fade"
        style={{ animationDelay: "1900ms" }}
      >
        ranked results
      </text>
      {RESULTS.map(([file, score], i) => {
        const y = listTop + i * listGap;
        return (
          <g key={file} className="hf-fade" style={{ animationDelay: `${1960 + i * 70}ms` }}>
            <text x={listX} y={y + 8} fontSize="12.5" className={i === 0 ? "hf-strong" : undefined}>
              {file}
            </text>
            <text x={listX + listW} y={y + 8} fontSize="11" textAnchor="end" className="hf-muted">
              {i + 1}
            </text>
            <rect x={listX} y={y + 16} width={listW} height="5" rx="2.5" className="hf-track" />
            <rect
              x={listX}
              y={y + 16}
              width={listW * score}
              height="5"
              rx="2.5"
              className={i === 0 ? "hf-bar hf-bar-strong" : "hf-bar"}
              style={{ animationDelay: `${2020 + i * 70}ms` }}
            />
          </g>
        );
      })}

      {/* Determinism */}
      <g className="hf-fade" style={{ animationDelay: "2600ms" }}>
        <path
          d={`M${listX} ${noteY + 3} l4.5 4.5 l9 -10`}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <text x={listX + 20} y={noteY + 6} fontSize="12">
          same query, same results
        </text>
        <text x={listX + 20} y={noteY + 23} fontSize="11" className="hf-muted">
          across requests and restarts
        </text>
      </g>
    </svg>
  );
}

/* ----------------------------------------------------------------- Chart */

type Cell = { value: number; delphi: boolean; reranked: boolean };

// SWE-bench Verified, 98 instances development never saw (paper, Appendix E).
const MRR: Cell[] = [
  { value: 0.319, delphi: false, reranked: false },
  { value: 0.66, delphi: false, reranked: true },
  { value: 0.507, delphi: true, reranked: false },
  { value: 0.7, delphi: true, reranked: true },
];
const RECALL: Cell[] = [
  { value: 0.733, delphi: false, reranked: false },
  { value: 0.733, delphi: false, reranked: true },
  { value: 0.806, delphi: true, reranked: false },
  { value: 0.82, delphi: true, reranked: true },
];

function Panel({ title, cells, x }: { title: string; cells: Cell[]; x: number }) {
  const base = 204;
  const scale = 156;
  const barW = 58;
  const xs = [28, 96, 196, 264];
  const width = 350;
  return (
    <g transform={`translate(${x} 0)`}>
      <text x="0" y="16" fontSize="15" fontWeight="700">
        {title}
      </text>
      <line x1="0" y1={base} x2={width} y2={base} className="ch-axis" />
      {cells.map((c, i) => {
        const h = c.value * scale;
        const cls = ["ch-bar", c.delphi ? "ch-delphi" : "ch-conv", c.reranked ? "ch-filled" : "ch-outline"].join(" ");
        return (
          <g key={i}>
            <rect x={xs[i]} y={base - h} width={barW} height={h} className={cls} />
            <text x={xs[i] + barW / 2} y={base - h - 8} textAnchor="middle" fontSize="13">
              {c.value.toFixed(3).replace(/^0/, "")}
            </text>
          </g>
        );
      })}
      <text x={(xs[0] + xs[1] + barW) / 2} y={base + 22} textAnchor="middle" fontSize="13" className="hf-muted">
        conventional
      </text>
      <text x={(xs[2] + xs[3] + barW) / 2} y={base + 22} textAnchor="middle" fontSize="13" className="hf-muted">
        Delphi
      </text>
    </g>
  );
}

/**
 * Candidate pool × learned reranking on the 98-instance SWE-bench Verified
 * draw. Outlined bars are the candidates alone; filled bars have Delphi's
 * rerankers attached.
 */
export function FactorialChart() {
  return (
    <svg className="chart-svg" viewBox="0 0 864 282" role="img" aria-labelledby="chart-title chart-desc">
      <title id="chart-title">Candidate pool versus reranking on SWE-bench Verified</title>
      <desc id="chart-desc">
        Two bar charts. MRR: conventional candidates score 0.319 alone and 0.660 with Delphi&apos;s
        rerankers; Delphi candidates score 0.507 alone and 0.700 with the rerankers. Recall at
        20: conventional 0.733 in both cases; Delphi 0.806 alone and 0.820 with the rerankers.
      </desc>
      <Panel title="MRR" cells={MRR} x={0} />
      <Panel title="Recall@20" cells={RECALL} x={470} />
      <g transform="translate(0 258)">
        <rect x="0" y="0" width="14" height="14" className="ch-bar ch-conv ch-outline" />
        <text x="22" y="12" fontSize="13" className="hf-muted">
          candidates alone
        </text>
        <rect x="170" y="0" width="14" height="14" className="ch-bar ch-conv ch-filled" />
        <text x="192" y="12" fontSize="13" className="hf-muted">
          with Delphi&apos;s rerankers attached
        </text>
      </g>
    </svg>
  );
}
