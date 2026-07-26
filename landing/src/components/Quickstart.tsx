import { Container } from "./Container";

const CODE = `# install + run locally
$ npx @synsci/delphi

# index a repository, auto-discovering its docs
$ delphi index github.com/fastapi/fastapi --auto-docs

# the MCP config for Claude Code / Cursor / Windsurf
# was written automatically. restart your agent.`;

export function Quickstart() {
  return (
    <section
      id="quickstart"
      className="py-20 md:py-28 border-t border-[var(--line)]"
    >
      <Container>
        <h2 className="font-serif text-[34px] md:text-[44px] leading-[1.1] tracking-[-0.01em] text-[var(--fg-strong)] max-w-[680px]">
          Quickstart.
        </h2>

        <div className="prose mt-10 text-[17.5px] leading-[1.7] text-[var(--fg-dim)] max-w-[680px] space-y-4">
          <p>
            One command. No accounts, no API keys, no cloud. The installer
            writes the MCP config for every agent it finds on your machine
            and brings up the local index.
          </p>
        </div>

        <pre className="mt-10 max-w-[720px] p-6 border border-[var(--line)] bg-[var(--code-bg)] rounded-[4px] overflow-x-auto font-mono text-[13.5px] leading-[1.7]">
          {CODE.split("\n").map((line, i) => {
            if (line.startsWith("#")) {
              return (
                <span key={i} className="block text-[var(--fg-mute)]">
                  {line}
                </span>
              );
            }
            if (line.startsWith("$")) {
              const [, ...rest] = line.split(" ");
              return (
                <span key={i} className="block">
                  <span className="text-[var(--fg-mute)]">$</span>{" "}
                  <span className="text-[var(--fg)]">{rest.join(" ")}</span>
                </span>
              );
            }
            return (
              <span key={i} className="block">
                &nbsp;
              </span>
            );
          })}
        </pre>

        <p className="mt-8 text-[14px] text-[var(--fg-mute)] max-w-[680px] italic">
          Prefer Docker or the Python client?{" "}
          <a
            className="quiet"
            href="https://github.com/synthetic-sciences/delphi#manual-install-from-source"
          >
            See the install guide
          </a>
          .
        </p>
      </Container>
    </section>
  );
}
