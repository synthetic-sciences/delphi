"""Language detection for code files."""

from pathlib import Path

# Extension to language mapping
EXTENSION_MAP: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyi": "python",
    
    # JavaScript
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    
    # TypeScript
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    
    # Rust
    ".rs": "rust",
    
    # Go
    ".go": "go",
    
    # Java
    ".java": "java",
    
    # Kotlin
    ".kt": "kotlin",
    ".kts": "kotlin",
    
    # Swift
    ".swift": "swift",
    
    # C
    ".c": "c",
    ".h": "c",
    
    # C++
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    
    # C#
    ".cs": "csharp",
    
    # Ruby
    ".rb": "ruby",
    
    # PHP
    ".php": "php",
    
    # Scala
    ".scala": "scala",
    
    # Elixir
    ".ex": "elixir",
    ".exs": "elixir",
    
    # Clojure
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    
    # Haskell
    ".hs": "haskell",
    
    # OCaml
    ".ml": "ocaml",
    ".mli": "ocaml",
    
    # Lua
    ".lua": "lua",
    
    # R
    ".r": "r",
    ".R": "r",
    
    # Julia
    ".jl": "julia",
    
    # Shell
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    
    # SQL
    ".sql": "sql",
    
    # GraphQL
    ".graphql": "graphql",
    ".gql": "graphql",
    
    # Protocol Buffers
    ".proto": "protobuf",
    
    # Config
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    
    # Markdown
    ".md": "markdown",
    ".mdx": "markdown",
    
    # CSS
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    
    # HTML
    ".html": "html",
    ".htm": "html",
    
    # Frontend frameworks
    ".vue": "vue",
    ".svelte": "svelte",
    ".astro": "astro",
}


def detect_language(file_path: str | Path) -> str | None:
    """Detect the programming language from file extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Language name or None if unknown
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    return EXTENSION_MAP.get(suffix)


def get_language_extensions(language: str) -> list[str]:
    """Get all file extensions for a language.
    
    Args:
        language: Language name
        
    Returns:
        List of file extensions
    """
    return [ext for ext, lang in EXTENSION_MAP.items() if lang == language]
