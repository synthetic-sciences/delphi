#!/usr/bin/env node
import { main } from "../src/index.js";

main(process.argv.slice(2)).catch((err) => {
  console.error(err?.stack || err?.message || err);
  process.exit(1);
});
