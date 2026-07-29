import rawTraces from "@/lib/traces.json";
import { QueryTrace, type RetrievalTrace } from "./TraceDisclosure";

/* Every trace on this page is a real query against the benchmarked build,
 * captured by harness/capture_traces.py and committed verbatim. Cases are
 * taken by position in the split rather than chosen by outcome, so the
 * failures are here alongside the wins. */

const TRACES = rawTraces as unknown as RetrievalTrace[];

export function TraceGallery({ workflow }: { workflow?: string }) {
  const traces = workflow
    ? TRACES.filter((trace) => trace.workflow === workflow)
    : TRACES;

  if (!traces.length) return null;

  return (
    <div className="not-prose mt-8">
      <p className="figure-heading">
        <span>Retrieval traces</span>
        <span>{traces.length} queries · expand to inspect</span>
      </p>
      {traces.map((trace) => (
        <QueryTrace key={trace.sampleId} trace={trace} />
      ))}
    </div>
  );
}
