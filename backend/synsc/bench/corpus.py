"""Corpus + task models for the retrieval benchmark."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Files the benchmark corpus is allowed to read (skip binaries / noise).
_CODE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".kt",
    ".swift",
    ".scala",
    ".lua",
    ".sh",
    ".md",
}


@dataclass
class Document:
    """One file in the corpus."""

    doc_id: str  # relative path, used as the stable identifier
    content: str
    language: str | None = None

    def token_count(self) -> int:
        """Whitespace token count — a deterministic, dependency-free proxy."""
        return len(self.content.split())


@dataclass
class Corpus:
    """A collection of documents keyed by relative path."""

    documents: list[Document] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._by_id = {d.doc_id: d for d in self.documents}

    def get(self, doc_id: str) -> Document | None:
        return self._by_id.get(doc_id)

    def __iter__(self):
        return iter(self.documents)

    def __len__(self) -> int:
        return len(self.documents)


@dataclass
class Task:
    """A retrieval task: a query and the set of documents that answer it."""

    task_id: str
    query: str
    relevant_files: list[str] = field(default_factory=list)
    relevant_symbols: list[str] = field(default_factory=list)
    category: str = "general"


def load_corpus(corpus_dir: str | Path) -> Corpus:
    """Load every code/doc file under ``corpus_dir`` into a Corpus."""
    root = Path(corpus_dir)
    docs: list[Document] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _CODE_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        # Canonical language name (e.g. "python") so it matches the parser
        # registry keys — raw suffixes like "py" would not resolve a parser.
        from synsc.core.language_detector import detect_language

        language = detect_language(path) or path.suffix.lstrip(".")
        docs.append(Document(doc_id=rel, content=content, language=language))
    return Corpus(documents=docs)


def load_tasks(tasks_path: str | Path) -> list[Task]:
    """Load tasks from a JSON file (list of task objects)."""
    data = json.loads(Path(tasks_path).read_text(encoding="utf-8"))
    return [
        Task(
            task_id=item["id"],
            query=item["query"],
            relevant_files=item.get("relevant_files", []),
            relevant_symbols=item.get("relevant_symbols", []),
            category=item.get("category", "general"),
        )
        for item in data
    ]
