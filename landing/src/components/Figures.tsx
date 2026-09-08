/*
  Line figures for the project page. Plain SVG, 1px strokes, the page's
  typeface inherited from the document. Colors come from `currentColor`.
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
    <svg viewBox="0 0 860 392" role="img" aria-labelledby="fig1-title">
      <title id="fig1-title">
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
        vectors · BM25 · trigrams · symbols · paths
      </text>

      <rect x="318" y="226" width="264" height="48" {...stroke} />
      <text x="450" y="246" textAnchor="middle" fontSize="14">
        Indexing workers
      </text>
      <text x="450" y="263" textAnchor="middle" fontSize="12" {...muted}>
        tree-sitter parsers · chunking · embeddings
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
      <path
        d="M670 150 a70 14 0 0 1 140 0 v110 a70 14 0 0 1 -140 0 z"
        {...stroke}
      />
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
        repositories · documentation · papers · datasets · local folders
      </text>
    </svg>
  );
}

const CANDIDATES = [
  "dense vectors (pgvector)",
  "BM25 full text",
  "trigram symbol match",
  "exact symbol lookup",
  "exact path and glob",
  "path tokens (opt-in)",
];

export function RetrievalFigure() {
  const boxX = 210;
  const boxW = 200;
  const boxH = 32;
  const gap = 9;
  const top = 8;
  const fusionY = 148;

  return (
    <svg viewBox="0 0 860 252" role="img" aria-labelledby="fig2-title">
      <title id="fig2-title">
        A query fans out to six candidate sources whose rankings are fused by reciprocal rank into
        one list or a context pack.
      </title>
      <Arrow />

      {/* Query */}
      <rect x="20" y="115" width="120" height="66" {...stroke} />
      <text x="80" y="139" textAnchor="middle" fontSize="15" fontWeight="700">
        Query
      </text>
      <text x="80" y="158" textAnchor="middle" fontSize="12" {...muted}>
        identifiers, paths,
      </text>
      <text x="80" y="172" textAnchor="middle" fontSize="12" {...muted}>
        or prose
      </text>
      <line x1="80" y1="181" x2="80" y2="197" {...stroke} strokeDasharray="3 3" />
      <text x="80" y="212" textAnchor="middle" fontSize="12" {...muted}>
        optional expansion
      </text>

      {/* Candidate sources */}
      {CANDIDATES.map((label, i) => {
        const y = top + i * (boxH + gap);
        const cy = y + boxH / 2;
        return (
          <g key={label}>
            <line x1="140" y1="148" x2={boxX} y2={cy} {...stroke} />
            <rect x={boxX} y={y} width={boxW} height={boxH} {...stroke} fill="var(--color-paper)" />
            <text x={boxX + boxW / 2} y={cy + 4.5} textAnchor="middle" fontSize="13">
              {label}
            </text>
            <line x1={boxX + boxW} y1={cy} x2="480" y2={fusionY} {...stroke} />
          </g>
        );
      })}

      {/* Fusion */}
      <rect x="480" y="118" width="150" height="60" {...stroke} fill="var(--color-paper)" />
      <text x="555" y="143" textAnchor="middle" fontSize="15" fontWeight="700">
        Rank fusion
      </text>
      <text x="555" y="162" textAnchor="middle" fontSize="12" {...muted}>
        weighted reciprocal rank
      </text>
      <line x1="555" y1="178" x2="555" y2="194" {...stroke} strokeDasharray="3 3" />
      <text x="555" y="210" textAnchor="middle" fontSize="12" {...muted}>
        optional rerank
      </text>
      <text x="555" y="225" textAnchor="middle" fontSize="11" {...muted}>
        cross-encoder or listwise
      </text>

      <line x1="630" y1="148" x2="689" y2="148" {...stroke} markerEnd="url(#arrow)" />

      {/* Output */}
      <rect x="690" y="108" width="150" height="80" {...stroke} />
      <text x="765" y="137" textAnchor="middle" fontSize="15" fontWeight="700">
        Ranked results
      </text>
      <text x="765" y="157" textAnchor="middle" fontSize="12" {...muted}>
        or a context pack
      </text>
      <text x="765" y="172" textAnchor="middle" fontSize="12" {...muted}>
        under a token budget
      </text>
    </svg>
  );
}
