"""Python parser using tree-sitter."""

from typing import Any

import structlog
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node, Tree

from synsc.parsing.base import BaseParser
from synsc.parsing.models import CodeRegion, ExtractedSymbol

logger = structlog.get_logger(__name__)


class PythonParser(BaseParser):
    """Parser for Python source code using tree-sitter.
    
    Extracts functions, classes, methods with full metadata
    including signatures, docstrings, decorators, and type hints.
    """
    
    def __init__(self) -> None:
        """Initialize the Python parser."""
        self._language = Language(tspython.language())
        self._parser = Parser(self._language)
    
    @property
    def language(self) -> str:
        return "python"
    
    @property
    def supported_extensions(self) -> list[str]:
        return [".py", ".pyi"]
    
    def parse(self, content: str) -> Tree:
        """Parse Python source code into AST.
        
        Args:
            content: Python source code
            
        Returns:
            tree-sitter Tree object
        """
        return self._parser.parse(content.encode("utf-8"))
    
    def extract_symbols(self, content: str) -> list[ExtractedSymbol]:
        """Extract all symbols from Python source code.
        
        Extracts:
        - Functions (including async functions)
        - Classes
        - Methods (as children of classes)
        
        Args:
            content: Python source code
            
        Returns:
            List of extracted symbols
        """
        tree = self.parse(content)
        lines = content.split("\n")
        symbols: list[ExtractedSymbol] = []
        
        self._visit_node(tree.root_node, lines, symbols, parent_name=None)
        
        return symbols
    
    def _visit_node(
        self,
        node: Node,
        lines: list[str],
        symbols: list[ExtractedSymbol],
        parent_name: str | None,
    ) -> None:
        """Recursively visit AST nodes to extract symbols.
        
        Args:
            node: Current AST node
            lines: Source code lines
            symbols: List to append extracted symbols to
            parent_name: Name of parent class (for methods)
        """
        if node.type == "function_definition":
            symbol = self._extract_function(node, lines, parent_name)
            symbols.append(symbol)
            # Don't recurse into function body for nested functions
            # (we only want top-level and method definitions)
            
        elif node.type == "class_definition":
            symbol = self._extract_class(node, lines)
            symbols.append(symbol)
            
            # Extract methods from class body
            class_name = symbol.name
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "function_definition":
                            method = self._extract_function(stmt, lines, class_name)
                            symbol.children.append(method)
                            symbols.append(method)
                        elif stmt.type == "decorated_definition":
                            # Handle decorated methods
                            for sub in stmt.children:
                                if sub.type == "function_definition":
                                    method = self._extract_function(
                                        sub, lines, class_name, decorated_node=stmt
                                    )
                                    symbol.children.append(method)
                                    symbols.append(method)
            return  # Don't recurse further for class
        
        elif node.type == "decorated_definition":
            # Handle decorated functions/classes at module level
            for child in node.children:
                if child.type == "function_definition":
                    symbol = self._extract_function(
                        child, lines, parent_name, decorated_node=node
                    )
                    symbols.append(symbol)
                elif child.type == "class_definition":
                    symbol = self._extract_class(child, lines, decorated_node=node)
                    symbols.append(symbol)
                    
                    # Extract methods
                    class_name = symbol.name
                    for sub in child.children:
                        if sub.type == "block":
                            for stmt in sub.children:
                                if stmt.type == "function_definition":
                                    method = self._extract_function(stmt, lines, class_name)
                                    symbol.children.append(method)
                                    symbols.append(method)
                                elif stmt.type == "decorated_definition":
                                    for subsub in stmt.children:
                                        if subsub.type == "function_definition":
                                            method = self._extract_function(
                                                subsub, lines, class_name, decorated_node=stmt
                                            )
                                            symbol.children.append(method)
                                            symbols.append(method)
            return
        
        # Recurse into children
        for child in node.children:
            self._visit_node(child, lines, symbols, parent_name)
    
    def _extract_function(
        self,
        node: Node,
        lines: list[str],
        parent_name: str | None = None,
        decorated_node: Node | None = None,
    ) -> ExtractedSymbol:
        """Extract a function or method definition.
        
        Args:
            node: function_definition AST node
            lines: Source code lines
            parent_name: Name of parent class (for methods)
            decorated_node: Parent decorated_definition node if decorated
            
        Returns:
            ExtractedSymbol for the function
        """
        name = ""
        parameters: list[dict[str, Any]] = []
        return_type: str | None = None
        is_async = False
        
        # Check if async (look at previous sibling or parent)
        prev = node.prev_sibling
        if prev and prev.type == "async":
            is_async = True
        
        # Parse function components
        for child in node.children:
            if child.type == "name" or child.type == "identifier":
                name = self._get_node_text(child)
            elif child.type == "parameters":
                parameters = self._extract_parameters(child)
            elif child.type == "type":
                return_type = self._get_node_text(child)
            # Handle return type annotation after ->
            elif child.type == "->" or (child.prev_sibling and child.prev_sibling.type == "->"):
                if child.type != "->":
                    return_type = self._get_node_text(child)
        
        # Get decorators
        decorators = self._extract_decorators(decorated_node or node)
        
        # Determine start line (include decorators)
        if decorated_node:
            start_line = decorated_node.start_point[0] + 1
        else:
            start_line = node.start_point[0] + 1
        
        end_line = node.end_point[0] + 1
        
        # Build qualified name
        qualified_name = f"{parent_name}.{name}" if parent_name else name
        
        # Get docstring
        docstring = self._extract_docstring(node)
        
        # Build signature
        signature = self._build_signature(node, lines, is_async, decorated_node)
        
        # Determine symbol type
        symbol_type = "method" if parent_name else "function"
        
        # Check for special methods
        is_exported = not name.startswith("_") or name.startswith("__") and name.endswith("__")
        
        return ExtractedSymbol(
            name=name,
            qualified_name=qualified_name,
            symbol_type=symbol_type,
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_async=is_async,
            is_exported=is_exported,
            parameters=parameters if parameters else None,
            return_type=return_type,
            decorators=decorators if decorators else None,
            parent_name=parent_name,
        )
    
    def _extract_class(
        self,
        node: Node,
        lines: list[str],
        decorated_node: Node | None = None,
    ) -> ExtractedSymbol:
        """Extract a class definition.
        
        Args:
            node: class_definition AST node
            lines: Source code lines
            decorated_node: Parent decorated_definition node if decorated
            
        Returns:
            ExtractedSymbol for the class
        """
        name = ""
        
        for child in node.children:
            if child.type == "name" or child.type == "identifier":
                name = self._get_node_text(child)
                break
        
        # Get decorators
        decorators = self._extract_decorators(decorated_node or node)
        
        # Determine start line (include decorators)
        if decorated_node:
            start_line = decorated_node.start_point[0] + 1
        else:
            start_line = node.start_point[0] + 1
        
        end_line = node.end_point[0] + 1
        
        # Get docstring
        docstring = self._extract_docstring(node)
        
        # Build signature (class declaration line)
        signature = self._build_class_signature(node, lines, decorated_node)
        
        # Check if exported
        is_exported = not name.startswith("_")
        
        return ExtractedSymbol(
            name=name,
            qualified_name=name,
            symbol_type="class",
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_exported=is_exported,
            decorators=decorators if decorators else None,
        )
    
    def _extract_parameters(self, node: Node) -> list[dict[str, Any]]:
        """Extract function parameters.
        
        Args:
            node: parameters AST node
            
        Returns:
            List of parameter dicts with name, type, default
        """
        params: list[dict[str, Any]] = []
        
        for child in node.children:
            if child.type in ("identifier", "name"):
                # Simple parameter without type
                param_name = self._get_node_text(child)
                if param_name not in ("(", ")", ","):
                    params.append({
                        "name": param_name,
                        "type": None,
                        "default": None,
                    })
            elif child.type == "typed_parameter":
                param = self._extract_typed_parameter(child)
                if param:
                    params.append(param)
            elif child.type == "default_parameter":
                param = self._extract_default_parameter(child)
                if param:
                    params.append(param)
            elif child.type == "typed_default_parameter":
                param = self._extract_typed_default_parameter(child)
                if param:
                    params.append(param)
            elif child.type == "list_splat_pattern":
                # *args
                for sub in child.children:
                    if sub.type in ("identifier", "name"):
                        params.append({
                            "name": "*" + self._get_node_text(sub),
                            "type": None,
                            "default": None,
                        })
            elif child.type == "dictionary_splat_pattern":
                # **kwargs
                for sub in child.children:
                    if sub.type in ("identifier", "name"):
                        params.append({
                            "name": "**" + self._get_node_text(sub),
                            "type": None,
                            "default": None,
                        })
        
        return params
    
    def _extract_typed_parameter(self, node: Node) -> dict[str, Any] | None:
        """Extract a typed parameter (name: type)."""
        param_name = ""
        param_type = None
        
        for child in node.children:
            if child.type in ("identifier", "name"):
                param_name = self._get_node_text(child)
            elif child.type == "type":
                param_type = self._get_node_text(child)
        
        if param_name:
            return {"name": param_name, "type": param_type, "default": None}
        return None
    
    def _extract_default_parameter(self, node: Node) -> dict[str, Any] | None:
        """Extract a default parameter (name=value)."""
        param_name = ""
        default = None
        
        for child in node.children:
            if child.type in ("identifier", "name"):
                param_name = self._get_node_text(child)
            elif child.type not in ("=",):
                if param_name:  # Already got name, this is the default
                    default = self._get_node_text(child)
        
        if param_name:
            return {"name": param_name, "type": None, "default": default}
        return None
    
    def _extract_typed_default_parameter(self, node: Node) -> dict[str, Any] | None:
        """Extract a typed default parameter (name: type = value)."""
        param_name = ""
        param_type = None
        default = None
        got_equals = False
        
        for child in node.children:
            if child.type in ("identifier", "name") and not param_name:
                param_name = self._get_node_text(child)
            elif child.type == "type":
                param_type = self._get_node_text(child)
            elif child.type == "=":
                got_equals = True
            elif got_equals:
                default = self._get_node_text(child)
        
        if param_name:
            return {"name": param_name, "type": param_type, "default": default}
        return None
    
    def _extract_decorators(self, node: Node) -> list[str]:
        """Extract decorators from a node.
        
        Args:
            node: AST node (function_definition, class_definition, or decorated_definition)
            
        Returns:
            List of decorator strings
        """
        decorators: list[str] = []
        
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    dec_text = self._get_node_text(child).lstrip("@").strip()
                    decorators.append(dec_text)
        else:
            # Check previous siblings for decorators
            prev = node.prev_sibling
            while prev:
                if prev.type == "decorator":
                    dec_text = self._get_node_text(prev).lstrip("@").strip()
                    decorators.insert(0, dec_text)
                elif prev.type not in ("comment", "async"):
                    break
                prev = prev.prev_sibling
        
        return decorators
    
    def _extract_docstring(self, node: Node) -> str | None:
        """Extract docstring from function/class body.
        
        Args:
            node: function_definition or class_definition node
            
        Returns:
            Docstring content or None
        """
        for child in node.children:
            if child.type == "block":
                for stmt in child.children:
                    if stmt.type == "expression_statement":
                        for expr in stmt.children:
                            if expr.type == "string":
                                text = self._get_node_text(expr)
                                # Strip triple quotes
                                if text.startswith('"""') and text.endswith('"""'):
                                    return text[3:-3].strip()
                                elif text.startswith("'''") and text.endswith("'''"):
                                    return text[3:-3].strip()
                                # Single line string docstring
                                elif text.startswith('"') and text.endswith('"'):
                                    return text[1:-1].strip()
                                elif text.startswith("'") and text.endswith("'"):
                                    return text[1:-1].strip()
                        # Only check first statement
                        break
                break
        return None
    
    def _build_signature(
        self,
        node: Node,
        lines: list[str],
        is_async: bool,
        decorated_node: Node | None = None,
    ) -> str:
        """Build function signature string.
        
        Args:
            node: function_definition node
            lines: Source code lines
            is_async: Whether function is async
            decorated_node: Parent decorated_definition node
            
        Returns:
            Signature string (may be multi-line)
        """
        start_line = node.start_point[0]
        sig_lines: list[str] = []
        
        # Find the colon that ends the signature
        for i in range(start_line, min(start_line + 10, len(lines))):
            line = lines[i]
            sig_lines.append(line)
            # Check if this line ends the signature (ends with : not inside string)
            stripped = line.rstrip()
            if stripped.endswith(":"):
                # Make sure we're not in a multi-line string or something
                if "def " in "\n".join(sig_lines) or not sig_lines[0].strip().startswith("def"):
                    break
        
        signature = "\n".join(sig_lines).rstrip()
        
        # Add async prefix if not already there
        if is_async and not signature.lstrip().startswith("async"):
            signature = "async " + signature.lstrip()
        
        return signature
    
    def _build_class_signature(
        self,
        node: Node,
        lines: list[str],
        decorated_node: Node | None = None,
    ) -> str:
        """Build class signature string.
        
        Args:
            node: class_definition node
            lines: Source code lines
            decorated_node: Parent decorated_definition node
            
        Returns:
            Signature string
        """
        start_line = node.start_point[0]
        
        # Class signature is usually just the first line
        if start_line < len(lines):
            return lines[start_line].rstrip()
        
        return ""
    
    def _get_node_text(self, node: Node) -> str:
        """Get text content of a node.
        
        Args:
            node: AST node
            
        Returns:
            Text content
        """
        if node.text:
            return node.text.decode("utf-8")
        return ""
    
    def create_code_regions(self, content: str) -> list[CodeRegion]:
        """Split Python code into semantic regions.
        
        Creates regions for:
        - Import blocks
        - Module-level docstrings
        - Function definitions
        - Class definitions
        - Other module-level code
        
        Args:
            content: Python source code
            
        Returns:
            List of code regions
        """
        tree = self.parse(content)
        lines = content.split("\n")
        regions: list[CodeRegion] = []
        
        # Track imports
        imports_start: int | None = None
        imports_end: int | None = None
        
        # Track module docstring
        module_docstring_handled = False
        
        def flush_imports() -> None:
            """Emit accumulated imports as a region."""
            nonlocal imports_start, imports_end
            if imports_start is not None and imports_end is not None:
                region_content = "\n".join(lines[imports_start:imports_end + 1])
                regions.append(CodeRegion(
                    content=region_content,
                    start_line=imports_start + 1,
                    end_line=imports_end + 1,
                    region_type="imports",
                    symbols=[],
                ))
                imports_start = None
                imports_end = None
        
        for child in tree.root_node.children:
            # Module docstring (first expression statement with string)
            if (
                not module_docstring_handled
                and child.type == "expression_statement"
                and not regions
                and imports_start is None
            ):
                for expr in child.children:
                    if expr.type == "string":
                        text = self._get_node_text(expr)
                        if text.startswith('"""') or text.startswith("'''"):
                            regions.append(CodeRegion(
                                content=self._get_node_text(child),
                                start_line=child.start_point[0] + 1,
                                end_line=child.end_point[0] + 1,
                                region_type="module_docstring",
                                symbols=[],
                            ))
                            module_docstring_handled = True
                            break
                continue
            
            module_docstring_handled = True  # No longer first statement
            
            # Import statements
            if child.type in ("import_statement", "import_from_statement"):
                if imports_start is None:
                    imports_start = child.start_point[0]
                imports_end = child.end_point[0]
                continue
            
            # Function or class definition
            if child.type in ("function_definition", "class_definition", "decorated_definition"):
                flush_imports()
                
                # Determine the actual definition and get symbol name
                actual_node = child
                symbol_name = ""
                region_type = ""
                
                if child.type == "decorated_definition":
                    for sub in child.children:
                        if sub.type == "function_definition":
                            actual_node = sub
                            region_type = "function"
                            break
                        elif sub.type == "class_definition":
                            actual_node = sub
                            region_type = "class"
                            break
                else:
                    region_type = "class" if child.type == "class_definition" else "function"
                
                # Get symbol name
                for sub in actual_node.children:
                    if sub.type in ("identifier", "name"):
                        symbol_name = self._get_node_text(sub)
                        break
                
                start = child.start_point[0]
                end = child.end_point[0]
                
                region_content = "\n".join(lines[start:end + 1])
                regions.append(CodeRegion(
                    content=region_content,
                    start_line=start + 1,
                    end_line=end + 1,
                    region_type=region_type,
                    symbols=[symbol_name] if symbol_name else [],
                ))
                continue
            
            # Other statements - could accumulate as "code" regions
            # For now, we skip them as they're usually minor
        
        # Flush any remaining imports
        flush_imports()
        
        # If no regions were created, treat entire file as one region
        if not regions and lines:
            regions.append(CodeRegion(
                content=content,
                start_line=1,
                end_line=len(lines),
                region_type="code",
                symbols=[],
            ))
        
        return regions
