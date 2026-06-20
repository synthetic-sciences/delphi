"""Declarative tree-sitter language specs for the generic parser.

Rather than hand-writing a verbose parser per language (the approach used for
Python and TypeScript), the bulk of supported languages are driven by a small
declarative ``LanguageSpec``. The :class:`~synsc.parsing.generic_parser.GenericTreeSitterParser`
consumes a spec and produces the same :class:`ExtractedSymbol` /
:class:`CodeRegion` output as the bespoke parsers.

Adding a language is usually a matter of appending one ``LanguageSpec`` here —
no new parser class required.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


# Node types that commonly carry a symbol's name when there is no ``name`` field.
NAME_NODE_TYPES: frozenset[str] = frozenset(
    {
        "identifier",
        "type_identifier",
        "field_identifier",
        "constant",
        "name",
        "scoped_identifier",
        "qualified_identifier",
    }
)

# Node types that represent a callable/declaration "body". Used to truncate a
# multi-line declaration into a signature.
BODY_NODE_TYPES: frozenset[str] = frozenset(
    {
        "block",
        "compound_statement",
        "declaration_list",
        "field_declaration_list",
        "statement_list",
        "body",
        "class_body",
        "enum_body",
        "interface_body",
        "do_block",
    }
)


@dataclass(frozen=True)
class LanguageSpec:
    """Configuration that drives the generic tree-sitter parser for a language."""

    language: str
    """Canonical language id — must match ``core.language_detector`` output."""

    extensions: tuple[str, ...]
    """File extensions handled by this language, including the leading dot."""

    module: str
    """Python module of the tree-sitter grammar (e.g. ``tree_sitter_go``)."""

    entrypoint: str = "language"
    """Name of the grammar's language function (PHP uses ``language_php``)."""

    function_nodes: frozenset[str] = field(default_factory=frozenset)
    """AST node types that define a function/method/constructor."""

    container_nodes: tuple[tuple[str, str], ...] = ()
    """(node_type, symbol_type) pairs for type-like declarations that are
    emitted as symbols and provide a parent scope for nested methods."""

    scope_nodes: frozenset[str] = field(default_factory=frozenset)
    """Node types that provide a parent scope but are *not* emitted as symbols
    (e.g. Rust ``impl_item``). Their name becomes the parent of inner methods."""

    name_field: str = "name"
    """tree-sitter field name that holds the symbol name when present."""

    declarator_fallback: bool = False
    """When True, dig through ``function_declarator`` to find the name
    (required for C / C++ where functions have no ``name`` field)."""

    method_receiver: bool = False
    """When True (Go), resolve a method's parent from its receiver type."""

    exported: str = "underscore"
    """Visibility heuristic: ``go`` (capitalized), ``rust`` (``pub`` modifier),
    ``always`` (everything public), or ``underscore`` (public unless ``_``)."""

    call_nodes: frozenset[str] = field(default_factory=frozenset)
    """Node types representing a call expression (for the code graph)."""

    import_nodes: frozenset[str] = field(default_factory=frozenset)
    """Node types representing import/use/include statements."""


SPECS: dict[str, LanguageSpec] = {
    "go": LanguageSpec(
        language="go",
        extensions=(".go",),
        module="tree_sitter_go",
        function_nodes=frozenset({"function_declaration", "method_declaration"}),
        container_nodes=(("type_spec", "type"),),
        name_field="name",
        method_receiver=True,
        exported="go",
        call_nodes=frozenset({"call_expression"}),
        import_nodes=frozenset({"import_declaration"}),
    ),
    "rust": LanguageSpec(
        language="rust",
        extensions=(".rs",),
        module="tree_sitter_rust",
        function_nodes=frozenset({"function_item"}),
        container_nodes=(
            ("struct_item", "struct"),
            ("enum_item", "enum"),
            ("trait_item", "trait"),
            ("union_item", "struct"),
            ("mod_item", "module"),
        ),
        scope_nodes=frozenset({"impl_item"}),
        name_field="name",
        exported="rust",
        call_nodes=frozenset({"call_expression", "macro_invocation"}),
        import_nodes=frozenset({"use_declaration"}),
    ),
    "java": LanguageSpec(
        language="java",
        extensions=(".java",),
        module="tree_sitter_java",
        function_nodes=frozenset({"method_declaration", "constructor_declaration"}),
        container_nodes=(
            ("class_declaration", "class"),
            ("interface_declaration", "interface"),
            ("enum_declaration", "enum"),
            ("record_declaration", "class"),
            ("annotation_type_declaration", "interface"),
        ),
        name_field="name",
        exported="always",
        call_nodes=frozenset({"method_invocation", "object_creation_expression"}),
        import_nodes=frozenset({"import_declaration"}),
    ),
    "c": LanguageSpec(
        language="c",
        extensions=(".c", ".h"),
        module="tree_sitter_c",
        function_nodes=frozenset({"function_definition"}),
        container_nodes=(
            ("struct_specifier", "struct"),
            ("enum_specifier", "enum"),
            ("union_specifier", "struct"),
        ),
        name_field="name",
        declarator_fallback=True,
        exported="always",
        call_nodes=frozenset({"call_expression"}),
        import_nodes=frozenset({"preproc_include"}),
    ),
    "cpp": LanguageSpec(
        language="cpp",
        extensions=(".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx", ".c++", ".h++"),
        module="tree_sitter_cpp",
        function_nodes=frozenset({"function_definition"}),
        container_nodes=(
            ("class_specifier", "class"),
            ("struct_specifier", "struct"),
            ("enum_specifier", "enum"),
            ("union_specifier", "struct"),
            ("namespace_definition", "module"),
        ),
        name_field="name",
        declarator_fallback=True,
        exported="always",
        call_nodes=frozenset({"call_expression"}),
        import_nodes=frozenset({"preproc_include", "using_declaration"}),
    ),
    "csharp": LanguageSpec(
        language="csharp",
        extensions=(".cs",),
        module="tree_sitter_c_sharp",
        function_nodes=frozenset(
            {"method_declaration", "constructor_declaration", "local_function_statement"}
        ),
        container_nodes=(
            ("class_declaration", "class"),
            ("interface_declaration", "interface"),
            ("struct_declaration", "struct"),
            ("enum_declaration", "enum"),
            ("record_declaration", "class"),
        ),
        name_field="name",
        exported="always",
        call_nodes=frozenset({"invocation_expression", "object_creation_expression"}),
        import_nodes=frozenset({"using_directive"}),
    ),
    "ruby": LanguageSpec(
        language="ruby",
        extensions=(".rb",),
        module="tree_sitter_ruby",
        function_nodes=frozenset({"method", "singleton_method"}),
        container_nodes=(
            ("class", "class"),
            ("module", "module"),
        ),
        name_field="name",
        exported="always",
        call_nodes=frozenset({"call"}),
        import_nodes=frozenset(),
    ),
    "php": LanguageSpec(
        language="php",
        extensions=(".php",),
        module="tree_sitter_php",
        entrypoint="language_php",
        function_nodes=frozenset(
            {"function_definition", "method_declaration"}
        ),
        container_nodes=(
            ("class_declaration", "class"),
            ("interface_declaration", "interface"),
            ("trait_declaration", "trait"),
            ("enum_declaration", "enum"),
        ),
        name_field="name",
        exported="always",
        call_nodes=frozenset(
            {"function_call_expression", "member_call_expression", "scoped_call_expression"}
        ),
        import_nodes=frozenset({"namespace_use_declaration"}),
    ),
}


_LANGUAGE_CACHE: dict[str, object] = {}


def load_language(spec: LanguageSpec):
    """Load and cache the tree-sitter ``Language`` for a spec.

    Returns ``None`` if the grammar package isn't installed or fails to load,
    so the registry can skip the language gracefully rather than crash.
    """
    if spec.language in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[spec.language]
    try:
        import importlib

        from tree_sitter import Language

        module = importlib.import_module(spec.module)
        entry: Callable = getattr(module, spec.entrypoint)
        language = Language(entry())
        _LANGUAGE_CACHE[spec.language] = language
        return language
    except Exception as e:  # pragma: no cover - depends on optional grammar wheels
        logger.warning(
            "tree-sitter grammar unavailable",
            language=spec.language,
            module=spec.module,
            error=str(e),
        )
        _LANGUAGE_CACHE[spec.language] = None
        return None
