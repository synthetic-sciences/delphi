"use client";

import PageShell from "@/components/PageShell";
import {
  type ConnectorSource,
  type ContextSession,
  type ProviderDescriptor,
  type ResearchSession,
  exportContextSession,
  getWorkspaceSnapshot,
  syncConnectorSource,
} from "@/lib/api";
import {
  ArrowRight,
  Check,
  CloudOff,
  Download,
  FolderSync,
  Layers3,
  LoaderCircle,
  RefreshCw,
  Search,
  ServerCog,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

interface WorkspaceState {
  providers: ProviderDescriptor[];
  connectorProviders: ProviderDescriptor[];
  connectors: ConnectorSource[];
  researchSessions: ResearchSession[];
  contextSessions: ContextSession[];
  unavailable: string[];
}

const EMPTY_WORKSPACE: WorkspaceState = {
  providers: [],
  connectorProviders: [],
  connectors: [],
  researchSessions: [],
  contextSessions: [],
  unavailable: [],
};

const STATUS_TONES: Record<string, string> = {
  ready: "bg-[#e5eee2] text-[#496143] border-[#b8cbb2]",
  completed: "bg-[#e5eee2] text-[#496143] border-[#b8cbb2]",
  active: "bg-[#e5eee2] text-[#496143] border-[#b8cbb2]",
  running: "bg-[#faebd5] text-[#9a3f10] border-[#efc995]",
  pending: "bg-[#faebd5] text-[#9a3f10] border-[#efc995]",
  degraded: "bg-[#f3e5d9] text-[#9a5631] border-[#dec0aa]",
  failed: "bg-[#f3dfdb] text-[#8a3730] border-[#d7aaa3]",
  unavailable: "bg-[#eee5df] text-[#695954] border-[#d3c4ba]",
  cancelled: "bg-[#eee5df] text-[#695954] border-[#d3c4ba]",
  archived: "bg-[#eee5df] text-[#695954] border-[#d3c4ba]",
};

function toneFor(status: string): string {
  return (
    STATUS_TONES[status.toLowerCase()] ??
    "bg-[#efe7dd] text-[#695954] border-[#d8c8bc]"
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] ${toneFor(status)}`}
    >
      {status}
    </span>
  );
}

function formatDate(value?: string | number | null): string {
  if (value === undefined || value === null) return "not yet";
  const timestamp =
    typeof value === "number" && value < 1_000_000_000_000
      ? value * 1000
      : value;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "unknown";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: number;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-[#dfcdbf] bg-[#faf5ef] p-4">
      <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[#9a7e70]">
        {label}
      </p>
      <p className="mt-2 text-3xl font-medium tabular-nums text-[#2e2522]">
        {value}
      </p>
      <p className="mt-1 text-[10px] text-[#9a8c83]">{detail}</p>
    </div>
  );
}

function Panel({
  title,
  eyebrow,
  icon,
  children,
}: {
  title: string;
  eyebrow: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-[#dfcdbf] bg-[#faf5ef]">
      <div className="flex items-center justify-between border-b border-[#e7d9cd] px-5 py-4">
        <div>
          <p className="text-[9px] font-medium uppercase tracking-[0.18em] text-[#a88b7c]">
            {eyebrow}
          </p>
          <h2 className="mt-0.5 text-base font-medium lowercase">{title}</h2>
        </div>
        <span className="text-[#b56b3a]">{icon}</span>
      </div>
      {children}
    </section>
  );
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-5 py-8 text-center text-xs text-[#9a8c83]">
      {children}
    </div>
  );
}

export default function WorkspacePage() {
  const [workspace, setWorkspace] =
    useState<WorkspaceState>(EMPTY_WORKSPACE);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncingSources, setSyncingSources] = useState<Set<string>>(
    () => new Set()
  );
  const [exportingSessions, setExportingSessions] = useState<Set<string>>(
    () => new Set()
  );
  const [notice, setNotice] = useState<string | null>(null);
  const requestGeneration = useRef(0);

  const loadWorkspace = useCallback(async (quiet = false) => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    if (quiet) setRefreshing(true);
    else setLoading(true);
    setNotice(null);
    const snapshot = await getWorkspaceSnapshot();
    if (requestGeneration.current !== generation) return;
    setWorkspace(snapshot);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void loadWorkspace();
    return () => {
      requestGeneration.current += 1;
    };
  }, [loadWorkspace]);

  async function handleSync(sourceId: string) {
    setSyncingSources((current) => new Set(current).add(sourceId));
    setNotice(null);
    try {
      const response = await syncConnectorSource(sourceId);
      if (!response.ok) {
        setNotice("The connector sync could not be queued.");
        return;
      }
      await loadWorkspace(true);
      setNotice("Connector sync queued.");
    } catch {
      setNotice("The connector service is unavailable.");
    } finally {
      setSyncingSources((current) => {
        const next = new Set(current);
        next.delete(sourceId);
        return next;
      });
    }
  }

  async function handleExport(session: ContextSession) {
    setExportingSessions((current) =>
      new Set(current).add(session.session_id)
    );
    setNotice(null);
    try {
      const response = await exportContextSession(session.session_id);
      if (!response.ok) {
        setNotice("The context export could not be prepared.");
        return;
      }
      const payload = await response.json();
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        })
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `${session.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "context"}-r${session.current_revision}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setNotice("Context export downloaded.");
    } catch {
      setNotice("The context service is unavailable.");
    } finally {
      setExportingSessions((current) => {
        const next = new Set(current);
        next.delete(session.session_id);
        return next;
      });
    }
  }

  const readyProviders = workspace.providers.filter(
    (provider) => provider.health === "ready"
  ).length;
  const activeConnectors = workspace.connectors.filter(
    (connector) => connector.enabled
  ).length;
  const activeResearch = workspace.researchSessions.filter((session) =>
    ["pending", "running", "cancelling"].includes(session.status)
  ).length;

  return (
    <PageShell>
      <header className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <h1 className="text-2xl font-medium lowercase">workspace</h1>
            <span className="inline-flex items-center gap-1 rounded-full border border-[#c8d5c2] bg-[#edf3ea] px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-[#496143]">
              <ShieldCheck size={10} />
              private by default
            </span>
          </div>
          <p className="max-w-2xl text-sm leading-relaxed text-[#766760]">
            One operational view for provider routing, source sync, durable
            research, and reproducible working context.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadWorkspace(true)}
          disabled={loading || refreshing}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[#d9c8ba] bg-[#faf5ef] px-3 text-xs text-[#695954] transition-colors hover:border-[#c89570] hover:text-[#9a3f10] disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw
            size={13}
            className={refreshing ? "animate-spin" : undefined}
          />
          refresh
        </button>
      </header>

      <section className="relative mb-5 overflow-hidden rounded-2xl border border-[#d7c4b5] bg-[#2e2522] px-5 py-5 text-[#f7f0e8] sm:px-7">
        <div
          aria-hidden="true"
          className="absolute -right-12 -top-16 h-44 w-44 rounded-full border border-[#b58a73]/20"
        />
        <div
          aria-hidden="true"
          className="absolute -right-2 -top-12 h-28 w-28 rounded-full border border-[#b58a73]/20"
        />
        <div className="relative">
          <div className="mb-5 flex items-center justify-between gap-4">
            <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-[#d2b5a2]">
              local-first context path
            </p>
            <span className="inline-flex items-center gap-1.5 text-[10px] text-[#d8c8bc]">
              <CloudOff size={11} />
              cloud optional
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] sm:items-center">
            {[
              ["01", "sources", "local + opted-in"],
              ["02", "snapshots", "sealed inputs"],
              ["03", "context", "budgeted state"],
              ["04", "handoff", "explicit lineage"],
            ].map(([number, label, detail], index) => (
              <div key={label} className="contents">
                <div className="rounded-lg border border-[#6d574c] bg-[#392e2a] px-3 py-3">
                  <span className="font-mono text-[9px] text-[#c3865c]">
                    {number}
                  </span>
                  <p className="mt-1 text-sm font-medium lowercase">{label}</p>
                  <p className="mt-0.5 text-[9px] text-[#b9a9a0]">{detail}</p>
                </div>
                {index < 3 && (
                  <ArrowRight
                    aria-hidden="true"
                    size={14}
                    className="hidden text-[#9b7866] sm:block"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {workspace.unavailable.length > 0 && (
        <div className="mb-5 flex items-start gap-2 rounded-lg border border-[#dec0aa] bg-[#f8eadd] px-4 py-3 text-xs text-[#844a2b]">
          <CloudOff size={14} className="mt-0.5 shrink-0" />
          <p>
            Partial view: {workspace.unavailable.join(", ")} could not be
            loaded. The available local services are still shown.
          </p>
        </div>
      )}

      {notice && (
        <div
          role="status"
          className="mb-5 flex items-center gap-2 rounded-lg border border-[#d8c8bc] bg-[#efe7dd] px-4 py-2.5 text-xs text-[#695954]"
        >
          <Check size={13} />
          {notice}
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          label="ready providers"
          value={readyProviders}
          detail={`${workspace.providers.length} registered`}
        />
        <MetricCard
          label="live sources"
          value={activeConnectors}
          detail={`${workspace.connectorProviders.length} connector types`}
        />
        <MetricCard
          label="research active"
          value={activeResearch}
          detail={`${workspace.researchSessions.length} durable sessions`}
        />
        <MetricCard
          label="contexts"
          value={workspace.contextSessions.length}
          detail="revisioned and exportable"
        />
      </div>

      {loading ? (
        <div className="flex min-h-72 items-center justify-center rounded-xl border border-[#dfcdbf] bg-[#faf5ef] text-sm text-[#8a7a72]">
          <LoaderCircle size={16} className="mr-2 animate-spin" />
          loading workspace
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <Panel
            title="connector sources"
            eyebrow="ingest"
            icon={<FolderSync size={17} />}
          >
            {workspace.connectors.length === 0 ? (
              <EmptyRow>
                No connector sources yet. Local folders can stay entirely on
                this deployment.
              </EmptyRow>
            ) : (
              <div className="divide-y divide-[#eaded4]">
                {workspace.connectors.slice(0, 5).map((source) => (
                  <div key={source.source_id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="truncate text-sm font-medium text-[#2e2522]">
                            {source.display_name}
                          </p>
                          <span className="rounded bg-[#efe7dd] px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider text-[#766760]">
                            {source.provider}
                          </span>
                        </div>
                        <p className="mt-1 text-[10px] text-[#9a8c83]">
                          {source.last_synced_at
                            ? `synced ${formatDate(source.last_synced_at)}`
                            : "awaiting first sync"}
                          {source.classification
                            ? ` · ${source.classification}`
                            : ""}
                        </p>
                        {source.last_error && (
                          <p className="mt-1 line-clamp-1 text-[10px] text-[#8a3730]">
                            {source.last_error}
                          </p>
                        )}
                      </div>
                      <button
                        type="button"
                        aria-label={`Sync ${source.display_name}`}
                        onClick={() => void handleSync(source.source_id)}
                        disabled={
                          !source.enabled ||
                          syncingSources.has(source.source_id)
                        }
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#d9c8ba] px-2.5 py-1.5 text-[10px] text-[#695954] hover:border-[#c89570] hover:text-[#9a3f10] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <RefreshCw
                          size={10}
                          className={
                            syncingSources.has(source.source_id)
                              ? "animate-spin"
                              : undefined
                          }
                        />
                        sync
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel
            title="working contexts"
            eyebrow="reproduce"
            icon={<Layers3 size={17} />}
          >
            {workspace.contextSessions.length === 0 ? (
              <EmptyRow>
                No context sessions yet. Create one through the CLI, SDK, or
                MCP surface.
              </EmptyRow>
            ) : (
              <div className="divide-y divide-[#eaded4]">
                {workspace.contextSessions.slice(0, 5).map((session) => (
                  <div key={session.session_id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="truncate text-sm font-medium">
                            {session.name}
                          </p>
                          <StatusBadge status={session.status} />
                          {session.parent_session_id && (
                            <span className="font-mono text-[8px] uppercase tracking-wider text-[#a56b47]">
                              handoff
                            </span>
                          )}
                        </div>
                        <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-[#82736b]">
                          {session.objective}
                        </p>
                        <p className="mt-1.5 font-mono text-[9px] text-[#a09488]">
                          revision {session.current_revision} · write{" "}
                          {session.write_version} · {session.sharing_policy}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-label={`Export ${session.name}`}
                        onClick={() => void handleExport(session)}
                        disabled={exportingSessions.has(session.session_id)}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#d9c8ba] px-2.5 py-1.5 text-[10px] text-[#695954] hover:border-[#c89570] hover:text-[#9a3f10] disabled:cursor-wait disabled:opacity-50"
                      >
                        {exportingSessions.has(session.session_id) ? (
                          <LoaderCircle size={10} className="animate-spin" />
                        ) : (
                          <Download size={10} />
                        )}
                        export
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel
            title="provider catalog"
            eyebrow="route"
            icon={<ServerCog size={17} />}
          >
            {workspace.providers.length === 0 ? (
              <EmptyRow>No provider descriptors are available.</EmptyRow>
            ) : (
              <div className="divide-y divide-[#eaded4]">
                {workspace.providers.slice(0, 7).map((provider) => (
                  <div key={provider.name} className="px-5 py-3.5">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="truncate font-mono text-[11px] font-medium">
                            {provider.name}
                          </p>
                          <StatusBadge status={provider.health ?? "ready"} />
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {provider.capabilities.slice(0, 4).map((capability) => (
                            <span
                              key={capability}
                              className="rounded bg-[#efe7dd] px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-[#766760]"
                            >
                              {capability.replaceAll("_", " ")}
                            </span>
                          ))}
                        </div>
                      </div>
                      <span className="shrink-0 font-mono text-[9px] uppercase text-[#a09488]">
                        {provider.execution?.replaceAll("_", " ") ?? "local"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel
            title="research sessions"
            eyebrow="investigate"
            icon={<Search size={17} />}
          >
            {workspace.researchSessions.length === 0 ? (
              <EmptyRow>No durable research sessions yet.</EmptyRow>
            ) : (
              <div className="divide-y divide-[#eaded4]">
                {workspace.researchSessions.slice(0, 7).map((session) => (
                  <div key={session.session_id} className="px-5 py-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="line-clamp-2 text-xs leading-relaxed text-[#413632]">
                          {session.query}
                        </p>
                        <p className="mt-1.5 font-mono text-[9px] uppercase tracking-wider text-[#a09488]">
                          {session.mode} · {formatDate(session.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={session.status} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      )}

      <footer className="mt-5 flex flex-col gap-2 rounded-xl border border-dashed border-[#d7c4b5] px-5 py-4 text-[10px] leading-relaxed text-[#82736b] sm:flex-row sm:items-center sm:justify-between">
        <span className="inline-flex items-center gap-2">
          <Workflow size={13} className="text-[#b56b3a]" />
          Local indexing and search remain self-hostable.
        </span>
        <span>Hosted capabilities are explicit provider contracts.</span>
      </footer>
    </PageShell>
  );
}
