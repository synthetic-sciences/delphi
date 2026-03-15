#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Load env vars
if [ -f "$ROOT/.env" ]; then
  set -a
  source "$ROOT/.env"
  set +a
fi

# Map PYPI_API to twine credentials
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="$PYPI_API"

echo "=== Publishing synsc-context-proxy to PyPI ==="
cd "$ROOT/packages/mcp-proxy"
rm -rf dist/
python -m build
uvx twine upload dist/*

echo ""
echo "=== Publishing synsc-context to npm ==="
cd "$ROOT/packages/wizard"
echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > .npmrc
npm publish
rm -f .npmrc

echo ""
echo "Done. Both packages published."
