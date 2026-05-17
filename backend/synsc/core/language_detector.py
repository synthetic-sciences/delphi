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

    # Infrastructure / IaC
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".hcl": "hcl",
    ".bicep": "bicep",
    ".bzl": "starlark",
    ".dockerfile": "dockerfile",
    ".mk": "makefile",
    ".rst": "restructuredtext",
}

# Basename → language for files that have no extension (Dockerfile, Makefile, etc.)
BASENAME_MAP: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "makefile",
    "GNUmakefile": "makefile",
    "Procfile": "yaml",
    "Vagrantfile": "ruby",
    "Berksfile": "ruby",
    "Gemfile": "ruby",
    "Rakefile": "ruby",
    "Justfile": "makefile",
    "justfile": "makefile",
    "BUILD": "starlark",
    "BUILD.bazel": "starlark",
    "WORKSPACE": "starlark",
    "CMakeLists.txt": "cmake",
    ".env.example": "shell",
    ".env.sample": "shell",
    ".env.template": "shell",
    ".envrc": "shell",
    ".gitignore": "gitignore",
    ".dockerignore": "gitignore",
    ".gitattributes": "gitattributes",
    ".editorconfig": "editorconfig",
    ".prettierrc": "json",
    ".eslintrc": "json",
    ".npmrc": "ini",
    ".yarnrc": "ini",
    ".nvmrc": "text",
    ".python-version": "text",
    ".node-version": "text",
    ".tool-versions": "text",
    ".ruby-version": "text",
    ".rustup-toolchain": "text",
    "go.mod": "go-mod",
    "go.sum": "go-sum",
    "go.work": "go-mod",
    "rust-toolchain": "text",
    "OWNERS": "text",
    "CODEOWNERS": "text",
    "MAINTAINERS": "text",
    "README": "markdown",
    "LICENSE": "text",
    "NOTICE": "text",
    "CHANGELOG": "markdown",
    "AUTHORS": "text",
}


def detect_language(file_path: str | Path) -> str | None:
    """Detect the programming language from file extension or basename.

    Args:
        file_path: Path to the file

    Returns:
        Language name or None if unknown
    """
    path = Path(file_path)

    # Try exact basename first — handles Dockerfile, Makefile, go.mod, etc.
    basename = path.name
    if basename in BASENAME_MAP:
        return BASENAME_MAP[basename]
    # Variants like "Dockerfile.dev", "Makefile.alpine"
    if basename.startswith("Dockerfile."):
        return "dockerfile"
    if basename.startswith("Makefile.") or basename.startswith("makefile."):
        return "makefile"

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
