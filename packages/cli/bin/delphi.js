#!/usr/bin/env node
import { main } from "../src/index.js";
import { humanize } from "../src/error-hints.js";

main(process.argv.slice(2)).catch((err) => {
  // Stack first so the technical context is preserved for bug reports,
  // then the humanized hint at the bottom (where eyeballs land last).
  console.error(err?.stack || err?.message || err);
  const hint = humanize(err?.message || String(err));
  if (hint) {
    console.error("");
    for (const line of hint.split("\n")) {
      console.error("  " + line);
    }
  }
  process.exit(1);
});
