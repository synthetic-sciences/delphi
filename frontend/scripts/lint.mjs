import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const binary = fileURLToPath(
  new URL("../node_modules/@biomejs/biome/bin/biome", import.meta.url),
);
const baseline = JSON.parse(
  readFileSync(new URL("../biome-baseline.json", import.meta.url), "utf8"),
);

const result = spawnSync(
  process.execPath,
  [
    binary,
    "lint",
    "src",
    "scripts",
    "--reporter=json",
    "--max-diagnostics=1000",
  ],
  {
    cwd: root,
    encoding: "utf8",
  },
);

if (result.error) {
  console.error(`Unable to run Biome: ${result.error.message}`);
  process.exit(1);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch {
  process.stderr.write(result.stderr);
  process.stdout.write(result.stdout);
  console.error("Biome did not return a JSON report.");
  process.exit(1);
}

const errors = report.diagnostics.filter(
  ({ severity }) => severity === "error" || severity === "fatal",
);
const warningCounts = {};

for (const diagnostic of report.diagnostics) {
  if (diagnostic.severity !== "warning") continue;
  const key = `${diagnostic.location?.path ?? "<unknown>"}::${diagnostic.category}`;
  warningCounts[key] = (warningCounts[key] ?? 0) + 1;
}

const regressions = Object.entries(warningCounts)
  .filter(([key, count]) => count > (baseline[key] ?? 0))
  .map(
    ([key, count]) =>
      `${key}: ${count} warning(s), baseline ${baseline[key] ?? 0}`,
  );

const staleAllowances = Object.entries(baseline)
  .filter(([key, allowance]) => (warningCounts[key] ?? 0) < allowance)
  .map(
    ([key, allowance]) =>
      `${key}: ${warningCounts[key] ?? 0} warning(s), baseline ${allowance}`,
  );

if (
  errors.length > 0 ||
  regressions.length > 0 ||
  staleAllowances.length > 0 ||
  result.status !== 0
) {
  for (const diagnostic of errors) {
    console.error(
      `${diagnostic.location?.path ?? "<unknown>"}:${diagnostic.location?.start?.line ?? "?"} ${diagnostic.category}: ${diagnostic.message}`,
    );
  }
  for (const regression of regressions) {
    console.error(`Lint warning regression: ${regression}`);
  }
  for (const staleAllowance of staleAllowances) {
    console.error(`Remove stale lint allowance: ${staleAllowance}`);
  }
  process.exit(1);
}

const warnings = Object.values(warningCounts).reduce(
  (total, count) => total + count,
  0,
);
const allowance = Object.values(baseline).reduce(
  (total, count) => total + count,
  0,
);

console.log(
  `Biome passed: 0 errors; ${warnings}/${allowance} bounded baseline warnings.`,
);
