"""TypeScript/JavaScript parser using tree-sitter."""

from typing import Any

import structlog
import tree_sitter_typescript as ts_typescript
import tree_sitter_javascript as ts_javascript
from tree_sitter import Language, Parser, Node, Tree

from synsc.parsing.base import BaseParser
from synsc.parsing.models import CodeRegion, ExtractedSymbol

logger = structlog.get_logger(__name__)


class TypeScriptParser(BaseParser):
    """Parser for TypeScript/JavaScript source code using tree-sitter.
    
    Extracts functions, classes, methods, interfaces, and type aliases
    with full metadata including signatures, JSDoc comments, and type annotations.
    """
    
    def __init__(self, is_typescript: bool = True) -> None:
        """Initialize the TypeScript/JavaScript parser.
        
        Args:
            is_typescript: If True, use TypeScript parser. If False, use JavaScript.
        """
        self._is_typescript = is_typescript
        if is_typescript:
            self._language = Language(ts_typescript.language_typescript())
        else:
            self._language = Language(ts_javascript.language())
        self._parser = Parser(self._language)
    
    @property
    def language(self) -> str:
        return "typescript" if self._is_typescript else "javascript"
    
    @property
    def supported_extensions(self) -> list[str]:
        if self._is_typescript:
            return [".ts", ".tsx", ".mts", ".cts"]
        return [".js", ".jsx", ".mjs", ".cjs"]
    
    def parse(self, content: str) -> Tree:
        """Parse TypeScript/JavaScript source code into AST.
        
        Args:
            content: Source code
            
        Returns:
            tree-sitter Tree object
        """
        return self._parser.parse(content.encode("utf-8"))
    
    def extract_symbols(self, content: str) -> list[ExtractedSymbol]:
        """Extract all symbols from TypeScript/JavaScript source code.
        
        Extracts:
        - Functions (including arrow functions assigned to const)
        - Classes
        - Methods
        - Interfaces (TypeScript)
        - Type aliases (TypeScript)
        
        Args:
            content: Source code
            
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
        """Recursively visit AST nodes to extract symbols."""
        
        # Function declaration: function foo() {}
        if node.type == "function_declaration":
            symbol = self._extract_function(node, lines, parent_name)
            if symbol:
                symbols.append(symbol)
        
        # Arrow function or function expression assigned to variable
        # const foo = () => {} or const foo = function() {}
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    symbol = self._extract_variable_function(child, lines)
                    if symbol:
                        symbols.append(symbol)
        
        # Class declaration
        elif node.type == "class_declaration":
            symbol = self._extract_class(node, lines)
            if symbol:
                symbols.append(symbol)
                # Extract methods
                self._extract_class_members(node, lines, symbols, symbol.name)
            return  # Don't recurse into class body
        
        # Interface declaration (TypeScript)
        elif node.type == "interface_declaration":
            symbol = self._extract_interface(node, lines)
            if symbol:
                symbols.append(symbol)
            return
        
        # Type alias (TypeScript)
        elif node.type == "type_alias_declaration":
            symbol = self._extract_type_alias(node, lines)
            if symbol:
                symbols.append(symbol)
            return
        
        # Export statements - look inside them
        elif node.type in ("export_statement", "export_default_declaration"):
            for child in node.children:
                self._visit_node(child, lines, symbols, parent_name)
            return
        
        # Recurse into children
        for child in node.children:
            self._visit_node(child, lines, symbols, parent_name)
    
    def _extract_function(
        self,
        node: Node,
        lines: list[str],
        parent_name: str | None = None,
    ) -> ExtractedSymbol | None:
        """Extract a function declaration."""
        name = ""
        parameters: list[dict[str, Any]] = []
        return_type: str | None = None
        is_async = False
        is_exported = False
        
        # Check for export and async
        parent = node.parent
        if parent:
            if parent.type == "export_statement":
                is_exported = True
            prev = node.prev_sibling
            while prev:
                if prev.type == "async":
                    is_async = True
                    break
                prev = prev.prev_sibling
        
        # Parse function components
        for child in node.children:
            if child.type == "identifier":
                name = self._get_node_text(child)
            elif child.type == "formal_parameters":
                parameters = self._extract_parameters(child)
            elif child.type == "type_annotation":
                return_type = self._get_type_annotation(child)
            elif child.type == "async":
                is_async = True
        
        if not name:
            return None
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        qualified_name = f"{parent_name}.{name}" if parent_name else name
        docstring = self._extract_jsdoc(node, lines)
        signature = self._build_function_signature(node, lines)
        
        symbol_type = "method" if parent_name else "function"
        
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
        )
    
    def _extract_variable_function(
        self,
        node: Node,
        lines: list[str],
    ) -> ExtractedSymbol | None:
        """Extract function from variable declaration (arrow function or function expression)."""
        name = ""
        func_node = None
        
        for child in node.children:
            if child.type == "identifier":
                name = self._get_node_text(child)
            elif child.type in ("arrow_function", "function_expression", "function"):
                func_node = child
        
        if not name or not func_node:
            return None
        
        parameters: list[dict[str, Any]] = []
        return_type: str | None = None
        is_async = False
        
        for child in func_node.children:
            if child.type == "formal_parameters":
                parameters = self._extract_parameters(child)
            elif child.type == "identifier" and func_node.type == "arrow_function":
                # Single parameter arrow function: x => x * 2
                parameters = [{"name": self._get_node_text(child), "type": None, "default": None}]
            elif child.type == "type_annotation":
                return_type = self._get_type_annotation(child)
            elif child.type == "async":
                is_async = True
        
        # Check if parent declaration is exported
        is_exported = False
        parent = node.parent
        while parent:
            if parent.type == "export_statement":
                is_exported = True
                break
            parent = parent.parent
        
        # Use the variable declarator's parent for line info
        decl_node = node.parent if node.parent else node
        start_line = decl_node.start_point[0] + 1
        end_line = decl_node.end_point[0] + 1
        
        docstring = self._extract_jsdoc(decl_node, lines)
        signature = self._build_variable_signature(node, lines)
        
        return ExtractedSymbol(
            name=name,
            qualified_name=name,
            symbol_type="function",
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_async=is_async,
            is_exported=is_exported,
            parameters=parameters if parameters else None,
            return_type=return_type,
        )
    
    def _extract_class(
        self,
        node: Node,
        lines: list[str],
    ) -> ExtractedSymbol | None:
        """Extract a class declaration."""
        name = ""
        is_exported = False
        
        parent = node.parent
        if parent and parent.type == "export_statement":
            is_exported = True
        
        for child in node.children:
            if child.type == "type_identifier" or child.type == "identifier":
                name = self._get_node_text(child)
                break
        
        if not name:
            return None
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        docstring = self._extract_jsdoc(node, lines)
        signature = self._build_class_signature(node, lines)
        
        return ExtractedSymbol(
            name=name,
            qualified_name=name,
            symbol_type="class",
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_exported=is_exported,
        )
    
    def _extract_class_members(
        self,
        class_node: Node,
        lines: list[str],
        symbols: list[ExtractedSymbol],
        class_name: str,
    ) -> None:
        """Extract methods and properties from a class."""
        for child in class_node.children:
            if child.type == "class_body":
                for member in child.children:
                    if member.type == "method_definition":
                        symbol = self._extract_method(member, lines, class_name)
                        if symbol:
                            symbols.append(symbol)
                    elif member.type == "public_field_definition":
                        # Arrow function as class property
                        symbol = self._extract_class_property(member, lines, class_name)
                        if symbol:
                            symbols.append(symbol)
    
    def _extract_method(
        self,
        node: Node,
        lines: list[str],
        class_name: str,
    ) -> ExtractedSymbol | None:
        """Extract a method definition."""
        name = ""
        parameters: list[dict[str, Any]] = []
        return_type: str | None = None
        is_async = False
        is_static = False
        
        for child in node.children:
            if child.type == "property_identifier":
                name = self._get_node_text(child)
            elif child.type == "formal_parameters":
                parameters = self._extract_parameters(child)
            elif child.type == "type_annotation":
                return_type = self._get_type_annotation(child)
            elif child.type == "async":
                is_async = True
            elif child.type == "static":
                is_static = True
        
        if not name:
            return None
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        qualified_name = f"{class_name}.{name}"
        docstring = self._extract_jsdoc(node, lines)
        signature = self._build_method_signature(node, lines)
        
        return ExtractedSymbol(
            name=name,
            qualified_name=qualified_name,
            symbol_type="method",
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_async=is_async,
            is_exported=True,  # Methods are exported with the class
            parameters=parameters if parameters else None,
            return_type=return_type,
            parent_name=class_name,
        )
    
    def _extract_class_property(
        self,
        node: Node,
        lines: list[str],
        class_name: str,
    ) -> ExtractedSymbol | None:
        """Extract a class property (especially arrow function properties)."""
        name = ""
        is_function = False
        
        for child in node.children:
            if child.type == "property_identifier":
                name = self._get_node_text(child)
            elif child.type == "arrow_function":
                is_function = True
        
        if not name or not is_function:
            return None
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        qualified_name = f"{class_name}.{name}"
        
        return ExtractedSymbol(
            name=name,
            qualified_name=qualified_name,
            symbol_type="method",
            signature=lines[start_line - 1].strip() if start_line <= len(lines) else "",
            start_line=start_line,
            end_line=end_line,
            is_exported=True,
            parent_name=class_name,
        )
    
    def _extract_interface(
        self,
        node: Node,
        lines: list[str],
    ) -> ExtractedSymbol | None:
        """Extract an interface declaration (TypeScript)."""
        name = ""
        is_exported = False
        
        parent = node.parent
        if parent and parent.type == "export_statement":
            is_exported = True
        
        for child in node.children:
            if child.type == "type_identifier":
                name = self._get_node_text(child)
                break
        
        if not name:
            return None
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        docstring = self._extract_jsdoc(node, lines)
        signature = self._build_interface_signature(node, lines)
        
        return ExtractedSymbol(
            name=name,
            qualified_name=name,
            symbol_type="interface",
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            is_exported=is_exported,
        )
    
    def _extract_type_alias(
        self,
        node: Node,
        lines: list[str],
    ) -> ExtractedSymbol | None:
        """Extract a type alias declaration (TypeScript)."""
        name = ""
        is_exported = False
        
        parent = node.parent
        if parent and parent.type == "export_statement":
            is_exported = True
        
        for child in node.children:
            if child.type == "type_identifier":
                name = self._get_node_text(child)
                break
        
        if not name:
            return None
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        signature = lines[start_line - 1].strip() if start_line <= len(lines) else ""
        
        return ExtractedSymbol(
            name=name,
            qualified_name=name,
            symbol_type="type",
            signature=signature,
            start_line=start_line,
            end_line=end_line,
            is_exported=is_exported,
        )
    
    def _extract_parameters(self, node: Node) -> list[dict[str, Any]]:
        """Extract function parameters."""
        params: list[dict[str, Any]] = []
        
        for child in node.children:
            if child.type == "required_parameter":
                param = self._extract_typed_param(child)
                if param:
                    params.append(param)
            elif child.type == "optional_parameter":
                param = self._extract_typed_param(child, optional=True)
                if param:
                    params.append(param)
            elif child.type == "rest_parameter":
                param = self._extract_rest_param(child)
                if param:
                    params.append(param)
            elif child.type == "identifier":
                name = self._get_node_text(child)
                if name not in ("(", ")", ","):
                    params.append({"name": name, "type": None, "default": None})
        
        return params
    
    def _extract_typed_param(self, node: Node, optional: bool = False) -> dict[str, Any] | None:
        """Extract a typed parameter."""
        name = ""
        param_type = None
        default = None
        
        for child in node.children:
            if child.type == "identifier":
                name = self._get_node_text(child)
            elif child.type == "type_annotation":
                param_type = self._get_type_annotation(child)
            elif child.type not in (":", "=", "?"):
                if name and child.type not in ("type_annotation",):
                    default = self._get_node_text(child)
        
        if name:
            return {"name": name + ("?" if optional else ""), "type": param_type, "default": default}
        return None
    
    def _extract_rest_param(self, node: Node) -> dict[str, Any] | None:
        """Extract a rest parameter (...args)."""
        name = ""
        param_type = None
        
        for child in node.children:
            if child.type == "identifier":
                name = self._get_node_text(child)
            elif child.type == "type_annotation":
                param_type = self._get_type_annotation(child)
        
        if name:
            return {"name": "..." + name, "type": param_type, "default": None}
        return None
    
    def _get_type_annotation(self, node: Node) -> str:
        """Get the type from a type annotation node."""
        for child in node.children:
            if child.type != ":":
                return self._get_node_text(child)
        return ""
    
    def _extract_jsdoc(self, node: Node, lines: list[str]) -> str | None:
        """Extract JSDoc comment preceding a node."""
        # Look at previous sibling for comment
        prev = node.prev_sibling
        while prev:
            if prev.type == "comment":
                text = self._get_node_text(prev)
                if text.startswith("/**"):
                    # Clean up JSDoc
                    return self._clean_jsdoc(text)
            elif prev.type not in ("decorator",):
                break
            prev = prev.prev_sibling
        return None
    
    def _clean_jsdoc(self, text: str) -> str:
        """Clean up JSDoc comment text."""
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            line = line.strip()
            if line.startswith("/**"):
                line = line[3:].strip()
            if line.endswith("*/"):
                line = line[:-2].strip()
            if line.startswith("*"):
                line = line[1:].strip()
            if line:
                cleaned.append(line)
        return "\n".join(cleaned)
    
    def _build_function_signature(self, node: Node, lines: list[str]) -> str:
        """Build function signature string."""
        start_line = node.start_point[0]
        if start_line < len(lines):
            line = lines[start_line]
            # Find opening brace and cut there
            brace_pos = line.find("{")
            if brace_pos > 0:
                return line[:brace_pos].strip()
            return line.strip()
        return ""
    
    def _build_variable_signature(self, node: Node, lines: list[str]) -> str:
        """Build signature for variable-assigned function."""
        parent = node.parent
        if parent:
            start_line = parent.start_point[0]
            if start_line < len(lines):
                line = lines[start_line]
                brace_pos = line.find("{")
                arrow_pos = line.find("=>")
                if brace_pos > 0:
                    return line[:brace_pos].strip()
                elif arrow_pos > 0:
                    return line[:arrow_pos + 2].strip()
                return line.strip()
        return ""
    
    def _build_class_signature(self, node: Node, lines: list[str]) -> str:
        """Build class signature string."""
        start_line = node.start_point[0]
        if start_line < len(lines):
            line = lines[start_line]
            brace_pos = line.find("{")
            if brace_pos > 0:
                return line[:brace_pos].strip()
            return line.strip()
        return ""
    
    def _build_method_signature(self, node: Node, lines: list[str]) -> str:
        """Build method signature string."""
        start_line = node.start_point[0]
        if start_line < len(lines):
            line = lines[start_line].strip()
            brace_pos = line.find("{")
            if brace_pos > 0:
                return line[:brace_pos].strip()
            return line
        return ""
    
    def _build_interface_signature(self, node: Node, lines: list[str]) -> str:
        """Build interface signature string."""
        start_line = node.start_point[0]
        if start_line < len(lines):
            line = lines[start_line]
            brace_pos = line.find("{")
            if brace_pos > 0:
                return line[:brace_pos].strip()
            return line.strip()
        return ""
    
    def _get_node_text(self, node: Node) -> str:
        """Get text content of a node."""
        if node.text:
            return node.text.decode("utf-8")
        return ""
    
    def create_code_regions(self, content: str) -> list[CodeRegion]:
        """Split TypeScript/JavaScript code into semantic regions."""
        tree = self.parse(content)
        lines = content.split("\n")
        regions: list[CodeRegion] = []
        
        # Track imports
        imports_start: int | None = None
        imports_end: int | None = None
        
        def flush_imports() -> None:
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
            # Import statements
            if child.type == "import_statement":
                if imports_start is None:
                    imports_start = child.start_point[0]
                imports_end = child.end_point[0]
                continue
            
            # Function, class, interface definitions
            if child.type in (
                "function_declaration",
                "class_declaration",
                "interface_declaration",
                "type_alias_declaration",
                "lexical_declaration",
                "export_statement",
            ):
                flush_imports()
                
                start = child.start_point[0]
                end = child.end_point[0]
                region_content = "\n".join(lines[start:end + 1])
                
                # Determine region type
                region_type = "code"
                if child.type == "function_declaration":
                    region_type = "function"
                elif child.type == "class_declaration":
                    region_type = "class"
                elif child.type == "interface_declaration":
                    region_type = "interface"
                elif child.type == "type_alias_declaration":
                    region_type = "type"
                elif child.type == "export_statement":
                    # Look inside export
                    for sub in child.children:
                        if sub.type == "function_declaration":
                            region_type = "function"
                        elif sub.type == "class_declaration":
                            region_type = "class"
                
                regions.append(CodeRegion(
                    content=region_content,
                    start_line=start + 1,
                    end_line=end + 1,
                    region_type=region_type,
                    symbols=[],
                ))
        
        flush_imports()
        
        if not regions and lines:
            regions.append(CodeRegion(
                content=content,
                start_line=1,
                end_line=len(lines),
                region_type="code",
                symbols=[],
            ))
        
        return regions


class JavaScriptParser(TypeScriptParser):
    """Parser for JavaScript source code using tree-sitter."""
    
    def __init__(self) -> None:
        """Initialize the JavaScript parser."""
        super().__init__(is_typescript=False)
