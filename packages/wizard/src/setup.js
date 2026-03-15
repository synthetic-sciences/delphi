#!/usr/bin/env node

// ═══════════════════════════════════════════════════════════════════════════════
//  SynSc Context — CLI Setup Wizard
//  One command to connect your AI agent to code repos & research papers.
//  Usage: npx synsc-context
// ═══════════════════════════════════════════════════════════════════════════════

import chalk from 'chalk';
import gradient from 'gradient-string';
import ora from 'ora';
import prompts from 'prompts';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { homedir, platform } from 'os';
import { join } from 'path';
import open from 'open';

// ─── Config ──────────────────────────────────────────────────────────────────
const SYNSC_API = process.env.SYNSC_API || 'https://synsc-context.onrender.com';
const SYNSC_WEB = process.env.SYNSC_WEB || 'https://context.syntheticsciences.ai';
const SYNSC_MCP = process.env.SYNSC_MCP || `${SYNSC_API}/mcp`;
const VERSION = '1.1.0';

// ─── Gradients ───────────────────────────────────────────────────────────────
const synscGradient = gradient(['#6366f1', '#8b5cf6', '#a855f7', '#d946ef']);
const successGradient = gradient(['#10b981', '#34d399', '#6ee7b7']);
const warnGradient = gradient(['#f59e0b', '#fbbf24']);
const errorGradient = gradient(['#ef4444', '#f87171']);
const cyanGrad = gradient(['#06b6d4', '#22d3ee', '#67e8f9']);

// ─── ASCII Banner ────────────────────────────────────────────────────────────
const BANNER = `
════════════════════════════════════════════════════════════════════
   ███████╗██╗   ██╗███╗   ██╗███████╗ ██████╗██╗
   ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔════╝██║
   ███████╗ ╚████╔╝ ██╔██╗ ██║███████╗██║     ██║
   ╚════██║  ╚██╔╝  ██║╚██╗██║╚════██║██║     ██║
   ███████║   ██║   ██║ ╚████║███████║╚██████╗██║
   ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚══════╝ ╚═════╝╚═╝
════════════════════════════════════════════════════════════════════`;

const TAGLINE = '  Unified Context for AI Agents — Code Repos & Research Papers';

// ─── Helpers ─────────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function box(text, { padding = 1, borderColor = 'dim', title = '' } = {}) {
  const lines = text.split('\n');
  const maxLen = Math.max(...lines.map((l) => stripAnsi(l).length));
  const width = maxLen + padding * 2;
  const horizontal = '─'.repeat(width + 2);
  const pad = ' '.repeat(padding);

  const colorFn = borderColor === 'green' ? chalk.green
    : borderColor === 'cyan' ? chalk.cyan
    : borderColor === 'yellow' ? chalk.yellow
    : borderColor === 'magenta' ? chalk.magenta
    : chalk.dim;

  const topLine = title
    ? colorFn('╭─') + colorFn(` ${title} `) + colorFn('─'.repeat(Math.max(0, width - title.length - 2))) + colorFn('╮')
    : colorFn(`╭${horizontal}╮`);

  const botLine = colorFn(`╰${horizontal}╯`);

  const body = lines.map((line) => {
    const visLen = stripAnsi(line).length;
    const rightPad = ' '.repeat(Math.max(0, maxLen - visLen));
    return colorFn('│') + pad + ' ' + line + rightPad + pad + ' ' + colorFn('│');
  });

  return [topLine, ...body, botLine].join('\n');
}

function stripAnsi(str) {
  return str.replace(
    /[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d/#&.:=?%@~_]*)*)?\u0007)|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g,
    ''
  );
}

function separator(label = '') {
  const width = 62;
  if (!label) return chalk.dim('─'.repeat(width));
  const side = Math.max(0, Math.floor((width - label.length - 4) / 2));
  return chalk.dim('─'.repeat(side) + '  ') + chalk.bold.white(label) + chalk.dim('  ' + '─'.repeat(side));
}

function step(num, total, label) {
  const filled = '●';
  const empty = '○';
  const dots = Array.from({ length: total }, (_, i) =>
    i < num ? chalk.magenta(filled) : chalk.dim(empty)
  ).join(' ');
  return `\n  ${dots}  ${chalk.bold(label)}\n`;
}

/** Cross-platform MCP config paths */
function getConfigPaths() {
  const home = homedir();
  const os = platform();

  const paths = {
    cursor: join(home, '.cursor', 'mcp.json'),
    windsurf: join(home, '.windsurf', 'mcp.json'),
    vscode: join(home, '.vscode', 'mcp.json'),
  };

  // Claude Desktop has different paths per OS
  if (os === 'darwin') {
    paths.claude = join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json');
  } else if (os === 'win32') {
    paths.claude = join(process.env.APPDATA || join(home, 'AppData', 'Roaming'), 'Claude', 'claude_desktop_config.json');
  } else {
    paths.claude = join(home, '.config', 'claude', 'claude_desktop_config.json');
  }

  return paths;
}

// ─── Health Check ────────────────────────────────────────────────────────────
async function checkServerHealth() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(`${SYNSC_API}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    if (res.ok) {
      const data = await res.json();
      return { ok: true, data };
    }
    return { ok: false };
  } catch {
    return { ok: false };
  }
}

// ─── GitHub OAuth Device Flow ────────────────────────────────────────────────
async function authenticateWithGitHub() {
  const spinner = ora({
    text: chalk.dim('Initiating GitHub authentication…'),
    spinner: 'arc',
    color: 'magenta',
  }).start();

  try {
    const startResponse = await fetch(`${SYNSC_API}/api/cli/auth/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!startResponse.ok) {
      throw new Error(`Server returned ${startResponse.status}: ${startResponse.statusText}`);
    }

    const authData = await startResponse.json();
    spinner.stop();

    const { device_code, user_code, verification_url, expires_in, interval } = authData;

    // Show code in a pretty box
    console.log();
    console.log(
      box(
        `${chalk.dim('Your verification code:')}\n\n    ${chalk.bold.cyan.underline(user_code)}`,
        { title: '🔑 GitHub Auth', borderColor: 'cyan', padding: 2 }
      )
    );
    console.log();

    console.log(chalk.dim('  Opening browser to complete authentication…'));
    console.log(chalk.dim(`  If it doesn't open, visit: ${verification_url || `${SYNSC_WEB}/cli-auth`}?cli_code=${user_code}`));
    console.log();

    const authUrl = `${SYNSC_WEB}/cli-auth?cli_code=${user_code}`;
    await open(authUrl);

    const pollSpinner = ora({
      text: chalk.dim('Waiting for you to authenticate in the browser…'),
      spinner: 'dots12',
      color: 'cyan',
    }).start();

    const startTime = Date.now();
    const maxWaitTime = (expires_in || 600) * 1000;
    const pollInterval = (interval || 5) * 1000;

    while (Date.now() - startTime < maxWaitTime) {
      await sleep(pollInterval);

      try {
        const statusRes = await fetch(`${SYNSC_API}/api/cli/auth/status/${device_code}`);
        const statusData = await statusRes.json();

        if (statusData.status === 'completed') {
          pollSpinner.succeed(chalk.green('Authentication successful!'));
          return {
            api_key: statusData.api_key,
            user_name: statusData.user_name,
            user_email: statusData.user_email,
          };
        }

        if (statusData.status === 'expired') {
          pollSpinner.fail(chalk.red('Session expired. Please try again.'));
          return null;
        }
      } catch {
        // Network hiccup — keep polling
      }
    }

    pollSpinner.fail(chalk.red('Timed out waiting for authentication.'));
    return null;
  } catch (error) {
    spinner.fail(chalk.red('Failed to start authentication'));
    console.log(errorGradient(`\n  Error: ${error.message}\n`));
    return null;
  }
}

// ─── MCP Config Writer ──────────────────────────────────────────────────────
function writeMcpConfig(agent, configPaths, mcpEntry) {
  const configPath = configPaths[agent];
  const configDir = join(configPath, '..');

  if (!existsSync(configDir)) {
    mkdirSync(configDir, { recursive: true });
  }

  let existingConfig = {};

  if (existsSync(configPath)) {
    try {
      const raw = readFileSync(configPath, 'utf-8');
      existingConfig = JSON.parse(raw);
      const existingCount = Object.keys(existingConfig.mcpServers || {}).length;
      console.log(chalk.dim(`\n  Found existing config with ${existingCount} MCP server(s)`));
    } catch (parseErr) {
      console.log(warnGradient(`\n  ⚠ Could not parse existing config (${parseErr.message})`));
      const backupPath = `${configPath}.backup.${Date.now()}`;
      writeFileSync(backupPath, readFileSync(configPath, 'utf-8'));
      console.log(chalk.dim(`  Backup saved → ${backupPath}`));
    }
  }

  const existingServers = existingConfig.mcpServers || {};
  const mergedConfig = {
    ...existingConfig,
    mcpServers: {
      ...existingServers,
      'synsc-context': mcpEntry,
    },
  };

  writeFileSync(configPath, JSON.stringify(mergedConfig, null, 2));

  const total = Object.keys(mergedConfig.mcpServers).length;
  const preserved = Object.keys(existingServers).filter((s) => s !== 'synsc-context');

  console.log(chalk.green(`\n  ✓ Configuration saved → ${chalk.underline(configPath)}`));
  if (preserved.length > 0) {
    console.log(chalk.green(`  ✓ Preserved existing servers: ${preserved.join(', ')}`));
  }
  console.log(chalk.green(`  ✓ Total MCP servers: ${total}`));
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MAIN
// ═══════════════════════════════════════════════════════════════════════════════

async function main() {
  // ── Banner ───────────────────────────────────────────────────────────────
  console.clear();
  console.log(synscGradient(BANNER));
  console.log(cyanGrad(TAGLINE));
  console.log(chalk.dim(`\n  v${VERSION}  •  ${SYNSC_WEB}\n`));
  console.log(separator());

  // ── Health Check ─────────────────────────────────────────────────────────
  const healthSpinner = ora({
    text: chalk.dim('Checking SynSc server status…'),
    spinner: 'dots',
    color: 'cyan',
  }).start();

  const health = await checkServerHealth();

  if (health.ok) {
    const d = health.data;
    healthSpinner.succeed(
      chalk.green('SynSc server is online') +
        chalk.dim(` (${d.database_backend || 'postgresql'} + ${d.vector_backend || 'pgvector'})`)
    );
  } else {
    healthSpinner.warn(
      chalk.yellow('Could not reach SynSc server — setup will continue anyway')
    );
  }

  console.log();

  // ════════════════════════════════════════════════════════════════════════
  //  STEP 1 — Authentication
  // ════════════════════════════════════════════════════════════════════════
  console.log(step(1, 3, 'Authentication'));
  console.log(separator('STEP 1 · AUTHENTICATE'));
  console.log();

  const authChoice = await prompts({
    type: 'select',
    name: 'method',
    message: 'How would you like to authenticate?',
    choices: [
      {
        title: `${chalk.bold('Sign in with GitHub')}  ${chalk.dim('— recommended')}`,
        value: 'github',
      },
      {
        title: `${chalk.bold('Enter existing API key')}`,
        value: 'existing',
      },
    ],
    hint: '↑/↓ to select, enter to confirm',
  });

  if (!authChoice.method) {
    console.log(errorGradient('\n  Setup cancelled.\n'));
    process.exit(0);
  }

  let apiKey = null;
  let userName = null;

  if (authChoice.method === 'github') {
    // ── GitHub OAuth Flow ────────────────────────────────────────────────
    const result = await authenticateWithGitHub();

    if (!result) {
      console.log(errorGradient('\n  Authentication failed. Run the command again to retry.\n'));
      process.exit(1);
    }

    apiKey = result.api_key;
    userName = result.user_name;

    console.log();
    if (userName) {
      console.log(successGradient(`  Welcome back, ${userName}!`));
    }

    // Show API key in a box
    console.log();
    console.log(
      box(
        `${chalk.dim('Your API Key (save this!):\n')}\n  ${chalk.green.bold(apiKey)}`,
        { title: '🔐 API Key', borderColor: 'green', padding: 2 }
      )
    );
    console.log(chalk.yellow('\n  ⚠  Save this key — you will not see it again.\n'));

  } else {
    // ── Existing Key ─────────────────────────────────────────────────────
    const keyInput = await prompts({
      type: 'password',
      name: 'key',
      message: 'Enter your API key:',
      validate: (v) => {
        if (!v) return 'API key is required';
        if (v.startsWith('synsc_') || v.startsWith('ink_') || v.startsWith('ghctx_')) return true;
        return 'API key should start with synsc_, ink_, or ghctx_';
      },
    });

    if (!keyInput.key) {
      console.log(errorGradient('\n  Setup cancelled.\n'));
      process.exit(0);
    }

    apiKey = keyInput.key;
    console.log(chalk.green('\n  ✓ API key accepted\n'));
  }

  // ════════════════════════════════════════════════════════════════════════
  //  STEP 2 — Choose AI Agent
  // ════════════════════════════════════════════════════════════════════════
  console.log(step(2, 3, 'Configure AI Agent'));
  console.log(separator('STEP 2 · AI AGENT'));
  console.log();

  const agentChoice = await prompts({
    type: 'select',
    name: 'agent',
    message: 'Which AI agent do you use?',
    choices: [
      { title: `${chalk.magenta('⎔')} ${chalk.bold('Cursor')}        ${chalk.dim('— AI code editor')}`, value: 'cursor' },
      { title: `${chalk.yellow('◆')} ${chalk.bold('Claude Desktop')} ${chalk.dim('— Anthropic desktop app')}`, value: 'claude' },
      { title: `${chalk.cyan('◈')} ${chalk.bold('Windsurf')}       ${chalk.dim('— Codeium editor')}`, value: 'windsurf' },
      { title: `${chalk.blue('◇')} ${chalk.bold('VS Code')}        ${chalk.dim('— with MCP extension')}`, value: 'vscode' },
      { title: `${chalk.dim('◻')} ${chalk.bold('Manual')}         ${chalk.dim('— show config to copy')}`, value: 'manual' },
    ],
    hint: '↑/↓ to select',
  });

  if (!agentChoice.agent) {
    console.log(errorGradient('\n  Setup cancelled.\n'));
    process.exit(0);
  }

  // ── Connection mode: local (uvx stdio) or remote (HTTP URL) ────────
  const modeChoice = await prompts({
    type: 'select',
    name: 'mode',
    message: 'How should the MCP server connect?',
    choices: [
      {
        title: `${chalk.bold('Remote (URL)')}  ${chalk.dim('— connects directly to hosted server')}`,
        value: 'remote',
      },
      {
        title: `${chalk.bold('Local (uvx)')}   ${chalk.dim('— runs a local proxy via stdio')}`,
        value: 'local',
      },
    ],
    hint: '↑/↓ to select',
  });

  if (!modeChoice.mode) {
    console.log(errorGradient('\n  Setup cancelled.\n'));
    process.exit(0);
  }

  let mcpEntry;
  if (modeChoice.mode === 'remote') {
    mcpEntry = {
      url: SYNSC_MCP,
      headers: {
        Authorization: `Bearer ${apiKey}`,
      },
    };
  } else {
    mcpEntry = {
      command: 'uvx',
      args: ['synsc-context-proxy'],
      env: {
        SYNSC_API_KEY: apiKey,
      },
    };
  }

  const fullMcpConfig = {
    mcpServers: {
      'synsc-context': mcpEntry,
    },
  };

  const configPaths = getConfigPaths();

  console.log();

  if (agentChoice.agent === 'manual') {
    // ── Manual Config ──────────────────────────────────────────────────
    console.log(chalk.bold('  Add this to your MCP configuration:\n'));
    console.log(
      box(JSON.stringify(fullMcpConfig, null, 2), {
        title: 'mcp.json',
        borderColor: 'cyan',
        padding: 1,
      })
    );
    console.log();
    console.log(chalk.dim('  Configuration file locations:'));
    console.log(chalk.dim(`    Cursor:        ${configPaths.cursor}`));
    console.log(chalk.dim(`    Claude Desktop: ${configPaths.claude}`));
    console.log(chalk.dim(`    Windsurf:      ${configPaths.windsurf}`));
    console.log(chalk.dim(`    VS Code:       ${configPaths.vscode}`));
    console.log();
  } else {
    // ── Auto-configure ─────────────────────────────────────────────────
    const agentNames = {
      cursor: 'Cursor',
      claude: 'Claude Desktop',
      windsurf: 'Windsurf',
      vscode: 'VS Code',
    };

    const confirm = await prompts({
      type: 'confirm',
      name: 'write',
      message: `Write SynSc Context config to ${agentNames[agentChoice.agent]}?`,
      initial: true,
    });

    if (confirm.write) {
      try {
        writeMcpConfig(agentChoice.agent, configPaths, mcpEntry);
      } catch (err) {
        console.log(chalk.red(`\n  ✗ Failed to write config: ${err.message}`));
        console.log(chalk.dim('\n  Add this manually instead:\n'));
        console.log(
          box(JSON.stringify(fullMcpConfig, null, 2), {
            title: 'mcp.json',
            borderColor: 'yellow',
            padding: 1,
          })
        );
        console.log(chalk.dim(`\n  File: ${configPaths[agentChoice.agent]}\n`));
      }
    } else {
      console.log(chalk.dim('\n  Skipped auto-config. Add manually:\n'));
      console.log(
        box(JSON.stringify(fullMcpConfig, null, 2), {
          title: 'mcp.json',
          borderColor: 'cyan',
          padding: 1,
        })
      );
      console.log(chalk.dim(`\n  File: ${configPaths[agentChoice.agent]}\n`));
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  STEP 3 — Done!
  // ════════════════════════════════════════════════════════════════════════
  console.log(step(3, 3, 'All Done'));
  console.log(separator('SETUP COMPLETE'));
  console.log();

  const doneBox = [
    `${chalk.green.bold('✓')} ${chalk.bold('SynSc Context is ready!')}`,
    '',
    `${chalk.dim('Restart your AI agent, then try:')}`,
    '',
    `  ${chalk.cyan('▸')} ${chalk.white('"Index this repo: https://github.com/facebook/react"')}`,
    `  ${chalk.cyan('▸')} ${chalk.white('"Search for how useState works"')}`,
    `  ${chalk.cyan('▸')} ${chalk.white('"Index this paper: https://arxiv.org/abs/2301.07041"')}`,
    `  ${chalk.cyan('▸')} ${chalk.white('"Index this dataset: openai/gsm8k"')}`,
    '',
    `${chalk.dim('Dashboard:')} ${chalk.underline.cyan(SYNSC_WEB)}`,
    `${chalk.dim('Docs:     ')} ${chalk.underline.cyan(SYNSC_WEB + '/docs')}`,
  ].join('\n');

  console.log(box(doneBox, { title: '🚀 Ready', borderColor: 'magenta', padding: 2 }));
  console.log();
  console.log(synscGradient('  Thanks for using SynSc Context!'));
  console.log(chalk.dim('  Star us on GitHub → https://github.com/inkvell/synsc-context\n'));
}

// ─── Run ─────────────────────────────────────────────────────────────────────
main().catch((err) => {
  console.error(chalk.red(`\n  Fatal error: ${err.message}\n`));
  if (process.env.DEBUG) {
    console.error(err.stack);
  }
  process.exit(1);
});
