"""Delphi retrieval benchmark.

A small, reproducible harness for measuring retrieval quality and token economy
across baselines (naive grep, smart grep, BM25, symbol lookup) and Delphi's
hybrid fusion. Runs fully in-process against a fixture corpus — no database, no
network — so anyone can reproduce the numbers with one command.

See ``bench/README.md`` (repo root) for methodology and how to run it against
your own corpora.
"""

from synsc.bench.corpus import Corpus, Document, Task, load_corpus, load_tasks
from synsc.bench.harness import BenchmarkReport, run_benchmark
from synsc.bench.metrics import aggregate_metrics, task_metrics

__all__ = [
    "Corpus",
    "Document",
    "Task",
    "load_corpus",
    "load_tasks",
    "BenchmarkReport",
    "run_benchmark",
    "aggregate_metrics",
    "task_metrics",
]
