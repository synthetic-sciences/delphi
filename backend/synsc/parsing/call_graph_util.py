"""Shared, language-agnostic call extraction for the code-dependency graph.

Given a tree-sitter root node plus a small node-type configuration, walk the
tree while tracking the enclosing function/type scope and emit a flat list of
:class:`CallSite` (``caller`` qualified name, ``callee`` name, line). The same
helpers drive the generic parser, the Python parser, and the TypeScript/JS
parser so all languages produce uniform edges for the graph.
"""
from __future__ import annotations

from tree_sitter import Node

# Node types that commonly hold a symbol/callee name.
NAME_NODE_TYPES: frozenset[str] = frozenset(
    {
        "identifier",
        "type_identifier",
        "field_identifier",
        "constant",
        "name",
        "scoped_identifier",
        "qualified_identifier",
        "property_identifier",
    }
)

_MODULE_SCOPE = "<module>"


class CallSite:
    """A single call discovered inside a function body."""

    __slots__ = ("caller", "callee", "line")

    def __init__(self, caller: str, callee: str, line: int) -> None:
        self.caller = caller
        self.callee = callee
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CallSite(caller={self.caller!r}, callee={self.callee!r}, line={self.line})"


def node_text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def find_descendant(node: Node, types: set[str]) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    for child in node.children:
        found = find_descendant(child, types)
        if found is not None:
            return found
    return None


def reduce_callee(text: str) -> str:
    """Reduce ``a.b.c`` / ``a::b`` / ``$obj->method`` to the final component."""
    for sep in ("->", "::", "."):
        if sep in text:
            text = text.split(sep)[-1]
    return text.strip().strip("$&*!?")


def callee_name(node: Node) -> str:
    """Best-effort callee identifier for a call-expression node."""
    func = node.child_by_field_name("function")
    if func is None:
        func = node.child_by_field_name("name")
    if func is None:
        for child in node.children:
            if child.type in NAME_NODE_TYPES or child.type.endswith("identifier"):
                func = child
                break
    if func is None:
        return ""
    name = reduce_callee(node_text(func))
    if not name or not (name[0].isalpha() or name[0] == "_"):
        return ""
    return name


def function_name(node: Node, name_field: str, declarator_fallback: bool) -> str:
    field = node.child_by_field_name(name_field)
    if field is not None:
        return node_text(field).split("::")[-1]
    if declarator_fallback:
        declarator = find_descendant(node, {"function_declarator"})
        if declarator is not None:
            ident = find_descendant(
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
                return node_text(ident).split("::")[-1]
    for child in node.children:
        if child.type in NAME_NODE_TYPES:
            return node_text(child).split("::")[-1]
    return ""


def node_name(node: Node, name_field: str) -> str:
    field = node.child_by_field_name(name_field)
    if field is not None:
        return node_text(field).split("::")[-1]
    for child in node.children:
        if child.type in NAME_NODE_TYPES:
            return node_text(child).split("::")[-1]
    return ""


def scope_name(node: Node) -> str:
    """Name of a non-emitted scope (e.g. Rust ``impl Foo`` -> ``Foo``)."""
    type_field = node.child_by_field_name("type")
    if type_field is not None:
        return node_text(type_field).split("::")[-1].split("<")[0].strip()
    for child in node.children:
        if child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
            return node_text(child).split("::")[-1].split("<")[0].strip()
    return ""


def go_receiver_type(node: Node) -> str:
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        for child in node.children:
            if child.type == "parameter_list":
                receiver = child
                break
    if receiver is None:
        return ""
    ident = find_descendant(receiver, {"type_identifier"})
    return node_text(ident) if ident is not None else ""


def extract_scoped_calls(
    root: Node,
    *,
    function_nodes: frozenset[str],
    container_nodes: frozenset[str],
    call_nodes: frozenset[str],
    scope_nodes: frozenset[str] = frozenset(),
    name_field: str = "name",
    declarator_fallback: bool = False,
    method_receiver: bool = False,
) -> list[CallSite]:
    """Walk the tree and emit call sites scoped to their enclosing function."""
    if not call_nodes:
        return []

    calls: list[CallSite] = []

    def walk(node: Node, scope: list[str], parent_stack: list[str]) -> None:
        node_type = node.type
        pushed_scope = False
        pushed_parent = False

        if node_type in function_nodes:
            parent = parent_stack[-1] if parent_stack else None
            if method_receiver and node_type == "method_declaration":
                receiver = go_receiver_type(node)
                if receiver:
                    parent = receiver
            name = function_name(node, name_field, declarator_fallback)
            if name:
                qualified = f"{parent}.{name}" if parent else name
                scope.append(qualified)
                parent_stack.append(name)
                pushed_scope = True
                pushed_parent = True
        elif node_type in container_nodes:
            name = node_name(node, name_field)
            if name:
                parent_stack.append(name)
                pushed_parent = True
        elif node_type in scope_nodes:
            name = scope_name(node)
            if name:
                parent_stack.append(name)
                pushed_parent = True

        if node_type in call_nodes:
            callee = callee_name(node)
            if callee:
                caller = scope[-1] if scope else _MODULE_SCOPE
                calls.append(CallSite(caller, callee, node.start_point[0] + 1))

        for child in node.children:
            walk(child, scope, parent_stack)

        if pushed_scope:
            scope.pop()
        if pushed_parent:
            parent_stack.pop()

    walk(root, [], [])
    return calls
