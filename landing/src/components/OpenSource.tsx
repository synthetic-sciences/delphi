import { Container } from "./Container";

export function OpenSource() {
  return (
    <section className="py-20 md:py-28 border-t border-[var(--line)]">
      <Container>
        <h2 className="font-serif text-[34px] md:text-[44px] leading-[1.1] tracking-[-0.01em] text-[var(--fg-strong)] max-w-[680px]">
          Apache 2.0.
        </h2>

        <div className="prose mt-10 text-[17.5px] leading-[1.7] text-[var(--fg-dim)] max-w-[680px] space-y-5">
          <p>
            Delphi runs on your laptop, in your VPC, or anywhere Docker
            runs. Your index lives on your hardware. No telemetry, no
            auth wall, no rate limit.
          </p>
          <p>
            <a
              className="quiet"
              href="https://github.com/synthetic-sciences/delphi"
            >
              github.com/synthetic-sciences/delphi
            </a>
            . Issues, pull requests, and forks all welcome.
          </p>
        </div>
      </Container>
    </section>
  );
}
