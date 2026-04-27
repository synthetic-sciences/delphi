import pc from "picocolors";
import { runInit } from "./init.js";
import { runConfig } from "./config.js";
import { runReload } from "./reload.js";
import { runStart, runStop, runStatus, runLogs, runOpen, runUninstall } from "./lifecycle.js";
import { loadState } from "./env.js";

const HELP = `${pc.bold("delphi")} ${pc.dim("— semantic context for AI coding agents")}

Usage
  npx @synsci/delphi [command] [options]
  delphi [command]               (after install)

Commands
  (none)         Open the dashboard if installed; otherwise run init
  init           Set up Delphi: pick path, embeddings, configure clients
  config         Edit provider, model, keys, or dashboard password
  reload         Restart api + worker so they pick up .env changes
  open           Open the dashboard (starts the stack if it's not running)
  start          Start the Docker stack
  stop           Stop the Docker stack
  status         Print health + container status
  logs [-f]      Tail container logs (-f to follow)
  uninstall      Tear down containers and remove the data volume
  help           Show this message

Environment
  SYNSCI_DELPHI_HOME     Override install dir (default ~/.synsci/delphi)
  SYNSCI_DELPHI_REPO     Override source repo URL
  SYNSCI_DELPHI_REF      Override branch/tag (default: remote HEAD)
  SYNSCI_DELPHI_API_URL  Override API URL the CLI talks to (default http://localhost:8742)

Run \`npx @synsci/delphi init\` to get started.
`;

function parseFlags(argv) {
  const flags = {};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-f" || a === "--follow") flags.follow = true;
    else if (a === "--force") flags.force = true;
    else if (a === "--service" || a === "-s") {
      flags.services = flags.services || [];
      flags.services.push(argv[++i]);
    } else positional.push(a);
  }
  return { flags, positional };
}

export async function main(argv) {
  // Smart default: bare `delphi`/`npx @synsci/delphi` opens the dashboard if
  // already installed, otherwise runs init.
  if (argv.length === 0) {
    const state = await loadState();
    return state ? runOpen() : runInit({ force: false });
  }

  const [cmd, ...rest] = argv;
  const { flags } = parseFlags(rest);

  switch (cmd) {
    case "init":
      return runInit({ force: !!flags.force });
    case "config":
      return runConfig();
    case "reload":
      return runReload();
    case "open":
      return runOpen();
    case "start":
      return runStart();
    case "stop":
      return runStop();
    case "status":
      return runStatus();
    case "logs":
      return runLogs({ follow: !!flags.follow, services: flags.services || [] });
    case "uninstall":
      return runUninstall();
    case "help":
    case "--help":
    case "-h":
      console.log(HELP);
      return;
    case "version":
    case "--version":
    case "-v": {
      const { readFile } = await import("node:fs/promises");
      const { fileURLToPath } = await import("node:url");
      const path = await import("node:path");
      const here = path.dirname(fileURLToPath(import.meta.url));
      const pkg = JSON.parse(await readFile(path.join(here, "..", "package.json"), "utf8"));
      console.log(pkg.version);
      return;
    }
    default:
      console.error(pc.red(`Unknown command: ${cmd}`));
      console.error(HELP);
      process.exit(2);
  }
}
