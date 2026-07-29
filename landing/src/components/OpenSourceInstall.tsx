import Link from "next/link";
import { InstallCommand } from "./InstallCommand";

export function OpenSourceInstall() {
  return (
    <section
      id="install"
      className="hairline-grid border-b border-[var(--line)] bg-[var(--bg-deep)] py-24 md:py-36"
    >
      <div className="mx-auto grid w-full max-w-[1240px] gap-14 px-5 sm:px-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end lg:gap-24">
        <div>
          <p className="eyebrow text-[var(--gold)]">Apache 2.0 · Self-hosted</p>
          <h2 className="section-title mt-5 max-w-[780px] text-[var(--fg-strong)]">
            Your index. Your source. Your deployment.
          </h2>
          <p className="mt-8 max-w-[640px] text-[17px] leading-8 text-[var(--fg-dim)]">
            Run Delphi locally or inside your own infrastructure. Use local
            sentence-transformers with no model API key, or connect hosted
            embeddings when your workload calls for them.
          </p>
        </div>

        <div className="lg:pb-2">
          <InstallCommand />
          <div className="mt-5 flex flex-wrap gap-5 font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--fg-mute)]">
            <Link
              href="https://github.com/synthetic-sciences/delphi#quick-start"
              className="hover:text-[var(--gold)]"
            >
              Installation guide →
            </Link>
            <Link
              href="https://github.com/synthetic-sciences/delphi"
              className="hover:text-[var(--gold)]"
            >
              Read the source →
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
