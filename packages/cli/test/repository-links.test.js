import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const CLI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PROJECT_ROOT = path.resolve(CLI_ROOT, "../..");
const REPOSITORY_URL = "https://github.com/synthetic-sciences/delphi";
const MISSPELLED_REPOSITORY = new RegExp("synthetic-sciences/del" + "hpi");

test("installer and documentation use the canonical Delphi repository", async () => {
  const files = await Promise.all(
    [
      path.join(PROJECT_ROOT, "README.md"),
      path.join(CLI_ROOT, "README.md"),
      path.join(CLI_ROOT, "src", "source.js"),
      path.join(CLI_ROOT, "package.json"),
    ].map((file) => fs.readFile(file, "utf8")),
  );

  for (const content of files) {
    assert.doesNotMatch(content, MISSPELLED_REPOSITORY);
    assert.match(content, /synthetic-sciences\/delphi/);
  }

  const packageJson = JSON.parse(files[3]);
  assert.equal(packageJson.repository.url, REPOSITORY_URL);
  assert.equal(packageJson.homepage, REPOSITORY_URL);
});

test("CLI docs describe the actual remote-default branch behavior", async () => {
  const readme = await fs.readFile(path.join(CLI_ROOT, "README.md"), "utf8");

  assert.match(
    readme,
    /\| `SYNSCI_DELPHI_REF` \| remote default \| Branch \/ tag to pull \|/,
  );
});
