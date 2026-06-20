"""Spec-driven tree-sitter parser.

One parser class, configured per-language by a :class:`LanguageSpec`. It extracts
functions, methods, and type declarations (class/struct/enum/trait/interface/...)
plus AST-aware code regions for chunking, and exposes call/import extraction for
the code-dependency graph.

This is how Delphi supports Go, Rust, Java, C, C++, C#, Ruby, and PHP without a
bespoke parser per language. Python and TypeScript keep their dedicated parsers
because they extract richer metadata (docstrings, typed params, decorators).
"""
from __future__ import annotations

import structlog
from tree_sitter import Node, Parser, Tree

from synsc.parsing.base import BaseParser
from synsc.parsing.language_specs import (
    BODY_NODE_TYPES,
    NAME_NODE_TYPES,
    LanguageSpec,
    load_language,
)
from synsc.parsing.models import CodeRegion, ExtractedSymbol

logger = structlog.get_logger(__name__)

_MAX_SIGNATURE_CHARS = 400


class CallSite:
    """A single call discovered inside a function body."""

    __slots__ = ("caller", "callee", "line")

    def __init__(self, caller: str, callee: str, line: int) -> None:
        self.caller = caller
        self.callee = callee
        self.line = line


class GenericTreeSitterParser(BaseParser):
    """Generic parser driven by a :class:`LanguageSpec`."""

    def __init__(self, spec: LanguageSpec) -> None:
        self.spec = spec
        language = load_language(spec)
        if language is None:
            raise ImportError(f"tree-sitter grammar for {spec.language} is unavailable")
        self._parser = Parser(language)
        self._container_map = dict(spec.container_nodes)

    @property
    def language(self) -> str:
        return self.spec.language

    @property
    def supported_extensions(self) -> list[str]:
        return list(self.spec.extensions)

    def parse(self, content: str) -> Tree:
        return self._parser.parse(content.encode("utf-8"))

    # ------------------------------------------------------------------
    # Symbol extraction
    # ------------------------------------------------------------------
    def extract_symbols(self, content: str) -> list[ExtractedSymbol]:
        tree = self.parse(content)
        symbols: list[ExtractedSymbol] = []
        self._visit(tree.root_node, symbols, parent_stack=[])
        return symbols

    def _visit(
        self,
        node: Node,
        symbols: list[ExtractedSymbol],
        parent_stack: list[str],
    ) -> None:
        node_type = node.type

        if node_type in self.spec.function_nodes:
            symbol = self._build_function(node, parent_stack)
            if symbol is not None:
                symbols.append(symbol)
                # Recurse for nested functions / local classes, scoped under this one.
                parent_stack.append(symbol.name)
                for child in node.children:
                    self._visit(child, symbols, parent_stack)
                parent_stack.pop()
            return

        if node_type in self._container_map:
            symbol = self._build_container(node, self._container_map[node_type])
            if symbol is not None:
                symbols.append(symbol)
                parent_stack.append(symbol.name)
                for child in node.children:
                    self._visit(child, symbols, parent_stack)
                parent_stack.pop()
                return

        if node_type in self.spec.scope_nodes:
            scope_name = self._scope_name(node)
            if scope_name:
                parent_stack.append(scope_name)
                for child in node.children:
                    self._visit(child, symbols, parent_stack)
                parent_stack.pop()
                return

        for child in node.children:
            self._visit(child, symbols, parent_stack)

    def _build_function(
        self, node: Node, parent_stack: list[str]
    ) -> ExtractedSymbol | None:
        parent_name: str | None = parent_stack[-1] if parent_stack else None

        if self.spec.method_receiver and node.type == "method_declaration":
            receiver = self._go_receiver_type(node)
            if receiver:
                parent_name = receiver

        name = self._function_name(node)
        if not name:
            return None

        symbol_type = "method" if parent_name else "function"
        qualified = f"{parent_name}.{name}" if parent_name else name
        return ExtractedSymbol(
            name=name,
            qualified_name=qualified,
            symbol_type=symbol_type,
            signature=self._signature(node),
            docstring=None,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=self._is_exported(node, name),
            is_async=self._is_async(node),
            parent_name=parent_name,
        )

    def _build_container(self, node: Node, symbol_type: str) -> ExtractedSymbol | None:
        name = self._node_name(node)
        if not name:
            return None
        return ExtractedSymbol(
            name=name,
            qualified_name=name,
            symbol_type=symbol_type,
            signature=self._signature(node),
            docstring=None,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=self._is_exported(node, name),
        )

    # ------------------------------------------------------------------
    # Name resolution
    # ------------------------------------------------------------------
    def _node_name(self, node: Node) -> str:
        field = node.child_by_field_name(self.spec.name_field)
        if field is not None:
            return self._text(field).split("::")[-1]
        for child in node.children:
            if child.type in NAME_NODE_TYPES:
                return self._text(child).split("::")[-1]
        return ""

    def _function_name(self, node: Node) -> str:
        field = node.child_by_field_name(self.spec.name_field)
        if field is not None:
            return self._text(field).split("::")[-1]
        if self.spec.declarator_fallback:
            declarator = self._find_descendant(node, {"function_declarator"})
            if declarator is not None:
                ident = self._find_descendant(
                    declarator,
                    {
                        "identifier",
                        "field_identifier",
                        "qualified_identifier",
                        "scoped_identifier",
                        "operator_name",
                        "destructor_name",
                    },
                )
                if ident is not None:
                    return self._text(ident).split("::")[-1]
        for child in node.children:
            if child.type in NAME_NODE_TYPES:
                return self._text(child).split("::")[-1]
        return ""

    def _scope_name(self, node: Node) -> str:
        """Name of a non-emitted scope (e.g. ``impl Foo`` -> ``Foo``)."""
        type_field = node.child_by_field_name("type")
        if type_field is not None:
            return self._text(type_field).split("::")[-1].split("<")[0].strip()
        for child in node.children:
            if child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                return self._text(child).split("::")[-1].split("<")[0].strip()
        return ""

    def _go_receiver_type(self, node: Node) -> str:
        """Resolve ``func (s *Server) Foo()`` -> ``Server``."""
        receiver = node.child_by_field_name("receiver")
        if receiver is None:
            for child in node.children:
                if child.type == "parameter_list":
                    receiver = child
                    break
        if receiver is None:
            return ""
        ident = self._find_descendant(receiver, {"type_identifier"})
        return self._text(ident) if ident is not None else ""

    # ------------------------------------------------------------------
    # Visibility / async heuristics
    # ------------------------------------------------------------------
    def _is_exported(self, node: Node, name: str) -> bool:
        mode = self.spec.exported
        if mode == "go":
            return bool(name) and name[0].isupper()
        if mode == "rust":
            return any(child.type == "visibility_modifier" for child in node.children)
        if mode == "always":
            return not name.startswith("_")
        return not name.startswith("_")

    def _is_async(self, node: Node) -> bool:
        text = self._text(node)[:60]
        return text.lstrip().startswith("async ") or " async " in text[:30]

    # ------------------------------------------------------------------
    # Signature
    # ------------------------------------------------------------------
    def _signature(self, node: Node) -> str:
        body = None
        for child in node.children:
            if child.type in BODY_NODE_TYPES:
                body = child
                break
        raw = (
            node.text[: body.start_byte - node.start_byte]
            if body is not None
            else node.text
        )
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        text = " ".join(text.split()).strip().rstrip("{(:").strip()
        if len(text) > _MAX_SIGNATURE_CHARS:
            text = text[:_MAX_SIGNATURE_CHARS] + "…"
        return text

    # ------------------------------------------------------------------
    # Code regions (AST-aware chunking)
    # ------------------------------------------------------------------
    def create_code_regions(self, content: str) -> list[CodeRegion]:
        tree = self.parse(content)
        lines = content.split("\n")
        regions: list[CodeRegion] = []

        import_start: int | None = None
        import_end: int | None = None

        def flush_imports() -> None:
            nonlocal import_start, import_end
            if import_start is not None and import_end is not None:
                regions.append(
                    CodeRegion(
                        content="\n".join(lines[import_start : import_end + 1]),
                        start_line=import_start + 1,
                        end_line=import_end + 1,
                        region_type="imports",
                        symbols=[],
                    )
                )
            import_start = None
            import_end = None

        top_level = self._top_level_definitions(tree.root_node)
        for child in top_level:
            if child.type in self.spec.import_nodes:
                if import_start is None:
                    import_start = child.start_point[0]
                import_end = child.end_point[0]
                continue

            is_function = child.type in self.spec.function_nodes
            is_container = child.type in self._container_map
            if not (is_function or is_container):
                continue

            flush_imports()
            name = (
                self._function_name(child) if is_function else self._node_name(child)
            )
            start = child.start_point[0]
            end = child.end_point[0]
            regions.append(
                CodeRegion(
                    content="\n".join(lines[start : end + 1]),
                    start_line=start + 1,
                    end_line=end + 1,
                    region_type="class" if is_container else "function",
                    symbols=[name] if name else [],
                )
            )

        flush_imports()

        if not regions and lines:
            regions.append(
                CodeRegion(
                    content=content,
                    start_line=1,
                    end_line=len(lines),
                    region_type="code",
                    symbols=[],
                )
            )
        return regions

    def _top_level_definitions(self, root: Node) -> list[Node]:
        """Flatten through wrapper nodes (e.g. PHP ``program``, C# namespaces)
        so top-level defs are discoverable even when nested one level deep."""
        result: list[Node] = []
        for child in root.children:
            if (
                child.type in self.spec.function_nodes
                or child.type in self._container_map
                or child.type in self.spec.import_nodes
            ):
                result.append(child)
            elif child.type in (
                "namespace_definition",
                "declaration_list",
                "namespace_use_declaration",
                "preproc_if",
                "linkage_specification",
            ):
                result.extend(self._top_level_definitions(child))
        return result

    # ------------------------------------------------------------------
    # Call / import extraction for the code graph
    # ------------------------------------------------------------------
    def extract_calls(self, content: str) -> list[CallSite]:
        """Return call sites grouped by the enclosing function (best-effort).

        ``caller`` is the qualified name of the enclosing function (or
        ``"<module>"`` for top-level calls); ``callee`` is the called name.
        """
        if not self.spec.call_nodes:
            return []
        tree = self.parse(content)
        calls: list[CallSite] = []
        self._collect_calls(tree.root_node, calls, scope=[], parent_stack=[])
        return calls

    def _collect_calls(
        self,
        node: Node,
        calls: list[CallSite],
        scope: list[str],
        parent_stack: list[str],
    ) -> None:
        node_type = node.type
        pushed_scope = False
        pushed_parent = False

        if node_type in self.spec.function_nodes:
            parent = parent_stack[-1] if parent_stack else None
            if self.spec.method_receiver and node_type == "method_declaration":
                receiver = self._go_receiver_type(node)
                if receiver:
                    parent = receiver
            name = self._function_name(node)
            if name:
                qualified = f"{parent}.{name}" if parent else name
                scope.append(qualified)
                parent_stack.append(name)
                pushed_scope = True
                pushed_parent = True
        elif node_type in self._container_map:
            name = self._node_name(node)
            if name:
                parent_stack.append(name)
                pushed_parent = True
        elif node_type in self.spec.scope_nodes:
            name = self._scope_name(node)
            if name:
                parent_stack.append(name)
                pushed_parent = True

        if node_type in self.spec.call_nodes:
            callee = self._callee_name(node)
            if callee:
                caller = scope[-1] if scope else "<module>"
                calls.append(CallSite(caller, callee, node.start_point[0] + 1))

        for child in node.children:
            self._collect_calls(child, calls, scope, parent_stack)

        if pushed_scope:
            scope.pop()
        if pushed_parent:
            parent_stack.pop()

    def _callee_name(self, node: Node) -> str:
        func = node.child_by_field_name("function")
        if func is None:
            func = node.child_by_field_name("name")
        if func is None:
            # Macro invocation / generic: first identifier-ish child.
            for child in node.children:
                if child.type in NAME_NODE_TYPES or child.type.endswith("identifier"):
                    func = child
                    break
        if func is None:
            return ""
        text = self._text(func)
        # Reduce ``a.b.c`` / ``a::b`` / ``$obj->method`` to the final component.
        for sep in ("->", "::", "."):
            if sep in text:
                text = text.split(sep)[-1]
        text = text.strip().strip("$&*")
        if not text or not (text[0].isalpha() or text[0] == "_"):
            return ""
        return text

    def extract_imports(self, content: str) -> list[str]:
        if not self.spec.import_nodes:
            return []
        tree = self.parse(content)
        imports: list[str] = []

        def walk(node: Node) -> None:
            if node.type in self.spec.import_nodes:
                imports.append(self._text(node).strip())
                return
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return imports

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _find_descendant(self, node: Node, types: set[str]) -> Node | None:
        for child in node.children:
            if child.type in types:
                return child
        for child in node.children:
            found = self._find_descendant(child, types)
            if found is not None:
                return found
        return None

    @staticmethod
    def _text(node: Node | None) -> str:
        if node is None or node.text is None:
            return ""
        return node.text.decode("utf-8", errors="replace")
