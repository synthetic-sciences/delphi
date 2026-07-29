# Contributing to Delphi

Thank you for helping make Delphi more useful, reliable, and trustworthy for
developers and research agents.

## Before You Start

- Search existing [issues](https://github.com/synthetic-sciences/delphi/issues)
  and pull requests before opening a duplicate.
- Use an issue to discuss large features, new dependencies, migrations, or
  public API changes before investing in an implementation.
- Report security vulnerabilities through the private process in
  [SECURITY.md](SECURITY.md), never through a public issue.

## Development Setup

The fastest end-to-end setup uses Docker:

```bash
git clone https://github.com/synthetic-sciences/delphi.git
cd delphi
cp env.example .env
./scripts/launch_app.sh
```

For focused development, install and validate the component you are changing.

### Backend

```bash
cd backend
uv sync --locked --extra dev
uv run ruff check synsc tests
uv run mypy synsc
uv run pytest -q
```

### Dashboard

```bash
cd frontend
npm ci
npm run lint
npm run build
```

### Landing site

```bash
cd landing
corepack enable
pnpm install --frozen-lockfile
pnpm build
```

### CLI

```bash
cd packages/cli
npm ci
npm test
npm pack --dry-run
```

### MCP proxy

```bash
cd packages/mcp-proxy
uv sync --locked --group dev
uv run pytest -q
uv build
```

PostgreSQL contract tests additionally require a PostgreSQL 16 instance with
the pgvector extension. The canonical service configuration and commands live
in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Making a Change

1. Create a focused branch from `master`.
2. Add or update tests for behavior changes.
3. Keep public APIs backwards compatible unless the change has been discussed.
4. Run the checks for every component you touched.
5. Use a concise, descriptive commit message such as
   `fix(search): preserve path matches during fusion`.
6. Open a pull request that explains the problem, approach, validation, and any
   deployment or migration implications.

Small, reviewable pull requests are easier to validate and ship. Avoid mixing
formatting sweeps, dependency upgrades, and product changes unless they are
inseparable.

## Benchmark and Performance Claims

Treat evaluation code and methodology as product code. A new benchmark claim
must state:

- the dataset and exact task slice;
- the model, prompt, and inference settings held fixed;
- the comparator conditions;
- exclusions, retries, provider failures, and corpus-integrity checks;
- the metric definition and whether the result is descriptive or supported by
  an uncertainty estimate;
- the command or procedure required to reproduce the result.

Do not optimize against a public evaluation slice and then describe it as a
held-out result. Do not publish a universal state-of-the-art claim from a small
or task-specific pilot. Raw benchmark outputs containing source content, user
data, credentials, or provider responses must not be committed.

## Documentation and Style

- Prefer plain language and concrete examples.
- Keep Markdown links relative when they point inside this repository.
- Follow the existing Python and TypeScript conventions in the component you
  change.
- Never add secrets, private source material, generated benchmark outputs, or
  local environment files.

## Community

Participation in Delphi is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md). By contributing, you agree that your
contributions are licensed under the repository's
[Apache License 2.0](LICENSE).

