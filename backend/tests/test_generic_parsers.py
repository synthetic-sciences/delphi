"""Tests for the spec-driven generic tree-sitter parsers and regex fallback.

These guard Delphi's multi-language symbol extraction: Go, Rust, Java, C, C++,
C#, Ruby, PHP via tree-sitter, plus Kotlin/Swift/Scala via regex.
"""
from __future__ import annotations

import pytest

from synsc.parsing.generic_parser import GenericTreeSitterParser
from synsc.parsing.language_specs import SPECS
from synsc.parsing.registry import get_parser_registry


def _parser(language: str) -> GenericTreeSitterParser:
    try:
        return GenericTreeSitterParser(SPECS[language])
    except ImportError:
        pytest.skip(f"grammar for {language} not installed")


SAMPLES: dict[str, tuple[str, set[str]]] = {
    "go": (
        """
package main

import "fmt"

type Server struct{ Port int }

func (s *Server) Start() error {
    return fmt.Errorf("boom")
}

func NewServer(port int) *Server {
    return &Server{Port: port}
}
""",
        {"Server", "Start", "NewServer"},
    ),
    "rust": (
        """
use std::fmt;

pub struct Engine { rpm: u32 }

impl Engine {
    pub fn rev(&self) -> u32 { self.rpm }
}

fn helper() -> u32 { 0 }
""",
        {"Engine", "rev", "helper"},
    ),
    "java": (
        """
package com.example;

public class Calculator {
    public int add(int a, int b) { return a + b; }
    private void reset() {}
}
""",
        {"Calculator", "add", "reset"},
    ),
    "c": (
        """
#include <stdio.h>

struct Point { int x; int y; };

int add(int a, int b) {
    return a + b;
}
""",
        {"Point", "add"},
    ),
    "cpp": (
        """
class Widget {
public:
    int render(int frame) { return frame; }
};

namespace ui {
    void draw() {}
}
""",
        {"Widget", "render", "draw"},
    ),
    "csharp": (
        """
namespace App {
    public class Service {
        public int Compute(int n) { return n; }
    }
}
""",
        {"Service", "Compute"},
    ),
    "ruby": (
        """
module Billing
  class Invoice
    def total
      42
    end
  end
end
""",
        {"Billing", "Invoice", "total"},
    ),
    "php": (
        """
<?php
namespace App;

class Repository {
    public function find($id) { return $id; }
}

function helper() { return 1; }
""",
        {"Repository", "find", "helper"},
    ),
}


@pytest.mark.parametrize("language", list(SAMPLES.keys()))
def test_extract_symbols(language: str) -> None:
    source, expected = SAMPLES[language]
    parser = _parser(language)
    symbols = parser.extract_symbols(source)
    names = {s.name for s in symbols}
    missing = expected - names
    assert not missing, f"{language}: missing symbols {missing} (got {names})"


@pytest.mark.parametrize("language", list(SAMPLES.keys()))
def test_symbols_have_line_ranges(language: str) -> None:
    source, _ = SAMPLES[language]
    parser = _parser(language)
    for sym in parser.extract_symbols(source):
        assert sym.start_line >= 1
        assert sym.end_line >= sym.start_line
        assert sym.signature is not None


@pytest.mark.parametrize("language", list(SAMPLES.keys()))
def test_code_regions(language: str) -> None:
    source, _ = SAMPLES[language]
    parser = _parser(language)
    regions = parser.create_code_regions(source)
    assert regions, f"{language}: no regions produced"
    assert all(r.start_line >= 1 and r.end_line >= r.start_line for r in regions)


def test_go_method_receiver_qualified_name() -> None:
    parser = _parser("go")
    symbols = parser.extract_symbols(SAMPLES["go"][0])
    start = next(s for s in symbols if s.name == "Start")
    assert start.symbol_type == "method"
    assert start.parent_name == "Server"
    assert start.qualified_name == "Server.Start"


def test_go_exported_visibility() -> None:
    parser = _parser("go")
    symbols = {s.name: s for s in parser.extract_symbols(SAMPLES["go"][0])}
    assert symbols["NewServer"].is_exported is True


def test_extract_calls_go() -> None:
    parser = _parser("go")
    calls = parser.extract_calls(SAMPLES["go"][0])
    callees = {c.callee for c in calls}
    assert "Errorf" in callees


def test_extract_calls_python_independent_of_grammar() -> None:
    parser = _parser("rust")
    calls = parser.extract_calls(SAMPLES["rust"][0])
    # `helper` is not called here, but `self.rpm` access is not a call;
    # ensure extraction returns a list without raising.
    assert isinstance(calls, list)


def test_registry_registers_many_languages() -> None:
    registry = get_parser_registry()
    langs = set(registry.supported_languages)
    # Core three plus the tree-sitter additions should be present.
    expected = {"python", "javascript", "typescript", "go", "rust", "java"}
    assert expected.issubset(langs), f"missing: {expected - langs}"


def test_regex_parser_kotlin() -> None:
    from synsc.parsing.regex_parser import REGEX_SPECS, RegexParser

    parser = RegexParser(REGEX_SPECS["kotlin"])
    source = """
class Greeter {
    fun greet(name: String): String {
        return "hi"
    }
}

fun topLevel() {}
"""
    names = {s.name for s in parser.extract_symbols(source)}
    assert {"Greeter", "greet", "topLevel"}.issubset(names)


def test_regex_parser_swift() -> None:
    from synsc.parsing.regex_parser import REGEX_SPECS, RegexParser

    parser = RegexParser(REGEX_SPECS["swift"])
    source = """
struct Vector {
    func length() -> Double { return 0.0 }
}

func freeFunc() {}
"""
    names = {s.name for s in parser.extract_symbols(source)}
    assert {"Vector", "length", "freeFunc"}.issubset(names)
