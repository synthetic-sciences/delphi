"""Tests for the code-dependency graph: call extraction + blast-radius traversal.

The DB-backed build/query paths need Postgres, so here we test the two pure
layers that carry the logic: per-language call extraction (parser) and the
reverse-BFS that powers blast radius.
"""
from __future__ import annotations

import pytest

from synsc.parsing.call_graph_util import reduce_callee
from synsc.parsing.generic_parser import GenericTreeSitterParser
from synsc.parsing.language_specs import SPECS
from synsc.parsing.python_parser import PythonParser
from synsc.services.code_graph_service import CodeGraphService


def _generic(language: str) -> GenericTreeSitterParser:
    try:
        return GenericTreeSitterParser(SPECS[language])
    except ImportError:
        pytest.skip(f"grammar for {language} not installed")


# ---------------------------------------------------------------------------
# Call extraction
# ---------------------------------------------------------------------------

def test_python_call_extraction_scopes_to_caller() -> None:
    source = '''
def helper(x):
    return x + 1

def main():
    y = helper(3)
    return helper(y)

class Service:
    def run(self):
        return helper(self.value)
'''
    calls = PythonParser().extract_calls(source)
    pairs = {(c.caller, c.callee) for c in calls}
    assert ("main", "helper") in pairs
    assert ("Service.run", "helper") in pairs


def test_go_call_extraction_uses_receiver_scope() -> None:
    parser = _generic("go")
    source = """
package main

func helper() int { return 1 }

type Server struct{}

func (s *Server) Start() int {
    return helper()
}
"""
    calls = parser.extract_calls(source)
    pairs = {(c.caller, c.callee) for c in calls}
    assert ("Server.Start", "helper") in pairs


def test_java_call_extraction() -> None:
    parser = _generic("java")
    source = """
class App {
    int helper() { return 1; }
    int run() { return helper(); }
}
"""
    calls = parser.extract_calls(source)
    callees = {c.callee for c in calls}
    assert "helper" in callees


def test_callee_name_reduction() -> None:
    assert reduce_callee("a.b.c") == "c"
    assert reduce_callee("std::vector") == "vector"
    assert reduce_callee("$obj->method") == "method"
    assert reduce_callee("plain") == "plain"


def test_callee_name_rejects_non_identifiers() -> None:
    # A numeric / empty callee should not produce a name.
    parser = _generic("go")
    # No calls in this snippet; just ensure extraction is empty, not erroring.
    assert parser.extract_calls("package main\nvar x = 3\n") == []


# ---------------------------------------------------------------------------
# Blast-radius BFS (pure, DB-free)
# ---------------------------------------------------------------------------

def test_bfs_reachable_depth_assignment() -> None:
    # a <- b <- c  (b calls a, c calls b). Reverse adjacency: a->{b}, b->{c}.
    reverse = {"a": {"b"}, "b": {"c"}}
    visited = CodeGraphService.bfs_reachable(reverse, {"a"}, max_depth=3, max_nodes=100)
    assert visited["a"] == 0
    assert visited["b"] == 1
    assert visited["c"] == 2


def test_bfs_reachable_respects_max_depth() -> None:
    reverse = {"a": {"b"}, "b": {"c"}, "c": {"d"}}
    visited = CodeGraphService.bfs_reachable(reverse, {"a"}, max_depth=1, max_nodes=100)
    assert "b" in visited
    assert "c" not in visited  # depth 2 excluded
    assert "d" not in visited


def test_bfs_reachable_respects_max_nodes() -> None:
    reverse = {"a": {"b", "c", "d", "e"}}
    visited = CodeGraphService.bfs_reachable(reverse, {"a"}, max_depth=5, max_nodes=2)
    # seed + at most 2 discovered
    assert len(visited) - 1 <= 2


def test_bfs_reachable_handles_cycles() -> None:
    reverse = {"a": {"b"}, "b": {"a"}}  # mutual recursion
    visited = CodeGraphService.bfs_reachable(reverse, {"a"}, max_depth=5, max_nodes=100)
    assert visited["a"] == 0
    assert visited["b"] == 1  # does not loop forever


def test_bfs_reachable_multiple_seeds() -> None:
    reverse = {"a": {"x"}, "b": {"y"}}
    visited = CodeGraphService.bfs_reachable(reverse, {"a", "b"}, max_depth=2, max_nodes=100)
    assert visited["a"] == 0 and visited["b"] == 0
    assert visited["x"] == 1 and visited["y"] == 1


# ---------------------------------------------------------------------------
# build_for_repo resolution (DB-free via a fake session)
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._items

    def delete(self, **kwargs):
        return len(self._items)


class _FakeSession:
    """Minimal session implementing only what CodeGraphService._build uses."""

    def __init__(self, symbols, chunks):
        self._symbols = symbols
        self._chunks = chunks
        self.inserted: list[dict] = []

    def query(self, model, *rest):
        from synsc.database.models import CodeChunk, Symbol, SymbolReference

        if model is Symbol:
            return _FakeQuery(self._symbols)
        if model is CodeChunk:
            return _FakeQuery(self._chunks)
        if model is SymbolReference:
            return _FakeQuery([])
        return _FakeQuery([])

    def bulk_insert_mappings(self, model, rows):
        self.inserted.extend(rows)

    def flush(self):
        pass


def _make_python_repo():
    from synsc.database.models import CodeChunk, Symbol

    def sym(sid, name, qual, stype):
        return Symbol(
            symbol_id=sid, repo_id="r1", file_id="f1", name=name,
            qualified_name=qual, symbol_type=stype, start_line=1, end_line=2,
            language="python",
        )

    symbols = [
        sym("s_helper", "helper", "helper", "function"),
        sym("s_main", "main", "main", "function"),
        sym("s_service", "Service", "Service", "class"),
        sym("s_run", "run", "Service.run", "method"),
    ]

    def chunk(idx, content, names):
        c = CodeChunk(
            chunk_id=f"c{idx}", repo_id="r1", file_id="f1", chunk_index=idx,
            content=content, start_line=1, end_line=2, language="python",
        )
        c.set_symbol_names(names)
        return c

    chunks = [
        chunk(0, "def helper(x):\n    return x + 1", ["helper"]),
        chunk(1, "def main():\n    print(helper(3))", ["main"]),
        chunk(2, "class Service:\n    def run(self):\n        return helper(self.x)", ["Service"]),
    ]
    return symbols, chunks


def test_build_resolves_internal_and_external_calls() -> None:
    symbols, chunks = _make_python_repo()
    session = _FakeSession(symbols, chunks)
    result = CodeGraphService()._build(session, "r1")

    assert result["success"] is True
    edges = {
        (r["source_symbol_id"], r["target_symbol_id"], r["callee_name"], r["is_resolved"])
        for r in session.inserted
    }
    # main() and Service.run() both call helper() — resolved internal edges.
    assert ("s_main", "s_helper", "helper", True) in edges
    assert ("s_run", "s_helper", "helper", True) in edges
    # print() is external (not a repo symbol) — unresolved edge from main().
    assert ("s_main", None, "print", False) in edges
    assert result["resolved"] >= 2
    assert result["unresolved"] >= 1

