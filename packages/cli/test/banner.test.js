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
const BRAND = "⚛  Delphi";

test("banner uses the Synthetic Sciences mark with the Delphi name", () => {
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
  assert.equal(output[1].trim(), BRAND);
  assert.equal(output.filter((line) => line.trim()).length, 1);
});

test("README and launcher use the same compact branding", async () => {
  const [readme, launcher] = await Promise.all([
    fs.readFile(path.join(PROJECT_ROOT, "README.md"), "utf8"),
    fs.readFile(path.join(PROJECT_ROOT, "scripts", "launch_app.sh"), "utf8"),
  ]);

  assert.match(readme, /frontend\/public\/icon\.svg/);
  assert.match(readme, /> Delphi\s*<\/h1>/);

  const launcherBanner = launcher.match(/# Banner\n([\s\S]*?)\n# Cleanup function/);
  assert.ok(launcherBanner);
  const result = spawnSync("/bin/bash", ["-c", launcherBanner[1]], {
    encoding: "utf8",
    env: {
      COLUMNS: "100",
      LC_ALL: "C.UTF-8",
      NC: "",
      ORANGE: "",
      DIM: "",
      PATH: "",
    },
  });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), BRAND);
});
