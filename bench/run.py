#!/usr/bin/env python3
"""Run the Delphi retrieval benchmark and emit a report.

Reproducible, dependency-light, and database-free: it loads the fixture corpus,
runs every retriever over the task set, and writes JSON + Markdown reports.

Usage (from repo root, with the backend env active):

    uv run --project backend python bench/run.py
    uv run --project backend python bench/run.py --k 3 --out bench/results

Point it at your own corpus/tasks to benchmark a different codebase:

    uv run --project backend python bench/run.py \
        --corpus path/to/repo --tasks path/to/tasks.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the `synsc` package importable when run from the repo root.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from synsc.bench import load_corpus, load_tasks, run_benchmark  # noqa: E402
from synsc.bench.harness import render_markdown, to_json  # noqa: E402


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Delphi retrieval benchmark")
    parser.add_argument("--corpus", default=str(here / "corpus"), help="corpus directory")
    parser.add_argument("--tasks", default=str(here / "tasks.json"), help="tasks JSON file")
    parser.add_argument("--k", type=int, default=5, help="cutoff for @k metrics")
    parser.add_argument("--out", default=str(here / "results"), help="output directory")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    tasks = load_tasks(args.tasks)
    report = run_benchmark(corpus, tasks, k=args.k)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(to_json(report), encoding="utf-8")
    markdown = render_markdown(report)
    (out_dir / "report.md").write_text(markdown + "\n", encoding="utf-8")

    print(markdown)
    print(f"\nWrote {out_dir / 'report.json'} and {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
