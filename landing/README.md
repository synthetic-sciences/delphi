# Delphi landing site

This is the public website for Delphi. It lives in the main
[`synthetic-sciences/delphi`](https://github.com/synthetic-sciences/delphi)
repository so product code, benchmarks, documentation, and the site change
together.

## Local development

```bash
cd landing
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

## Verification

```bash
corepack pnpm audit --prod
corepack pnpm build
```

Vercel is connected to the main repository with `landing` configured as the
project root directory. Production deploys come from `master`.
