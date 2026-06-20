"""Benchmark runner: run retrievers over tasks, compute metrics, render reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from synsc.bench.corpus import Corpus, Task
from synsc.bench.metrics import aggregate_metrics, task_metrics
from synsc.bench.retrievers import Retriever, default_retrievers


@dataclass
class RetrieverResult:
    name: str
    metrics: dict[str, float]
    avg_token_cost: float
    per_task: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BenchmarkReport:
    k: int
    corpus_size: int
    task_count: int
    results: list[RetrieverResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "corpus_size": self.corpus_size,
            "task_count": self.task_count,
            "results": [
                {
                    "retriever": r.name,
                    "metrics": r.metrics,
                    "avg_token_cost": r.avg_token_cost,
                }
                for r in self.results
            ],
        }


def _relevant_set(corpus: Corpus, task: Task) -> set[str]:
    """The relevant doc-id set for a task.

    Files are matched directly; symbols are resolved to the files that define
    them so symbol-level tasks still score against document ids.
    """
    relevant = set(task.relevant_files)
    if task.relevant_symbols:
        from synsc.parsing.registry import get_parser_registry

        registry = get_parser_registry()
        wanted = set(task.relevant_symbols)
        for doc in corpus:
            parser = registry.get_parser(doc.language) if doc.language else None
            if parser is None:
                continue
            try:
                names = {s.name for s in parser.extract_symbols(doc.content)}
            except Exception:
                continue
            if wanted & names:
                relevant.add(doc.doc_id)
    return relevant


def run_benchmark(
    corpus: Corpus,
    tasks: list[Task],
    retrievers: list[Retriever] | None = None,
    k: int = 5,
) -> BenchmarkReport:
    retrievers = retrievers or default_retrievers()
    results: list[RetrieverResult] = []

    for retriever in retrievers:
        per_task: list[dict[str, Any]] = []
        metric_rows: list[dict[str, float]] = []
        token_costs: list[int] = []
        for task in tasks:
            relevant = _relevant_set(corpus, task)
            ranked, token_cost = retriever.retrieve(corpus, task.query, k)
            m = task_metrics(ranked, relevant, k)
            metric_rows.append(m)
            token_costs.append(token_cost)
            per_task.append(
                {
                    "task_id": task.task_id,
                    "query": task.query,
                    "metrics": m,
                    "token_cost": token_cost,
                }
            )
        results.append(
            RetrieverResult(
                name=retriever.name,
                metrics=aggregate_metrics(metric_rows),
                avg_token_cost=mean(token_costs) if token_costs else 0.0,
                per_task=per_task,
            )
        )

    return BenchmarkReport(
        k=k,
        corpus_size=len(corpus),
        task_count=len(tasks),
        results=results,
    )


def render_markdown(report: BenchmarkReport) -> str:
    """Render the report as a markdown leaderboard."""
    lines: list[str] = []
    lines.append("# Delphi Retrieval Benchmark")
    lines.append("")
    lines.append(
        f"Corpus: **{report.corpus_size} files** · Tasks: **{report.task_count}** · k = **{report.k}**"
    )
    lines.append("")

    metric_keys = [
        f"recall@{report.k}",
        f"precision@{report.k}",
        f"success@{report.k}",
        f"ndcg@{report.k}",
        "mrr",
    ]
    header = "| Retriever | " + " | ".join(metric_keys) + " | avg tokens read |"
    sep = "|" + "---|" * (len(metric_keys) + 2)
    lines.append(header)
    lines.append(sep)

    # Token economy: relative to naive grep, the "what most agents do" baseline.
    naive = next((r for r in report.results if r.name == "naive_grep"), None)
    naive_cost = naive.avg_token_cost if naive else 0.0

    for r in report.results:
        cells = [f"{r.metrics.get(key, 0.0):.3f}" for key in metric_keys]
        if naive_cost and r.avg_token_cost:
            ratio = naive_cost / r.avg_token_cost
            token_cell = f"{r.avg_token_cost:.0f} ({ratio:.1f}× leaner)"
        else:
            token_cell = f"{r.avg_token_cost:.0f}"
        lines.append(f"| {r.name} | " + " | ".join(cells) + f" | {token_cell} |")

    lines.append("")
    lines.append(
        "> Token economy is measured against `naive_grep` (dump every file with a "
        "token match), which is what an agent does without a retrieval layer."
    )
    lines.append("")
    return "\n".join(lines)


def to_json(report: BenchmarkReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent)
