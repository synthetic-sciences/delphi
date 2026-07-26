import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { banner } from "../src/log.js";

const ANSI = /\u001b\[[0-9;]*m/g;
const CLI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PROJECT_ROOT = path.resolve(CLI_ROOT, "../..");
const ART = [
  "██████╗ ███████╗██╗     ██████╗ ██╗  ██╗██╗",
  "██╔══██╗██╔════╝██║     ██╔══██╗██║  ██║██║",
  "██║  ██║█████╗  ██║     ██████╔╝███████║██║",
  "██║  ██║██╔══╝  ██║     ██╔═══╝ ██╔══██║██║",
  "██████╔╝███████╗███████╗██║     ██║  ██║██║",
  "╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝",
];

function assertCentered(line, width) {
  const leadingSpaces = line.length - line.trimStart().length;
  const centeredWidth = leadingSpaces * 2 + line.trimStart().length;
  assert.ok(Math.abs(centeredWidth - width) <= 1, `"${line}" is not centered`);
}

test("banner contains only centered Delphi branding", () => {
  const lines = [];
  const originalLog = console.log;
  const originalColumns = Object.getOwnPropertyDescriptor(process.stdout, "columns");

  console.log = (...parts) => lines.push(parts.join(" "));
  Object.defineProperty(process.stdout, "columns", {
    configurable: true,
    value: 100,
  });

  try {
    banner();
  } finally {
    console.log = originalLog;
    if (originalColumns) {
      Object.defineProperty(process.stdout, "columns", originalColumns);
    } else {
      delete process.stdout.columns;
    }
  }

  const output = lines.map((line) => line.replace(ANSI, ""));
  assert.doesNotMatch(output.join("\n"), /synsci/i);
  assert.deepEqual(
    output.slice(1, 7).map((line) => line.trimStart()),
    ART,
  );

  for (const line of output.slice(1, 8)) {
    assertCentered(line, 100);
  }
});

test("README and C-locale launcher use the same centered Delphi art", async () => {
  const [readme, launcher] = await Promise.all([
    fs.readFile(path.join(PROJECT_ROOT, "README.md"), "utf8"),
    fs.readFile(path.join(PROJECT_ROOT, "scripts", "launch_app.sh"), "utf8"),
  ]);

  const readmeBanner = readme.match(/<pre align="center">\n([\s\S]*?)\n<\/pre>/);
  assert.ok(readmeBanner);
  assert.deepEqual(readmeBanner[1].split("\n"), ART);
  assert.doesNotMatch(readmeBanner[0], /synsci/i);

  const launcherBanner = launcher.match(/# Banner\n([\s\S]*?)\n# Cleanup function/);
  assert.ok(launcherBanner);
  const result = spawnSync("/bin/bash", ["-c", launcherBanner[1]], {
    encoding: "utf8",
    env: {
      COLUMNS: "100",
      LC_ALL: "C",
      NC: "",
      ORANGE: "",
      DIM: "",
      PATH: "",
    },
  });
  assert.equal(result.status, 0, result.stderr);

  const output = result.stdout.split("\n").filter((line) => line.trim());
  assert.doesNotMatch(output.join("\n"), /synsci/i);
  assert.deepEqual(
    output.slice(0, 6).map((line) => line.trimStart()),
    ART,
  );
  for (const line of output) {
    assertCentered(line, 100);
  }
});
