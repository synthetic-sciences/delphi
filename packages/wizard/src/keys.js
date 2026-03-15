#!/usr/bin/env node

// ═══════════════════════════════════════════════════════════════════════════════
//  SynSc Context — API Key Manager CLI
//  Manage API keys for your AI agents.
//  Usage: npx synsc-context-keys
// ═══════════════════════════════════════════════════════════════════════════════

import chalk from 'chalk';
import gradient from 'gradient-string';
import ora from 'ora';
import prompts from 'prompts';
import open from 'open';

// ─── Config ──────────────────────────────────────────────────────────────────
const SYNSC_API = process.env.SYNSC_API || 'https://synsc-context.onrender.com';
const SYNSC_WEB = process.env.SYNSC_WEB || 'https://context.syntheticsciences.ai';
const VERSION = '1.1.0';

// ─── Gradients ───────────────────────────────────────────────────────────────
const synscGradient = gradient(['#6366f1', '#8b5cf6', '#a855f7', '#d946ef']);
const successGradient = gradient(['#10b981', '#34d399', '#6ee7b7']);
const warnGradient = gradient(['#f59e0b', '#fbbf24']);
const errorGradient = gradient(['#ef4444', '#f87171']);
const cyanGrad = gradient(['#06b6d4', '#22d3ee', '#67e8f9']);

// ─── ASCII Banner ────────────────────────────────────────────────────────────
const BANNER = `
════════════════════════════════════════════════════════════════
   ███████╗██╗   ██╗███╗   ██╗███████╗ ██████╗
   ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔════╝
   ███████╗ ╚████╔╝ ██╔██╗ ██║███████╗██║     
   ╚════██║  ╚██╔╝  ██║╚██╗██║╚════██║██║     
   ███████║   ██║   ██║ ╚████║███████║╚██████╗
   ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚══════╝ ╚═════╝
════════════════════════════════════════════════════════════════`;

const TAGLINE = '       🔑  API Key Manager  —  Manage keys for your AI agents';

// ─── Helpers ─────────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function stripAnsi(str) {
  return str.replace(
    /[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d/#&.:=?%@~_]*)*)?\u0007)|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g,
    ''
  );
}

function box(text, { padding = 1, borderColor = 'dim', title = '' } = {}) {
  const lines = text.split('\n');
  const maxLen = Math.max(...lines.map((l) => stripAnsi(l).length));
  const width = maxLen + padding * 2;
  const horizontal = '─'.repeat(width + 2);
  const pad = ' '.repeat(padding);

  const colorFn =
    borderColor === 'green' ? chalk.green
    : borderColor === 'cyan' ? chalk.cyan
    : borderColor === 'yellow' ? chalk.yellow
    : borderColor === 'magenta' ? chalk.magenta
    : borderColor === 'red' ? chalk.red
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

function separator(label = '') {
  const width = 62;
  if (!label) return chalk.dim('─'.repeat(width));
  const side = Math.max(0, Math.floor((width - label.length - 4) / 2));
  return chalk.dim('─'.repeat(side) + '  ') + chalk.bold.white(label) + chalk.dim('  ' + '─'.repeat(side));
}

// ─── API Helpers ─────────────────────────────────────────────────────────────

async function apiRequest(method, path, { apiKey, body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }

  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  opts.signal = controller.signal;

  try {
    const res = await fetch(`${SYNSC_API}${path}`, opts);
    clearTimeout(timeout);
    const data = await res.json();
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    clearTimeout(timeout);
    return { ok: false, status: 0, data: { error: err.message } };
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
    const { ok, data: authData } = await apiRequest('POST', '/api/cli/auth/start');

    if (!ok) {
      throw new Error(`Server returned error: ${authData.error || 'unknown'}`);
    }

    spinner.stop();

    const { device_code, user_code, expires_in, interval } = authData;

    console.log();
    console.log(
      box(
        `${chalk.dim('Your verification code:')}\n\n    ${chalk.bold.cyan.underline(user_code)}`,
        { title: '🔑 GitHub Auth', borderColor: 'cyan', padding: 2 }
      )
    );
    console.log();
    console.log(chalk.dim('  Opening browser to complete authentication…'));
    console.log(chalk.dim(`  If it doesn't open, visit: ${SYNSC_WEB}/cli-auth?cli_code=${user_code}`));
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
        const { data: statusData } = await apiRequest('GET', `/api/cli/auth/status/${device_code}`);

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

// ─── Authenticate (shared) ──────────────────────────────────────────────────

async function authenticate() {
  console.log();
  console.log(separator('AUTHENTICATE'));
  console.log();

  const authChoice = await prompts({
    type: 'select',
    name: 'method',
    message: 'How would you like to authenticate?',
    choices: [
      {
        title: `${chalk.bold('Sign in with GitHub')}  ${chalk.dim('— recommended, opens browser')}`,
        value: 'github',
      },
      {
        title: `${chalk.bold('Enter existing API key')}  ${chalk.dim('— if you already have one')}`,
        value: 'existing',
      },
    ],
    hint: '↑/↓ to select, enter to confirm',
  });

  if (!authChoice.method) {
    console.log(errorGradient('\n  Cancelled.\n'));
    process.exit(0);
  }

  if (authChoice.method === 'github') {
    const result = await authenticateWithGitHub();
    if (!result) {
      console.log(errorGradient('\n  Authentication failed. Run the command again to retry.\n'));
      process.exit(1);
    }

    if (result.user_name) {
      console.log(successGradient(`\n  Welcome, ${result.user_name}!`));
    }
    console.log();

    return result.api_key;
  }

  // Existing key
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
    console.log(errorGradient('\n  Cancelled.\n'));
    process.exit(0);
  }

  console.log(chalk.green('  ✓ API key accepted\n'));
  return keyInput.key;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ACTIONS
// ═══════════════════════════════════════════════════════════════════════════════

// ─── Create Key ──────────────────────────────────────────────────────────────

async function actionCreateKey(apiKey) {
  console.log();
  console.log(separator('CREATE NEW API KEY'));
  console.log();

  const input = await prompts({
    type: 'text',
    name: 'name',
    message: 'Name for this key (e.g. "Cursor", "Work Laptop"):',
    initial: 'API Key',
    validate: (v) => (v.trim() ? true : 'Name is required'),
  });

  if (!input.name) {
    console.log(chalk.dim('\n  Cancelled.\n'));
    return;
  }

  const spinner = ora({
    text: chalk.dim('Creating API key…'),
    spinner: 'dots',
    color: 'magenta',
  }).start();

  const { ok, data } = await apiRequest('POST', '/v1/keys', {
    apiKey,
    body: { name: input.name.trim() },
  });

  if (ok && data.success) {
    spinner.succeed(chalk.green('API key created!'));

    console.log();
    console.log(
      box(
        [
          `${chalk.dim('Name:')}     ${chalk.white(data.name)}`,
          `${chalk.dim('Key ID:')}   ${chalk.white(data.key_id)}`,
          '',
          `${chalk.dim('API Key:')}`,
          '',
          `  ${chalk.green.bold(data.key)}`,
        ].join('\n'),
        { title: '🔐 New API Key', borderColor: 'green', padding: 2 }
      )
    );
    console.log();
    console.log(chalk.yellow('  ⚠  Save this key now — you will not see it again!'));
    console.log();

    // Offer to show MCP config with the new key
    const showConfig = await prompts({
      type: 'confirm',
      name: 'yes',
      message: 'Show MCP config for your agent? (Cursor, Claude, etc.)',
      initial: true,
    });

    if (showConfig.yes) {
      await actionConfigureMCP(data.key);
    }
  } else {
    spinner.fail(chalk.red('Failed to create API key'));
    console.log(chalk.red(`  Error: ${data.error || 'Unknown error'}\n`));
  }
}

// ─── List Keys ───────────────────────────────────────────────────────────────

async function actionListKeys(apiKey) {
  console.log();
  console.log(separator('YOUR API KEYS'));
  console.log();

  const spinner = ora({
    text: chalk.dim('Fetching API keys…'),
    spinner: 'dots',
    color: 'cyan',
  }).start();

  const { ok, data } = await apiRequest('GET', '/v1/keys', { apiKey });

  if (!ok || !data.success) {
    spinner.fail(chalk.red('Failed to fetch API keys'));
    console.log(chalk.red(`  Error: ${data.error || 'Unknown error'}\n`));
    return [];
  }

  const keys = data.keys || [];
  spinner.succeed(chalk.green(`Found ${keys.length} API key(s)`));
  console.log();

  if (keys.length === 0) {
    console.log(chalk.dim('  No API keys found. Create one with the "Create new key" option.\n'));
    return keys;
  }

  // Display each key
  for (const key of keys) {
    const status = key.is_revoked
      ? chalk.red.bold('REVOKED')
      : chalk.green.bold('ACTIVE');

    const lastUsed = key.last_used_at
      ? formatTimeAgo(key.last_used_at)
      : chalk.dim('never');

    const created = key.created_at
      ? new Date(key.created_at).toLocaleDateString('en-US', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        })
      : '—';

    const line = [
      `  ${status}  ${chalk.bold(key.name || 'Unnamed')}`,
      `         ${chalk.dim('Preview:')} ${chalk.cyan(key.key_preview || '—')}…`,
      `         ${chalk.dim('ID:')}      ${chalk.dim(key.id)}`,
      `         ${chalk.dim('Created:')} ${created}  ${chalk.dim('·')}  ${chalk.dim('Last used:')} ${lastUsed}`,
      '',
    ].join('\n');

    console.log(line);
  }

  return keys;
}

// ─── Revoke Key ──────────────────────────────────────────────────────────────

async function actionRevokeKey(apiKey) {
  // First, list keys so user can pick one
  const keys = await actionListKeysQuiet(apiKey);
  if (!keys || keys.length === 0) {
    console.log(chalk.dim('  No keys to revoke.\n'));
    return;
  }

  const activeKeys = keys.filter((k) => !k.is_revoked);
  if (activeKeys.length === 0) {
    console.log(chalk.yellow('  All keys are already revoked.\n'));
    return;
  }

  console.log(separator('REVOKE API KEY'));
  console.log();

  const choice = await prompts({
    type: 'select',
    name: 'keyId',
    message: 'Select a key to revoke:',
    choices: activeKeys.map((k) => ({
      title: `${chalk.cyan(k.key_preview || '???')}…  ${chalk.dim('—')} ${k.name || 'Unnamed'}  ${chalk.dim(`(${k.id.slice(0, 8)}…)`)}`,
      value: k.id,
    })),
    hint: '↑/↓ to select',
  });

  if (!choice.keyId) {
    console.log(chalk.dim('\n  Cancelled.\n'));
    return;
  }

  const selectedKey = activeKeys.find((k) => k.id === choice.keyId);

  const confirm = await prompts({
    type: 'confirm',
    name: 'yes',
    message: `Revoke key "${selectedKey.name}"? This cannot be undone.`,
    initial: false,
  });

  if (!confirm.yes) {
    console.log(chalk.dim('\n  Cancelled.\n'));
    return;
  }

  const spinner = ora({
    text: chalk.dim('Revoking key…'),
    spinner: 'dots',
    color: 'yellow',
  }).start();

  const { ok, data } = await apiRequest('POST', `/v1/keys/${choice.keyId}/revoke`, { apiKey });

  if (ok && data.success) {
    spinner.succeed(chalk.green(`Key "${selectedKey.name}" revoked successfully`));
    console.log();
  } else {
    spinner.fail(chalk.red('Failed to revoke key'));
    console.log(chalk.red(`  Error: ${data.error || 'Unknown error'}\n`));
  }
}

// ─── Delete Key ──────────────────────────────────────────────────────────────

async function actionDeleteKey(apiKey) {
  const keys = await actionListKeysQuiet(apiKey);
  if (!keys || keys.length === 0) {
    console.log(chalk.dim('  No keys to delete.\n'));
    return;
  }

  console.log(separator('DELETE API KEY'));
  console.log();

  const choice = await prompts({
    type: 'select',
    name: 'keyId',
    message: 'Select a key to permanently delete:',
    choices: keys.map((k) => {
      const status = k.is_revoked ? chalk.red('revoked') : chalk.green('active');
      return {
        title: `${chalk.cyan(k.key_preview || '???')}…  ${chalk.dim('—')} ${k.name || 'Unnamed'}  [${status}]  ${chalk.dim(`(${k.id.slice(0, 8)}…)`)}`,
        value: k.id,
      };
    }),
    hint: '↑/↓ to select',
  });

  if (!choice.keyId) {
    console.log(chalk.dim('\n  Cancelled.\n'));
    return;
  }

  const selectedKey = keys.find((k) => k.id === choice.keyId);

  const confirm = await prompts({
    type: 'confirm',
    name: 'yes',
    message: chalk.red(`Permanently delete key "${selectedKey.name}"? This CANNOT be undone.`),
    initial: false,
  });

  if (!confirm.yes) {
    console.log(chalk.dim('\n  Cancelled.\n'));
    return;
  }

  const spinner = ora({
    text: chalk.dim('Deleting key…'),
    spinner: 'dots',
    color: 'red',
  }).start();

  const { ok, data } = await apiRequest('DELETE', `/v1/keys/${choice.keyId}`, { apiKey });

  if (ok && data.success) {
    spinner.succeed(chalk.green(`Key "${selectedKey.name}" deleted permanently`));
    console.log();
  } else {
    spinner.fail(chalk.red('Failed to delete key'));
    console.log(chalk.red(`  Error: ${data.error || 'Unknown error'}\n`));
  }
}

// ─── Configure MCP ───────────────────────────────────────────────────────────

async function actionConfigureMCP(keyToUse) {
  console.log();
  console.log(separator('CONFIGURE MCP'));
  console.log();

  const modeChoice = await prompts({
    type: 'select',
    name: 'mode',
    message: 'How should your agent connect?',
    choices: [
      {
        title: `${chalk.green('⬡')} ${chalk.bold('Local')}   ${chalk.dim('— stdio proxy via uvx (recommended)')}`,
        description: 'Runs a lightweight local proxy that forwards to the cloud',
        value: 'local',
      },
      {
        title: `${chalk.cyan('☁')} ${chalk.bold('Remote')}  ${chalk.dim('— streamable HTTP (direct connection)')}`,
        description: 'Connects directly to the cloud MCP endpoint',
        value: 'remote',
      },
    ],
    hint: '↑/↓ to select',
  });

  if (!modeChoice.mode) {
    console.log(chalk.dim('\n  Cancelled.\n'));
    return;
  }

  let config;

  if (modeChoice.mode === 'local') {
    config = {
      mcpServers: {
        'synsc-context': {
          command: 'uvx',
          args: ['synsc-context-proxy'],
          env: {
            SYNSC_API_KEY: keyToUse,
          },
        },
      },
    };
  } else {
    config = {
      mcpServers: {
        'synsc-context': {
          url: `${SYNSC_API}/mcp`,
          headers: {
            Authorization: `Bearer ${keyToUse}`,
          },
        },
      },
    };
  }

  const jsonStr = JSON.stringify(config, null, 2);

  console.log();
  console.log(
    box(jsonStr, {
      title: modeChoice.mode === 'local' ? '📦 MCP Config (stdio proxy)' : '☁️  MCP Config (remote)',
      borderColor: 'cyan',
      padding: 1,
    })
  );
  console.log();
  console.log(chalk.dim('  Copy the JSON above into your agent\'s MCP config file:'));
  console.log();
  console.log(chalk.dim('    Cursor:         ~/.cursor/mcp.json'));
  console.log(chalk.dim('    Claude Desktop:  ~/Library/Application Support/Claude/claude_desktop_config.json'));
  console.log(chalk.dim('    Claude Code:     ~/.claude/mcp.json'));
  console.log(chalk.dim('    Windsurf:        ~/.codeium/windsurf/mcp_config.json'));
  console.log();

  if (modeChoice.mode === 'local') {
    console.log(chalk.dim('  Requires uv: ') + chalk.cyan('curl -LsSf https://astral.sh/uv/install.sh | sh'));
    console.log();
  }

  console.log(successGradient('  Your API key is pre-filled — just paste and restart your agent!'));
  console.log();
}

// ─── Quiet list (for internal use by revoke/delete) ─────────────────────────

async function actionListKeysQuiet(apiKey) {
  const spinner = ora({
    text: chalk.dim('Fetching your keys…'),
    spinner: 'dots',
    color: 'cyan',
  }).start();

  const { ok, data } = await apiRequest('GET', '/v1/keys', { apiKey });

  if (!ok || !data.success) {
    spinner.fail(chalk.red('Failed to fetch keys'));
    console.log(chalk.red(`  Error: ${data.error || 'Unknown error'}\n`));
    return [];
  }

  const keys = data.keys || [];
  spinner.succeed(chalk.dim(`${keys.length} key(s) found`));
  console.log();
  return keys;
}

// ─── Format time ago ─────────────────────────────────────────────────────────

function formatTimeAgo(dateStr) {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);

  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 2592000) return `${Math.floor(diffSec / 86400)}d ago`;
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MAIN MENU LOOP
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
    text: chalk.dim('Checking SynSc server…'),
    spinner: 'dots',
    color: 'cyan',
  }).start();

  const healthRes = await apiRequest('GET', '/health');

  if (healthRes.ok) {
    const d = healthRes.data;
    healthSpinner.succeed(
      chalk.green('SynSc server is online') +
        chalk.dim(` (${d.indexed_repos ?? '?'} repos, ${d.indexed_papers ?? '?'} papers, ${d.indexed_datasets ?? '?'} datasets)`)
    );
  } else {
    healthSpinner.warn(
      chalk.yellow('Could not reach SynSc server — make sure it is running')
    );
    console.log(chalk.dim(`  API URL: ${SYNSC_API}`));
    console.log(chalk.dim('  Set SYNSC_API env var to override.\n'));
  }

  // ── Authenticate ─────────────────────────────────────────────────────────
  const apiKey = await authenticate();

  // Verify the key works
  const verifySpinner = ora({
    text: chalk.dim('Verifying your key…'),
    spinner: 'dots',
    color: 'cyan',
  }).start();

  const verifyRes = await apiRequest('GET', '/v1/keys', { apiKey });

  if (verifyRes.ok && verifyRes.data.success) {
    const count = verifyRes.data.keys?.length ?? 0;
    verifySpinner.succeed(
      chalk.green('Authenticated') + chalk.dim(` — ${count} existing key(s) on your account`)
    );
  } else if (verifyRes.status === 401) {
    verifySpinner.fail(chalk.red('Invalid API key'));
    console.log(chalk.red('  The key was rejected by the server. Please check it and try again.\n'));
    process.exit(1);
  } else {
    verifySpinner.warn(chalk.yellow('Could not verify key — continuing anyway'));
  }

  // ── Menu Loop ────────────────────────────────────────────────────────────
  let running = true;

  while (running) {
    console.log();
    console.log(separator('WHAT WOULD YOU LIKE TO DO?'));
    console.log();

    const action = await prompts({
      type: 'select',
      name: 'choice',
      message: 'Choose an action:',
      choices: [
        {
          title: `${chalk.green('+')} ${chalk.bold('Create a new API key')}  ${chalk.gray('— generate a key for an agent or integration')}`,
          value: 'create',
        },
        {
          title: `${chalk.magenta('⎔')} ${chalk.bold('Configure MCP')}       ${chalk.gray('— get copyable config for Cursor, Claude, etc.')}`,
          value: 'configure',
        },
        {
          title: `${chalk.cyan('☰')} ${chalk.bold('List all API keys')}    ${chalk.gray('— view keys and their status')}`,
          value: 'list',
        },
        {
          title: `${chalk.yellow('⊘')} ${chalk.bold('Revoke an API key')}   ${chalk.gray('— disable a key (stops working)')}`,
          value: 'revoke',
        },
        {
          title: `${chalk.red('✕')} ${chalk.bold('Delete an API key')}   ${chalk.gray('— permanently remove a key')}`,
          value: 'delete',
        },
        {
          title: `${chalk.dim('→')} ${chalk.bold('Exit')}`,
          value: 'exit',
        },
      ],
      hint: '↑/↓ to select',
    });

    if (!action.choice || action.choice === 'exit') {
      running = false;
      continue;
    }

    switch (action.choice) {
      case 'create':
        await actionCreateKey(apiKey);
        break;
      case 'configure':
        await actionConfigureMCP(apiKey);
        break;
      case 'list':
        await actionListKeys(apiKey);
        break;
      case 'revoke':
        await actionRevokeKey(apiKey);
        break;
      case 'delete':
        await actionDeleteKey(apiKey);
        break;
    }
  }

  // ── Goodbye ────────────────────────────────────────────────────────────
  console.log();
  console.log(synscGradient('  Thanks for using SynSc Context!'));
  console.log(chalk.dim('  Run `npx synsc-context` to configure an AI agent with your key.\n'));
}

// ─── Run ─────────────────────────────────────────────────────────────────────
main().catch((err) => {
  console.error(chalk.red(`\n  Fatal error: ${err.message}\n`));
  if (process.env.DEBUG) {
    console.error(err.stack);
  }
  process.exit(1);
});
