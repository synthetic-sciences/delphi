"""Analysis service for deep repository understanding.

Provides comprehensive analysis of indexed repositories:
- Directory structure with annotations
- Entry points detection (main files, CLI, API)
- Dependency parsing (package.json, pyproject.toml, etc.)
- Architecture pattern detection
- Key file identification
- Codebase conventions detection
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import func

from synsc.config import get_config
from synsc.database.connection import get_session
from synsc.database.models import (
    Repository,
    RepositoryFile,
    CodeChunk,
)

logger = structlog.get_logger(__name__)


# ==============================================================================
# PATTERNS AND CONSTANTS
# ==============================================================================

# Entry point patterns by language
ENTRY_POINT_PATTERNS = {
    "python": [
        r"^main\.py$",
        r"^app\.py$",
        r"^cli\.py$",
        r"^__main__\.py$",
        r"^run\.py$",
        r"^server\.py$",
        r"^manage\.py$",  # Django
        r"^wsgi\.py$",
        r"^asgi\.py$",
    ],
    "javascript": [
        r"^index\.js$",
        r"^main\.js$",
        r"^app\.js$",
        r"^server\.js$",
        r"^cli\.js$",
    ],
    "typescript": [
        r"^index\.ts$",
        r"^main\.ts$",
        r"^app\.ts$",
        r"^server\.ts$",
        r"^cli\.ts$",
    ],
    "rust": [
        r"^main\.rs$",
        r"^lib\.rs$",
    ],
    "go": [
        r"^main\.go$",
        r"^cmd/",
    ],
    "ruby": [
        r"^main\.rb$",
        r"^app\.rb$",
        r"^config\.ru$",  # Rack
        r"^Rakefile$",
    ],
    "java": [
        r"^Main\.java$",
        r"^App\.java$",
        r"^Application\.java$",
    ],
    "kotlin": [
        r"^Main\.kt$",
        r"^App\.kt$",
        r"^Application\.kt$",
    ],
    "scala": [
        r"^Main\.scala$",
        r"^App\.scala$",
    ],
    "csharp": [
        r"^Program\.cs$",
        r"^Startup\.cs$",
    ],
    "php": [
        r"^index\.php$",
        r"^artisan$",  # Laravel
        r"^console$",
    ],
    "swift": [
        r"^main\.swift$",
        r"^App\.swift$",
        r"^AppDelegate\.swift$",
    ],
    "dart": [
        r"^main\.dart$",
        r"^app\.dart$",
    ],
    "elixir": [
        r"^mix\.exs$",
        r"^application\.ex$",
    ],
    "haskell": [
        r"^Main\.hs$",
        r"^app/Main\.hs$",
    ],
    "c": [
        r"^main\.c$",
    ],
    "cpp": [
        r"^main\.cpp$",
        r"^main\.cc$",
        r"^main\.cxx$",
    ],
    "zig": [
        r"^main\.zig$",
    ],
    "lua": [
        r"^main\.lua$",
        r"^init\.lua$",
    ],
    "perl": [
        r"^main\.pl$",
        r"^app\.pl$",
    ],
    "r": [
        r"^main\.R$",
        r"^app\.R$",
    ],
    "julia": [
        r"^main\.jl$",
    ],
    "clojure": [
        r"^core\.clj$",
    ],
}

# Config file patterns
CONFIG_FILE_PATTERNS = [
    # Python
    r"^pyproject\.toml$",
    r"^setup\.py$",
    r"^setup\.cfg$",
    r"^requirements\.txt$",
    r"^Pipfile$",
    r"^poetry\.lock$",
    r"^tox\.ini$",
    r"^pytest\.ini$",
    # JavaScript/Node
    r"^package\.json$",
    r"^package-lock\.json$",
    r"^yarn\.lock$",
    r"^pnpm-lock\.yaml$",
    r"^tsconfig\.json$",
    r"^\.eslintrc",
    r"^\.prettierrc",
    r"^vite\.config\.",
    r"^webpack\.config\.",
    r"^next\.config\.",
    r"^nuxt\.config\.",
    r"^rollup\.config\.",
    r"^babel\.config\.",
    r"^\.babelrc",
    r"^jest\.config\.",
    r"^vitest\.config\.",
    # Rust
    r"^Cargo\.toml$",
    r"^Cargo\.lock$",
    r"^rust-toolchain",
    # Go
    r"^go\.mod$",
    r"^go\.sum$",
    # Ruby
    r"^Gemfile$",
    r"^Gemfile\.lock$",
    r"^\.ruby-version$",
    r"^\.rubocop\.yml$",
    r"^Rakefile$",
    # Java/Kotlin
    r"^pom\.xml$",
    r"^build\.gradle$",
    r"^build\.gradle\.kts$",
    r"^settings\.gradle",
    r"^gradle\.properties$",
    # C#/.NET
    r"\.csproj$",
    r"\.sln$",
    r"^packages\.config$",
    r"^nuget\.config$",
    r"^\.editorconfig$",
    # PHP
    r"^composer\.json$",
    r"^composer\.lock$",
    r"^phpunit\.xml",
    r"^\.php-version$",
    # Swift
    r"^Package\.swift$",
    r"^\.swift-version$",
    r"^Podfile$",
    r"^Podfile\.lock$",
    # Dart/Flutter
    r"^pubspec\.yaml$",
    r"^pubspec\.lock$",
    r"^analysis_options\.yaml$",
    # Elixir
    r"^mix\.exs$",
    r"^mix\.lock$",
    # Haskell
    r"^package\.yaml$",
    r"^stack\.yaml$",
    r"\.cabal$",
    # Scala
    r"^build\.sbt$",
    r"^project/build\.properties$",
    # C/C++
    r"^CMakeLists\.txt$",
    r"^Makefile$",
    r"^vcpkg\.json$",
    r"^conanfile\.txt$",
    r"^conanfile\.py$",
    r"^meson\.build$",
    # Zig
    r"^build\.zig$",
    r"^build\.zig\.zon$",
    # Lua
    r"^rockspec$",
    # Perl
    r"^cpanfile$",
    r"^Makefile\.PL$",
    # R
    r"^DESCRIPTION$",
    r"^NAMESPACE$",
    # Julia
    r"^Project\.toml$",
    r"^Manifest\.toml$",
    # Clojure
    r"^project\.clj$",
    r"^deps\.edn$",
    # General
    r"^\.env",
    r"^\.gitignore$",
    r"^Dockerfile$",
    r"^docker-compose",
    r"^\.github/",
    r"^\.gitlab-ci\.yml$",
    r"^\.travis\.yml$",
    r"^\.circleci/",
    r"^Jenkinsfile$",
    r"^azure-pipelines\.yml$",
]

# Documentation patterns
DOC_PATTERNS = [
    r"^README",
    r"^CHANGELOG",
    r"^CONTRIBUTING",
    r"^LICENSE",
    r"^docs/",
    r"^documentation/",
]

# Test patterns
TEST_PATTERNS = [
    r"^tests?/",
    r"^__tests__/",
    r"^spec/",
    r"_test\.",
    r"\.test\.",
    r"_spec\.",
    r"\.spec\.",
]

# Architecture patterns
ARCHITECTURE_PATTERNS = {
    "clean_architecture": {
        "indicators": ["domain/", "application/", "infrastructure/", "interfaces/"],
        "description": "Clean Architecture - separates business logic from external concerns",
    },
    "hexagonal": {
        "indicators": ["adapters/", "ports/", "core/", "domain/"],
        "description": "Hexagonal Architecture (Ports & Adapters)",
    },
    "mvc": {
        "indicators": ["models/", "views/", "controllers/"],
        "description": "Model-View-Controller pattern",
    },
    "mvp": {
        "indicators": ["models/", "views/", "presenters/"],
        "description": "Model-View-Presenter pattern",
    },
    "layered": {
        "indicators": ["api/", "services/", "database/", "models/"],
        "description": "Layered Architecture - horizontal separation of concerns",
    },
    "modular": {
        "indicators": ["modules/", "features/", "packages/"],
        "description": "Modular Architecture - feature-based organization",
    },
    "flat": {
        "indicators": [],
        "description": "Flat structure - simple project layout",
    },
}

# Framework detection patterns
FRAMEWORK_PATTERNS = {
    # Python Frameworks
    "fastapi": {
        "files": ["main.py", "app.py"],
        "imports": ["fastapi", "from fastapi"],
        "framework": "FastAPI",
        "type": "Python Web Framework",
    },
    "django": {
        "files": ["manage.py", "wsgi.py", "asgi.py"],
        "imports": ["django"],
        "framework": "Django",
        "type": "Python Web Framework",
    },
    "flask": {
        "files": ["app.py", "wsgi.py"],
        "imports": ["flask", "from flask"],
        "framework": "Flask",
        "type": "Python Web Framework",
    },
    "click": {
        "files": [],
        "imports": ["click", "from click"],
        "framework": "Click",
        "type": "Python CLI Framework",
    },
    "typer": {
        "files": [],
        "imports": ["typer", "from typer"],
        "framework": "Typer",
        "type": "Python CLI Framework",
    },
    "pytorch": {
        "files": [],
        "imports": ["torch", "import torch"],
        "framework": "PyTorch",
        "type": "Python ML Framework",
    },
    "tensorflow": {
        "files": [],
        "imports": ["tensorflow", "import tensorflow"],
        "framework": "TensorFlow",
        "type": "Python ML Framework",
    },
    "pytest": {
        "files": ["pytest.ini", "conftest.py"],
        "imports": ["pytest", "import pytest"],
        "framework": "pytest",
        "type": "Python Testing Framework",
    },
    # JavaScript/TypeScript Frameworks
    "react": {
        "files": ["package.json"],
        "deps": ["react", "react-dom"],
        "framework": "React",
        "type": "JavaScript UI Library",
    },
    "nextjs": {
        "files": ["next.config.js", "next.config.mjs", "next.config.ts"],
        "deps": ["next"],
        "framework": "Next.js",
        "type": "React Framework",
    },
    "vue": {
        "files": ["package.json"],
        "deps": ["vue"],
        "framework": "Vue.js",
        "type": "JavaScript UI Framework",
    },
    "nuxt": {
        "files": ["nuxt.config.js", "nuxt.config.ts"],
        "deps": ["nuxt"],
        "framework": "Nuxt",
        "type": "Vue Framework",
    },
    "angular": {
        "files": ["angular.json"],
        "deps": ["@angular/core"],
        "framework": "Angular",
        "type": "TypeScript Framework",
    },
    "svelte": {
        "files": ["svelte.config.js"],
        "deps": ["svelte"],
        "framework": "Svelte",
        "type": "JavaScript UI Framework",
    },
    "express": {
        "files": ["package.json"],
        "deps": ["express"],
        "framework": "Express.js",
        "type": "Node.js Web Framework",
    },
    "nestjs": {
        "files": ["nest-cli.json"],
        "deps": ["@nestjs/core"],
        "framework": "NestJS",
        "type": "Node.js Framework",
    },
    "fastify": {
        "files": [],
        "deps": ["fastify"],
        "framework": "Fastify",
        "type": "Node.js Web Framework",
    },
    "jest": {
        "files": ["jest.config.js", "jest.config.ts"],
        "deps": ["jest"],
        "framework": "Jest",
        "type": "JavaScript Testing Framework",
    },
    "vitest": {
        "files": ["vitest.config.js", "vitest.config.ts"],
        "deps": ["vitest"],
        "framework": "Vitest",
        "type": "JavaScript Testing Framework",
    },
    "electron": {
        "files": [],
        "deps": ["electron"],
        "framework": "Electron",
        "type": "Desktop App Framework",
    },
    "tauri": {
        "files": ["tauri.conf.json"],
        "deps": ["@tauri-apps/api"],
        "framework": "Tauri",
        "type": "Desktop App Framework",
    },
    # Ruby Frameworks
    "rails": {
        "files": ["config.ru", "Gemfile"],
        "gems": ["rails"],
        "framework": "Ruby on Rails",
        "type": "Ruby Web Framework",
    },
    "sinatra": {
        "files": ["Gemfile"],
        "gems": ["sinatra"],
        "framework": "Sinatra",
        "type": "Ruby Web Framework",
    },
    "rspec": {
        "files": ["spec/spec_helper.rb", ".rspec"],
        "gems": ["rspec"],
        "framework": "RSpec",
        "type": "Ruby Testing Framework",
    },
    # Java/Kotlin Frameworks
    "spring": {
        "files": ["pom.xml", "build.gradle"],
        "java_deps": ["spring-boot", "spring-core", "org.springframework"],
        "framework": "Spring",
        "type": "Java Web Framework",
    },
    "quarkus": {
        "files": [],
        "java_deps": ["quarkus"],
        "framework": "Quarkus",
        "type": "Java Web Framework",
    },
    "micronaut": {
        "files": [],
        "java_deps": ["micronaut"],
        "framework": "Micronaut",
        "type": "Java Web Framework",
    },
    "junit": {
        "files": [],
        "java_deps": ["junit"],
        "framework": "JUnit",
        "type": "Java Testing Framework",
    },
    "android": {
        "files": ["AndroidManifest.xml", "build.gradle"],
        "java_deps": ["androidx", "android"],
        "framework": "Android",
        "type": "Mobile Framework",
    },
    # PHP Frameworks
    "laravel": {
        "files": ["artisan"],
        "composer_deps": ["laravel/framework"],
        "framework": "Laravel",
        "type": "PHP Web Framework",
    },
    "symfony": {
        "files": ["symfony.lock"],
        "composer_deps": ["symfony/framework-bundle"],
        "framework": "Symfony",
        "type": "PHP Web Framework",
    },
    "wordpress": {
        "files": ["wp-config.php", "wp-content/"],
        "framework": "WordPress",
        "type": "PHP CMS",
    },
    "phpunit": {
        "files": ["phpunit.xml", "phpunit.xml.dist"],
        "composer_deps": ["phpunit/phpunit"],
        "framework": "PHPUnit",
        "type": "PHP Testing Framework",
    },
    # C#/.NET Frameworks
    "aspnet": {
        "files": ["Startup.cs", "Program.cs"],
        "nuget_deps": ["Microsoft.AspNetCore"],
        "framework": "ASP.NET Core",
        "type": ".NET Web Framework",
    },
    "blazor": {
        "files": [],
        "nuget_deps": ["Microsoft.AspNetCore.Components"],
        "framework": "Blazor",
        "type": ".NET Web Framework",
    },
    "maui": {
        "files": [],
        "nuget_deps": ["Microsoft.Maui"],
        "framework": ".NET MAUI",
        "type": ".NET Mobile Framework",
    },
    "xunit": {
        "files": [],
        "nuget_deps": ["xunit"],
        "framework": "xUnit",
        "type": ".NET Testing Framework",
    },
    "nunit": {
        "files": [],
        "nuget_deps": ["NUnit"],
        "framework": "NUnit",
        "type": ".NET Testing Framework",
    },
    # Rust Frameworks
    "actix": {
        "files": [],
        "cargo_deps": ["actix-web"],
        "framework": "Actix Web",
        "type": "Rust Web Framework",
    },
    "axum": {
        "files": [],
        "cargo_deps": ["axum"],
        "framework": "Axum",
        "type": "Rust Web Framework",
    },
    "rocket": {
        "files": [],
        "cargo_deps": ["rocket"],
        "framework": "Rocket",
        "type": "Rust Web Framework",
    },
    "tokio": {
        "files": [],
        "cargo_deps": ["tokio"],
        "framework": "Tokio",
        "type": "Rust Async Runtime",
    },
    # Go Frameworks
    "gin": {
        "files": [],
        "go_deps": ["github.com/gin-gonic/gin"],
        "framework": "Gin",
        "type": "Go Web Framework",
    },
    "echo": {
        "files": [],
        "go_deps": ["github.com/labstack/echo"],
        "framework": "Echo",
        "type": "Go Web Framework",
    },
    "fiber": {
        "files": [],
        "go_deps": ["github.com/gofiber/fiber"],
        "framework": "Fiber",
        "type": "Go Web Framework",
    },
    # Swift/iOS Frameworks
    "swiftui": {
        "files": [],
        "swift_imports": ["SwiftUI"],
        "framework": "SwiftUI",
        "type": "iOS UI Framework",
    },
    "vapor": {
        "files": ["Package.swift"],
        "swift_deps": ["vapor"],
        "framework": "Vapor",
        "type": "Swift Web Framework",
    },
    # Flutter/Dart
    "flutter": {
        "files": ["pubspec.yaml"],
        "dart_deps": ["flutter"],
        "framework": "Flutter",
        "type": "Cross-platform Mobile Framework",
    },
    # Elixir Frameworks
    "phoenix": {
        "files": ["mix.exs"],
        "elixir_deps": ["phoenix"],
        "framework": "Phoenix",
        "type": "Elixir Web Framework",
    },
}


class AnalysisService:
    """Service for comprehensive repository analysis.
    
    Note: Some features require local file access and may have limited 
    functionality in cloud-only mode (e.g., dependency parsing, framework detection).
    These features will still work based on database metadata and file patterns.
    """

    def __init__(self, user_id: str | None = None):
        """Initialize the analysis service.
        
        Args:
            user_id: User ID for multi-tenant isolation.
        """
        self.config = get_config()
        self.user_id = user_id

    def analyze_repository(self, repo_id: str, user_id: str | None = None) -> dict:
        """Perform comprehensive analysis of a repository.
        
        Args:
            repo_id: Repository identifier
            user_id: User ID for authorization (required in multi-tenant mode)
            
        Returns:
            Comprehensive analysis including structure, dependencies,
            entry points, architecture, and conventions.
        """
        effective_user_id = user_id or self.user_id
        
        with get_session() as session:
            # Get repository
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()
            
            if not repo:
                return {
                    "success": False,
                    "error": "Repository not found",
                    "message": f"Repository with ID '{repo_id}' not found",
                }
            
            # Access control check
            if not repo.can_user_access(effective_user_id):
                return {
                    "success": False,
                    "error": "Access denied",
                    "message": "You don't have access to this private repository",
                }
            
            # Get all files
            files = session.query(RepositoryFile).filter(
                RepositoryFile.repo_id == repo_id
            ).all()
            
            file_paths = [f.file_path for f in files]
            
            # Check if running in cloud mode (no local path)
            is_cloud_mode = not repo.local_path or not Path(repo.local_path).exists()
            
            # Build analysis
            analysis = {
                "success": True,
                "repo_id": repo_id,
                "repo_name": f"{repo.owner}/{repo.name}",
                "branch": repo.branch,
                "mode": "cloud" if is_cloud_mode else "local",
            }
            
            # Get directory structure (works in both modes - uses database)
            analysis["structure"] = self._analyze_structure(file_paths)
            
            # Detect entry points (partially works - file patterns from DB)
            analysis["entry_points"] = self._detect_entry_points(repo, files)
            
            # Parse dependencies (limited in cloud mode - requires local files)
            analysis["dependencies"] = self._parse_dependencies(repo)
            if is_cloud_mode and not analysis["dependencies"]["manifest_files"]:
                analysis["dependencies"]["_note"] = "Limited in cloud mode - manifest files not accessible"
            
            # Detect frameworks (limited in cloud mode)
            analysis["frameworks"] = self._detect_frameworks(repo, files)
            
            # Detect architecture (works in both modes - uses file paths)
            analysis["architecture"] = self._detect_architecture(file_paths)
            
            # Find key files (works in both modes - uses database)
            analysis["key_files"] = self._find_key_files(files)
            
            # Analyze conventions (limited in cloud mode)
            analysis["conventions"] = self._analyze_conventions(repo, files)
            if is_cloud_mode:
                analysis["conventions"]["_note"] = "Limited in cloud mode - linter configs not accessible"
            
            # Generate summary
            analysis["summary"] = self._generate_summary(analysis)
            
            return analysis

    def get_directory_structure(
        self,
        repo_id: str,
        max_depth: int = 4,
        annotate: bool = True,
        user_id: str | None = None,
    ) -> dict:
        """Get annotated directory structure of a repository.
        
        Args:
            repo_id: Repository identifier
            max_depth: Maximum directory depth to show
            annotate: Whether to add annotations for directories
            user_id: User ID for authorization (required in multi-tenant mode)
            
        Returns:
            Directory tree with optional annotations.
        """
        effective_user_id = user_id or self.user_id
        
        with get_session() as session:
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()
            
            if not repo:
                return {
                    "success": False,
                    "error": "Repository not found",
                }
            
            # Access control check
            if not repo.can_user_access(effective_user_id):
                return {
                    "success": False,
                    "error": "Access denied",
                    "message": "You don't have access to this private repository",
                }
            
            files = session.query(RepositoryFile).filter(
                RepositoryFile.repo_id == repo_id
            ).all()
            
            file_paths = [f.file_path for f in files]
            
            # Build tree
            tree = self._build_directory_tree(file_paths, max_depth)
            
            # Add annotations if requested
            if annotate:
                tree = self._annotate_tree(tree)
            
            return {
                "success": True,
                "repo_id": repo_id,
                "repo_name": f"{repo.owner}/{repo.name}",
                "tree": tree,
                "total_files": len(files),
                "total_directories": self._count_directories(tree),
            }

    def _analyze_structure(self, file_paths: list[str]) -> dict:
        """Analyze the directory structure."""
        # Count files per top-level directory
        top_level_counts: Counter = Counter()
        root_files: list[str] = []
        depths: list[int] = []
        
        for path in file_paths:
            parts = Path(path).parts
            depths.append(len(parts))
            if len(parts) == 1:
                # Root-level file
                root_files.append(parts[0])
            elif len(parts) > 1:
                # File in a directory
                top_level_counts[parts[0]] += 1
        
        # Identify directory purposes (only actual directories, not files)
        top_level_dirs = {}
        for dir_name in top_level_counts:
            purpose = self._identify_directory_purpose(dir_name)
            top_level_dirs[dir_name] = {
                "files_count": top_level_counts[dir_name],
                "purpose": purpose,
            }
        
        return {
            "top_level_directories": top_level_dirs,
            "root_files": root_files,
            "root_files_count": len(root_files),
            "total_directories": len(set(
                str(Path(p).parent) for p in file_paths if len(Path(p).parts) > 1
            )),
            "max_depth": max(depths) if depths else 0,
            "avg_depth": sum(depths) / len(depths) if depths else 0,
        }

    def _identify_directory_purpose(self, dir_name: str) -> str:
        """Identify the purpose of a directory by its name."""
        name_lower = dir_name.lower()
        
        purpose_map = {
            "src": "Source code",
            "source": "Source code",
            "lib": "Library code",
            "app": "Application code",
            "pkg": "Package code",
            "tests": "Test files",
            "test": "Test files",
            "__tests__": "Test files",
            "spec": "Test specifications",
            "docs": "Documentation",
            "documentation": "Documentation",
            "examples": "Example code",
            "samples": "Sample code",
            "scripts": "Utility scripts",
            "bin": "Executable scripts",
            "tools": "Development tools",
            "utils": "Utility functions",
            "helpers": "Helper functions",
            "config": "Configuration files",
            "configs": "Configuration files",
            "api": "API layer",
            "routes": "Route handlers",
            "controllers": "Controller layer",
            "models": "Data models",
            "views": "View layer",
            "templates": "Template files",
            "static": "Static assets",
            "assets": "Static assets",
            "public": "Public files",
            "dist": "Build output",
            "build": "Build output",
            "out": "Build output",
            ".github": "GitHub workflows/config",
            "ci": "CI/CD configuration",
            "docker": "Docker configuration",
            "deploy": "Deployment configuration",
            "services": "Service layer",
            "core": "Core business logic",
            "domain": "Domain layer",
            "infrastructure": "Infrastructure code",
            "database": "Database layer",
            "db": "Database layer",
            "migrations": "Database migrations",
            "components": "UI components",
            "pages": "Page components",
            "features": "Feature modules",
            "modules": "Application modules",
            "hooks": "React hooks",
            "store": "State management",
            "types": "Type definitions",
            "interfaces": "Interface definitions",
            "middleware": "Middleware",
            "plugins": "Plugins",
            "extensions": "Extensions",
            "vendor": "Third-party code",
            "node_modules": "Node.js dependencies",
            "__pycache__": "Python bytecode cache",
            ".git": "Git repository",
        }
        
        return purpose_map.get(name_lower, "Project files")

    def _detect_entry_points(
        self,
        repo: Repository,
        files: list[RepositoryFile],
    ) -> dict:
        """Detect entry points in the repository."""
        entry_points = {
            "main_files": [],
            "cli_entry_points": [],
            "api_entry_points": [],
            "test_entry_points": [],
        }
        
        for file in files:
            file_name = Path(file.file_path).name
            
            # Check language-specific entry points
            if file.language in ENTRY_POINT_PATTERNS:
                for pattern in ENTRY_POINT_PATTERNS[file.language]:
                    if re.match(pattern, file_name):
                        entry_points["main_files"].append({
                            "path": file.file_path,
                            "language": file.language,
                            "type": "main",
                        })
                        break
            
            # Check for CLI patterns (only code files, not docs)
            if "cli" in file_name.lower() and file.language and file.language not in ("markdown", "text"):
                entry_points["cli_entry_points"].append({
                    "path": file.file_path,
                    "language": file.language,
                })
            
            # Check for API patterns
            if any(p in file.file_path.lower() for p in ["api/", "routes/", "endpoints/"]):
                entry_points["api_entry_points"].append({
                    "path": file.file_path,
                    "language": file.language,
                })
        
        # Check pyproject.toml for Python entry points
        if repo.local_path:
            pyproject_path = Path(repo.local_path) / "pyproject.toml"
            if pyproject_path.exists():
                try:
                    content = pyproject_path.read_text()
                    # Parse scripts section
                    if "[project.scripts]" in content:
                        scripts = self._parse_toml_section(content, "[project.scripts]")
                        for name, value in scripts.items():
                            entry_points["cli_entry_points"].append({
                                "name": name,
                                "target": value,
                                "type": "pyproject.toml",
                            })
                except Exception:
                    pass
            
            # Check package.json for Node entry points
            package_json_path = Path(repo.local_path) / "package.json"
            if package_json_path.exists():
                try:
                    pkg = json.loads(package_json_path.read_text())
                    if "main" in pkg:
                        entry_points["main_files"].append({
                            "path": pkg["main"],
                            "type": "package.json main",
                        })
                    if "bin" in pkg:
                        if isinstance(pkg["bin"], str):
                            entry_points["cli_entry_points"].append({
                                "name": pkg.get("name", "cli"),
                                "target": pkg["bin"],
                                "type": "package.json bin",
                            })
                        elif isinstance(pkg["bin"], dict):
                            for name, target in pkg["bin"].items():
                                entry_points["cli_entry_points"].append({
                                    "name": name,
                                    "target": target,
                                    "type": "package.json bin",
                                })
                except Exception:
                    pass
        
        return entry_points

    def _parse_dependencies(self, repo: Repository) -> dict:
        """Parse dependencies from manifest files."""
        dependencies = {
            "production": [],
            "development": [],
            "manifest_files": [],
        }
        
        if not repo.local_path:
            return dependencies
        
        local_path = Path(repo.local_path)
        
        # Parse pyproject.toml
        pyproject_path = local_path / "pyproject.toml"
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text()
                dependencies["manifest_files"].append("pyproject.toml")
                
                # Parse dependencies section
                if "[project.dependencies]" in content or "dependencies = [" in content:
                    deps = self._parse_python_deps(content)
                    dependencies["production"].extend(deps["production"])
                    dependencies["development"].extend(deps.get("development", []))
            except Exception as e:
                logger.warning("Failed to parse pyproject.toml", error=str(e))
        
        # Parse requirements.txt
        req_path = local_path / "requirements.txt"
        if req_path.exists():
            try:
                content = req_path.read_text()
                dependencies["manifest_files"].append("requirements.txt")
                for line in content.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        # Extract package name
                        match = re.match(r'^([a-zA-Z0-9_-]+)', line)
                        if match:
                            dependencies["production"].append({
                                "name": match.group(1),
                                "spec": line,
                            })
            except Exception:
                pass
        
        # Parse package.json
        pkg_path = local_path / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                dependencies["manifest_files"].append("package.json")
                
                for name, version in pkg.get("dependencies", {}).items():
                    dependencies["production"].append({
                        "name": name,
                        "version": version,
                    })
                
                for name, version in pkg.get("devDependencies", {}).items():
                    dependencies["development"].append({
                        "name": name,
                        "version": version,
                    })
            except Exception:
                pass
        
        # Parse Cargo.toml
        cargo_path = local_path / "Cargo.toml"
        if cargo_path.exists():
            try:
                content = cargo_path.read_text()
                dependencies["manifest_files"].append("Cargo.toml")
                
                if "[dependencies]" in content:
                    deps_section = self._parse_toml_section(content, "[dependencies]")
                    for name, spec in deps_section.items():
                        dependencies["production"].append({
                            "name": name,
                            "spec": str(spec),
                        })
                
                if "[dev-dependencies]" in content:
                    dev_deps = self._parse_toml_section(content, "[dev-dependencies]")
                    for name, spec in dev_deps.items():
                        dependencies["development"].append({
                            "name": name,
                            "spec": str(spec),
                        })
            except Exception:
                pass
        
        # Parse go.mod
        go_mod_path = local_path / "go.mod"
        if go_mod_path.exists():
            try:
                content = go_mod_path.read_text()
                dependencies["manifest_files"].append("go.mod")
                
                for line in content.split("\n"):
                    if line.strip().startswith("require"):
                        continue
                    match = re.match(r'\s*([^\s]+)\s+v?([^\s]+)', line)
                    if match:
                        dependencies["production"].append({
                            "name": match.group(1),
                            "version": match.group(2),
                        })
            except Exception:
                pass
        
        # Parse Gemfile (Ruby)
        gemfile_path = local_path / "Gemfile"
        if gemfile_path.exists():
            try:
                content = gemfile_path.read_text()
                dependencies["manifest_files"].append("Gemfile")
                self._parse_gemfile(content, dependencies)
            except Exception:
                pass
        
        # Parse composer.json (PHP)
        composer_path = local_path / "composer.json"
        if composer_path.exists():
            try:
                composer = json.loads(composer_path.read_text())
                dependencies["manifest_files"].append("composer.json")
                
                for name, version in composer.get("require", {}).items():
                    if not name.startswith("php") and not name.startswith("ext-"):
                        dependencies["production"].append({
                            "name": name,
                            "version": version,
                        })
                
                for name, version in composer.get("require-dev", {}).items():
                    dependencies["development"].append({
                        "name": name,
                        "version": version,
                    })
            except Exception:
                pass
        
        # Parse pom.xml (Java/Maven)
        pom_path = local_path / "pom.xml"
        if pom_path.exists():
            try:
                content = pom_path.read_text()
                dependencies["manifest_files"].append("pom.xml")
                self._parse_pom_xml(content, dependencies)
            except Exception:
                pass
        
        # Parse build.gradle (Java/Kotlin/Gradle)
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = local_path / gradle_file
            if gradle_path.exists():
                try:
                    content = gradle_path.read_text()
                    dependencies["manifest_files"].append(gradle_file)
                    self._parse_gradle(content, dependencies)
                except Exception:
                    pass
                break
        
        # Parse .csproj files (C#/.NET)
        csproj_files = list(local_path.glob("*.csproj"))
        for csproj_path in csproj_files[:1]:  # Parse first one found
            try:
                content = csproj_path.read_text()
                dependencies["manifest_files"].append(csproj_path.name)
                self._parse_csproj(content, dependencies)
            except Exception:
                pass
        
        # Parse Package.swift (Swift)
        swift_path = local_path / "Package.swift"
        if swift_path.exists():
            try:
                content = swift_path.read_text()
                dependencies["manifest_files"].append("Package.swift")
                self._parse_swift_package(content, dependencies)
            except Exception:
                pass
        
        # Parse pubspec.yaml (Dart/Flutter)
        pubspec_path = local_path / "pubspec.yaml"
        if pubspec_path.exists():
            try:
                content = pubspec_path.read_text()
                dependencies["manifest_files"].append("pubspec.yaml")
                self._parse_pubspec(content, dependencies)
            except Exception:
                pass
        
        # Parse mix.exs (Elixir)
        mix_path = local_path / "mix.exs"
        if mix_path.exists():
            try:
                content = mix_path.read_text()
                dependencies["manifest_files"].append("mix.exs")
                self._parse_mix_exs(content, dependencies)
            except Exception:
                pass
        
        # Parse build.sbt (Scala)
        sbt_path = local_path / "build.sbt"
        if sbt_path.exists():
            try:
                content = sbt_path.read_text()
                dependencies["manifest_files"].append("build.sbt")
                self._parse_sbt(content, dependencies)
            except Exception:
                pass
        
        # Parse deps.edn or project.clj (Clojure)
        deps_edn_path = local_path / "deps.edn"
        if deps_edn_path.exists():
            try:
                content = deps_edn_path.read_text()
                dependencies["manifest_files"].append("deps.edn")
                self._parse_deps_edn(content, dependencies)
            except Exception:
                pass
        
        project_clj_path = local_path / "project.clj"
        if project_clj_path.exists():
            try:
                content = project_clj_path.read_text()
                dependencies["manifest_files"].append("project.clj")
                self._parse_project_clj(content, dependencies)
            except Exception:
                pass
        
        # Parse Project.toml (Julia)
        julia_path = local_path / "Project.toml"
        if julia_path.exists():
            try:
                content = julia_path.read_text()
                dependencies["manifest_files"].append("Project.toml")
                
                if "[deps]" in content:
                    deps_section = self._parse_toml_section(content, "[deps]")
                    for name, uuid in deps_section.items():
                        dependencies["production"].append({
                            "name": name,
                            "uuid": uuid,
                        })
            except Exception:
                pass
        
        # Parse stack.yaml or package.yaml (Haskell)
        for haskell_file in ["package.yaml", "stack.yaml"]:
            haskell_path = local_path / haskell_file
            if haskell_path.exists():
                try:
                    content = haskell_path.read_text()
                    dependencies["manifest_files"].append(haskell_file)
                    self._parse_haskell_yaml(content, dependencies)
                except Exception:
                    pass
                break
        
        # Deduplicate
        seen = set()
        unique_prod = []
        for dep in dependencies["production"]:
            if dep["name"] not in seen:
                seen.add(dep["name"])
                unique_prod.append(dep)
        dependencies["production"] = unique_prod
        
        seen = set()
        unique_dev = []
        for dep in dependencies["development"]:
            if dep["name"] not in seen:
                seen.add(dep["name"])
                unique_dev.append(dep)
        dependencies["development"] = unique_dev
        
        return dependencies

    def _parse_python_deps(self, content: str) -> dict:
        """Parse Python dependencies from pyproject.toml content."""
        deps = {"production": [], "development": []}
        
        # Simple regex-based parsing for dependencies array
        # This handles the common format: dependencies = ["pkg1", "pkg2>=1.0"]
        dep_match = re.search(r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if dep_match:
            dep_str = dep_match.group(1)
            for item in re.findall(r'"([^"]+)"', dep_str):
                # Extract package name
                match = re.match(r'^([a-zA-Z0-9_-]+)', item)
                if match:
                    deps["production"].append({
                        "name": match.group(1),
                        "spec": item,
                    })
        
        # Optional dependencies
        opt_match = re.search(r'\[project\.optional-dependencies\](.*?)(?=\[|$)', content, re.DOTALL)
        if opt_match:
            opt_str = opt_match.group(1)
            # Find dev dependencies
            dev_match = re.search(r'dev\s*=\s*\[(.*?)\]', opt_str, re.DOTALL)
            if dev_match:
                for item in re.findall(r'"([^"]+)"', dev_match.group(1)):
                    match = re.match(r'^([a-zA-Z0-9_-]+)', item)
                    if match:
                        deps["development"].append({
                            "name": match.group(1),
                            "spec": item,
                        })
        
        return deps

    def _parse_toml_section(self, content: str, section: str) -> dict:
        """Parse a TOML section into a dictionary (simple parser)."""
        result = {}
        
        # Find section start
        section_start = content.find(section)
        if section_start == -1:
            return result
        
        # Find section end (next section or EOF)
        section_content = content[section_start + len(section):]
        next_section = re.search(r'\n\[', section_content)
        if next_section:
            section_content = section_content[:next_section.start()]
        
        # Parse key-value pairs
        for line in section_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            match = re.match(r'([a-zA-Z0-9_-]+)\s*=\s*(.+)', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip().strip('"\'')
                result[key] = value
        
        return result

    def _parse_gemfile(self, content: str, dependencies: dict) -> None:
        """Parse Ruby Gemfile."""
        # Match: gem 'name', 'version' or gem "name", "version"
        gem_pattern = r"gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?"
        
        in_dev_group = False
        for line in content.split("\n"):
            line = line.strip()
            
            # Track groups
            if "group :development" in line or "group :test" in line:
                in_dev_group = True
            elif line.startswith("end"):
                in_dev_group = False
            
            match = re.match(gem_pattern, line)
            if match:
                name = match.group(1)
                version = match.group(2) or "*"
                
                dep = {"name": name, "version": version}
                if in_dev_group:
                    dependencies["development"].append(dep)
                else:
                    dependencies["production"].append(dep)

    def _parse_pom_xml(self, content: str, dependencies: dict) -> None:
        """Parse Maven pom.xml."""
        # Simple regex-based parsing for dependencies
        dep_pattern = r'<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>(?:\s*<version>([^<]+)</version>)?(?:\s*<scope>([^<]+)</scope>)?'
        
        for match in re.finditer(dep_pattern, content, re.DOTALL):
            group_id = match.group(1).strip()
            artifact_id = match.group(2).strip()
            version = match.group(3).strip() if match.group(3) else "*"
            scope = match.group(4).strip() if match.group(4) else "compile"
            
            dep = {
                "name": f"{group_id}:{artifact_id}",
                "version": version,
            }
            
            if scope in ("test", "provided"):
                dependencies["development"].append(dep)
            else:
                dependencies["production"].append(dep)

    def _parse_gradle(self, content: str, dependencies: dict) -> None:
        """Parse Gradle build file (build.gradle or build.gradle.kts)."""
        # Match: implementation 'group:artifact:version'
        # Or: testImplementation "group:artifact:version"
        patterns = [
            r"implementation\s*['\"]([^'\"]+)['\"]",
            r"api\s*['\"]([^'\"]+)['\"]",
            r"compileOnly\s*['\"]([^'\"]+)['\"]",
            r"runtimeOnly\s*['\"]([^'\"]+)['\"]",
        ]
        dev_patterns = [
            r"testImplementation\s*['\"]([^'\"]+)['\"]",
            r"testCompileOnly\s*['\"]([^'\"]+)['\"]",
            r"androidTestImplementation\s*['\"]([^'\"]+)['\"]",
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                dep_str = match.group(1)
                parts = dep_str.split(":")
                if len(parts) >= 2:
                    dependencies["production"].append({
                        "name": f"{parts[0]}:{parts[1]}",
                        "version": parts[2] if len(parts) > 2 else "*",
                    })
        
        for pattern in dev_patterns:
            for match in re.finditer(pattern, content):
                dep_str = match.group(1)
                parts = dep_str.split(":")
                if len(parts) >= 2:
                    dependencies["development"].append({
                        "name": f"{parts[0]}:{parts[1]}",
                        "version": parts[2] if len(parts) > 2 else "*",
                    })

    def _parse_csproj(self, content: str, dependencies: dict) -> None:
        """Parse C# .csproj file."""
        # Match: <PackageReference Include="Name" Version="1.0" />
        pattern = r'<PackageReference\s+Include="([^"]+)"(?:\s+Version="([^"]+)")?'
        
        for match in re.finditer(pattern, content):
            name = match.group(1)
            version = match.group(2) or "*"
            
            dependencies["production"].append({
                "name": name,
                "version": version,
            })

    def _parse_swift_package(self, content: str, dependencies: dict) -> None:
        """Parse Swift Package.swift."""
        # Match: .package(url: "https://github.com/...", from: "1.0.0")
        url_pattern = r'\.package\s*\(\s*url:\s*"([^"]+)"'
        
        for match in re.finditer(url_pattern, content):
            url = match.group(1)
            # Extract package name from URL
            name = url.rstrip("/").split("/")[-1].replace(".git", "")
            dependencies["production"].append({
                "name": name,
                "url": url,
            })

    def _parse_pubspec(self, content: str, dependencies: dict) -> None:
        """Parse Dart/Flutter pubspec.yaml."""
        # Simple YAML parsing for dependencies section
        in_deps = False
        in_dev_deps = False
        indent_level = 0
        
        for line in content.split("\n"):
            stripped = line.strip()
            
            if stripped.startswith("dependencies:"):
                in_deps = True
                in_dev_deps = False
                continue
            elif stripped.startswith("dev_dependencies:"):
                in_deps = False
                in_dev_deps = True
                continue
            elif stripped and not stripped.startswith("#") and not line.startswith(" "):
                in_deps = False
                in_dev_deps = False
                continue
            
            if (in_deps or in_dev_deps) and stripped and not stripped.startswith("#"):
                # Parse: name: version or name: ^version
                match = re.match(r'^([a-zA-Z0-9_]+):\s*(.+)?$', stripped)
                if match:
                    name = match.group(1)
                    version = match.group(2) or "*"
                    if version.startswith("^") or version.startswith(">="):
                        version = version
                    
                    dep = {"name": name, "version": version.strip()}
                    if in_dev_deps:
                        dependencies["development"].append(dep)
                    else:
                        dependencies["production"].append(dep)

    def _parse_mix_exs(self, content: str, dependencies: dict) -> None:
        """Parse Elixir mix.exs."""
        # Match: {:name, "~> 1.0"}
        dep_pattern = r'\{:([a-zA-Z0-9_]+),\s*"([^"]+)"\}'
        
        for match in re.finditer(dep_pattern, content):
            name = match.group(1)
            version = match.group(2)
            
            dependencies["production"].append({
                "name": name,
                "version": version,
            })

    def _parse_sbt(self, content: str, dependencies: dict) -> None:
        """Parse Scala build.sbt."""
        # Match: "org" %% "artifact" % "version"
        # Or: "org" % "artifact" % "version"
        dep_pattern = r'"([^"]+)"\s*%%?\s*"([^"]+)"\s*%\s*"([^"]+)"'
        
        for match in re.finditer(dep_pattern, content):
            org = match.group(1)
            artifact = match.group(2)
            version = match.group(3)
            
            dependencies["production"].append({
                "name": f"{org}:{artifact}",
                "version": version,
            })

    def _parse_deps_edn(self, content: str, dependencies: dict) -> None:
        """Parse Clojure deps.edn."""
        # Match: org/artifact {:mvn/version "1.0"}
        dep_pattern = r'([a-zA-Z0-9_./-]+)\s*\{:mvn/version\s*"([^"]+)"\}'
        
        for match in re.finditer(dep_pattern, content):
            name = match.group(1)
            version = match.group(2)
            
            dependencies["production"].append({
                "name": name,
                "version": version,
            })

    def _parse_project_clj(self, content: str, dependencies: dict) -> None:
        """Parse Clojure project.clj."""
        # Match: [org/artifact "version"]
        dep_pattern = r'\[([a-zA-Z0-9_./-]+)\s+"([^"]+)"\]'
        
        for match in re.finditer(dep_pattern, content):
            name = match.group(1)
            version = match.group(2)
            
            dependencies["production"].append({
                "name": name,
                "version": version,
            })

    def _parse_haskell_yaml(self, content: str, dependencies: dict) -> None:
        """Parse Haskell package.yaml or stack.yaml."""
        # Look for dependencies section
        in_deps = False
        
        for line in content.split("\n"):
            stripped = line.strip()
            
            if stripped.startswith("dependencies:"):
                in_deps = True
                continue
            elif stripped and not line.startswith(" ") and not line.startswith("-"):
                in_deps = False
                continue
            
            if in_deps and stripped.startswith("-"):
                # Parse: - name or - name >= version
                dep_str = stripped[1:].strip()
                match = re.match(r'^([a-zA-Z0-9_-]+)', dep_str)
                if match:
                    dependencies["production"].append({
                        "name": match.group(1),
                        "spec": dep_str,
                    })

    def _detect_frameworks(
        self,
        repo: Repository,
        files: list[RepositoryFile],
    ) -> list[dict]:
        """Detect frameworks and libraries used in the repository."""
        detected = []
        file_names = {Path(f.file_path).name for f in files}
        file_paths = {f.file_path for f in files}
        
        # Cache parsed dependency files
        parsed_deps = self._get_all_parsed_deps(repo)
        
        # Check file-based detection
        for framework_id, patterns in FRAMEWORK_PATTERNS.items():
            score = 0
            
            # Check for specific files (exact filename match, not substring)
            for file_pattern in patterns.get("files", []):
                if file_pattern in file_names or any(fp.endswith("/" + file_pattern) and fp.count("/") <= 1 for fp in file_paths):
                    score += 1
            
            # Check package.json dependencies (JavaScript/TypeScript)
            if "deps" in patterns and "npm" in parsed_deps:
                for dep in patterns["deps"]:
                    if dep in parsed_deps["npm"]:
                        score += 2
            
            # Check Gemfile dependencies (Ruby)
            if "gems" in patterns and "gems" in parsed_deps:
                for gem in patterns["gems"]:
                    if gem in parsed_deps["gems"]:
                        score += 2
            
            # Check pom.xml/build.gradle dependencies (Java/Kotlin)
            if "java_deps" in patterns and "java" in parsed_deps:
                for dep in patterns["java_deps"]:
                    if any(dep.lower() in d.lower() for d in parsed_deps["java"]):
                        score += 2
            
            # Check composer.json dependencies (PHP)
            if "composer_deps" in patterns and "composer" in parsed_deps:
                for dep in patterns["composer_deps"]:
                    if dep in parsed_deps["composer"]:
                        score += 2
            
            # Check .csproj dependencies (C#/.NET)
            if "nuget_deps" in patterns and "nuget" in parsed_deps:
                for dep in patterns["nuget_deps"]:
                    if any(dep.lower() in d.lower() for d in parsed_deps["nuget"]):
                        score += 2
            
            # Check Cargo.toml dependencies (Rust)
            if "cargo_deps" in patterns and "cargo" in parsed_deps:
                for dep in patterns["cargo_deps"]:
                    if dep in parsed_deps["cargo"]:
                        score += 2
            
            # Check go.mod dependencies (Go)
            if "go_deps" in patterns and "go" in parsed_deps:
                for dep in patterns["go_deps"]:
                    if any(dep in d for d in parsed_deps["go"]):
                        score += 2
            
            # Check Package.swift dependencies (Swift)
            if "swift_deps" in patterns and "swift" in parsed_deps:
                for dep in patterns["swift_deps"]:
                    if any(dep.lower() in d.lower() for d in parsed_deps["swift"]):
                        score += 2
            
            # Check pubspec.yaml dependencies (Dart/Flutter)
            if "dart_deps" in patterns and "dart" in parsed_deps:
                for dep in patterns["dart_deps"]:
                    if dep in parsed_deps["dart"]:
                        score += 2
            
            # Check mix.exs dependencies (Elixir)
            if "elixir_deps" in patterns and "elixir" in parsed_deps:
                for dep in patterns["elixir_deps"]:
                    if dep in parsed_deps["elixir"]:
                        score += 2
            
            # Check imports in Python files
            if "imports" in patterns and repo.local_path:
                for file in files[:50]:  # Limit to first 50 files for performance
                    if file.language == "python":
                        try:
                            file_path = Path(repo.local_path) / file.file_path
                            if file_path.exists():
                                content = file_path.read_text(errors="ignore")
                                for import_pattern in patterns["imports"]:
                                    if import_pattern in content:
                                        score += 1
                                        break
                        except Exception:
                            pass
            
            # Check imports in Swift files
            if "swift_imports" in patterns and repo.local_path:
                for file in files[:50]:
                    if file.language == "swift":
                        try:
                            file_path = Path(repo.local_path) / file.file_path
                            if file_path.exists():
                                content = file_path.read_text(errors="ignore")
                                for import_pattern in patterns["swift_imports"]:
                                    if f"import {import_pattern}" in content:
                                        score += 2
                                        break
                        except Exception:
                            pass
            
            if score > 0:
                detected.append({
                    "id": framework_id,
                    "name": patterns["framework"],
                    "type": patterns["type"],
                    "confidence": min(score / 3.0, 1.0),  # Normalize score
                })
        
        # Sort by confidence
        detected.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Filter out low-confidence detections that are likely false positives
        detected = [d for d in detected if d["confidence"] >= 0.33]
        
        return detected

    def _get_all_parsed_deps(self, repo: Repository) -> dict:
        """Get all parsed dependencies from various manifest files."""
        deps = {}
        
        if not repo.local_path:
            return deps
        
        local_path = Path(repo.local_path)
        
        # Parse package.json (npm)
        pkg_path = local_path / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                all_deps = set(pkg.get("dependencies", {}).keys())
                all_deps.update(pkg.get("devDependencies", {}).keys())
                deps["npm"] = all_deps
            except Exception:
                pass
        
        # Parse Gemfile (Ruby)
        gemfile_path = local_path / "Gemfile"
        if gemfile_path.exists():
            try:
                content = gemfile_path.read_text()
                gems = set()
                for match in re.finditer(r"gem\s+['\"]([^'\"]+)['\"]", content):
                    gems.add(match.group(1))
                deps["gems"] = gems
            except Exception:
                pass
        
        # Parse pom.xml or build.gradle (Java)
        java_deps = set()
        pom_path = local_path / "pom.xml"
        if pom_path.exists():
            try:
                content = pom_path.read_text()
                for match in re.finditer(r'<artifactId>([^<]+)</artifactId>', content):
                    java_deps.add(match.group(1))
                for match in re.finditer(r'<groupId>([^<]+)</groupId>', content):
                    java_deps.add(match.group(1))
            except Exception:
                pass
        
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = local_path / gradle_file
            if gradle_path.exists():
                try:
                    content = gradle_path.read_text()
                    for match in re.finditer(r"['\"]([^'\"]+:[^'\"]+)['\"]", content):
                        java_deps.add(match.group(1))
                except Exception:
                    pass
                break
        if java_deps:
            deps["java"] = java_deps
        
        # Parse composer.json (PHP)
        composer_path = local_path / "composer.json"
        if composer_path.exists():
            try:
                composer = json.loads(composer_path.read_text())
                all_deps = set(composer.get("require", {}).keys())
                all_deps.update(composer.get("require-dev", {}).keys())
                deps["composer"] = all_deps
            except Exception:
                pass
        
        # Parse .csproj files (C#/.NET)
        csproj_deps = set()
        for csproj_path in local_path.glob("**/*.csproj"):
            try:
                content = csproj_path.read_text()
                for match in re.finditer(r'<PackageReference\s+Include="([^"]+)"', content):
                    csproj_deps.add(match.group(1))
            except Exception:
                pass
        if csproj_deps:
            deps["nuget"] = csproj_deps
        
        # Parse Cargo.toml (Rust)
        cargo_path = local_path / "Cargo.toml"
        if cargo_path.exists():
            try:
                content = cargo_path.read_text()
                cargo_deps = set()
                if "[dependencies]" in content:
                    section = self._parse_toml_section(content, "[dependencies]")
                    cargo_deps.update(section.keys())
                if "[dev-dependencies]" in content:
                    section = self._parse_toml_section(content, "[dev-dependencies]")
                    cargo_deps.update(section.keys())
                deps["cargo"] = cargo_deps
            except Exception:
                pass
        
        # Parse go.mod (Go)
        go_mod_path = local_path / "go.mod"
        if go_mod_path.exists():
            try:
                content = go_mod_path.read_text()
                go_deps = set()
                for line in content.split("\n"):
                    match = re.match(r'\s*([^\s]+)\s+v', line)
                    if match:
                        go_deps.add(match.group(1))
                deps["go"] = go_deps
            except Exception:
                pass
        
        # Parse Package.swift (Swift)
        swift_path = local_path / "Package.swift"
        if swift_path.exists():
            try:
                content = swift_path.read_text()
                swift_deps = set()
                for match in re.finditer(r'\.package\s*\(\s*url:\s*"([^"]+)"', content):
                    url = match.group(1)
                    name = url.rstrip("/").split("/")[-1].replace(".git", "")
                    swift_deps.add(name)
                deps["swift"] = swift_deps
            except Exception:
                pass
        
        # Parse pubspec.yaml (Dart/Flutter)
        pubspec_path = local_path / "pubspec.yaml"
        if pubspec_path.exists():
            try:
                content = pubspec_path.read_text()
                dart_deps = set()
                in_deps = False
                for line in content.split("\n"):
                    if line.strip().startswith("dependencies:"):
                        in_deps = True
                        continue
                    elif line.strip().startswith("dev_dependencies:"):
                        continue
                    elif line and not line.startswith(" ") and not line.startswith("#"):
                        in_deps = False
                    if in_deps:
                        match = re.match(r'^\s+([a-zA-Z0-9_]+):', line)
                        if match:
                            dart_deps.add(match.group(1))
                deps["dart"] = dart_deps
            except Exception:
                pass
        
        # Parse mix.exs (Elixir)
        mix_path = local_path / "mix.exs"
        if mix_path.exists():
            try:
                content = mix_path.read_text()
                elixir_deps = set()
                for match in re.finditer(r'\{:([a-zA-Z0-9_]+),', content):
                    elixir_deps.add(match.group(1))
                deps["elixir"] = elixir_deps
            except Exception:
                pass
        
        return deps

    def _detect_architecture(self, file_paths: list[str]) -> dict:
        """Detect architectural patterns from directory structure."""
        # Get all directories
        directories = set()
        for path in file_paths:
            parts = Path(path).parts
            for i in range(1, len(parts)):
                directories.add("/".join(parts[:i]))
        
        top_level_dirs = {Path(p).parts[0].lower() for p in file_paths if Path(p).parts}
        
        detected_patterns = []
        
        for pattern_id, pattern_info in ARCHITECTURE_PATTERNS.items():
            if not pattern_info["indicators"]:
                continue
            
            matches = sum(
                1 for indicator in pattern_info["indicators"]
                if indicator.rstrip("/").lower() in top_level_dirs
                or any(indicator.lower() in d.lower() for d in directories)
            )
            
            if matches > 0:
                confidence = matches / len(pattern_info["indicators"])
                detected_patterns.append({
                    "pattern": pattern_id,
                    "description": pattern_info["description"],
                    "confidence": confidence,
                    "matched_indicators": matches,
                    "total_indicators": len(pattern_info["indicators"]),
                })
        
        # Sort by confidence
        detected_patterns.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Determine primary architecture
        primary = None
        if detected_patterns:
            primary = detected_patterns[0]
        elif len(top_level_dirs) <= 3:
            primary = {
                "pattern": "flat",
                "description": ARCHITECTURE_PATTERNS["flat"]["description"],
                "confidence": 1.0,
            }
        
        if primary is None:
            primary = {
                "pattern": "standard",
                "description": "Standard project structure",
                "confidence": 1.0,
            }
        
        return {
            "primary": primary,
            "detected_patterns": detected_patterns,
            "directory_count": len(directories),
        }

    def _find_key_files(self, files: list[RepositoryFile]) -> dict:
        """Find key files in the repository."""
        key_files = {
            "documentation": [],
            "configuration": [],
            "build": [],
            "ci_cd": [],
        }
        
        for file in files:
            file_path = file.file_path
            file_name = Path(file_path).name
            
            # Documentation
            for pattern in DOC_PATTERNS:
                if re.match(pattern, file_path, re.IGNORECASE) or re.match(pattern, file_name, re.IGNORECASE):
                    key_files["documentation"].append({
                        "path": file_path,
                        "type": self._identify_doc_type(file_name),
                    })
                    break
            
            # Configuration
            for pattern in CONFIG_FILE_PATTERNS:
                if re.match(pattern, file_name, re.IGNORECASE) or re.match(pattern, file_path):
                    key_files["configuration"].append({
                        "path": file_path,
                        "type": self._identify_config_type(file_name),
                    })
                    break
            
            # CI/CD
            if ".github/" in file_path or "ci/" in file_path.lower():
                key_files["ci_cd"].append({
                    "path": file_path,
                })
        
        return key_files

    def _identify_doc_type(self, file_name: str) -> str:
        """Identify the type of documentation file."""
        name_upper = file_name.upper()
        if "README" in name_upper:
            return "readme"
        if "CHANGELOG" in name_upper or "CHANGES" in name_upper:
            return "changelog"
        if "CONTRIBUTING" in name_upper:
            return "contributing"
        if "LICENSE" in name_upper:
            return "license"
        return "documentation"

    def _identify_config_type(self, file_name: str) -> str:
        """Identify the type of configuration file."""
        name_lower = file_name.lower()
        if "package.json" in name_lower:
            return "npm"
        if "pyproject.toml" in name_lower:
            return "python"
        if "cargo.toml" in name_lower:
            return "rust"
        if "go.mod" in name_lower:
            return "go"
        if "tsconfig" in name_lower:
            return "typescript"
        if "docker" in name_lower:
            return "docker"
        if ".eslint" in name_lower:
            return "eslint"
        if ".prettier" in name_lower:
            return "prettier"
        if "makefile" in name_lower:
            return "make"
        return "config"

    def _analyze_conventions(
        self,
        repo: Repository,
        files: list[RepositoryFile],
    ) -> dict:
        """Analyze coding conventions in the repository."""
        conventions = {
            "file_naming": {},
            "directory_naming": {},
            "detected_style": None,
        }
        
        # Analyze file naming
        file_names = [Path(f.file_path).name for f in files]
        
        snake_case_count = sum(1 for n in file_names if re.match(r'^[a-z][a-z0-9_]*\.[a-z]+$', n))
        camel_case_count = sum(1 for n in file_names if re.match(r'^[a-z][a-zA-Z0-9]*\.[a-z]+$', n))
        pascal_case_count = sum(1 for n in file_names if re.match(r'^[A-Z][a-zA-Z0-9]*\.[a-z]+$', n))
        kebab_case_count = sum(1 for n in file_names if re.match(r'^[a-z][a-z0-9-]*\.[a-z]+$', n))
        
        if len(file_names) > 0:
            conventions["file_naming"] = {
                "snake_case": snake_case_count / len(file_names),
                "camelCase": camel_case_count / len(file_names),
                "PascalCase": pascal_case_count / len(file_names),
                "kebab-case": kebab_case_count / len(file_names),
            }
            
            # Determine dominant style
            max_style = max(conventions["file_naming"].items(), key=lambda x: x[1])
            if max_style[1] > 0.5:
                conventions["detected_style"] = max_style[0]
        
        # Check for linter configs
        linter_configs = []
        if repo.local_path:
            local_path = Path(repo.local_path)
            
            if (local_path / ".eslintrc.json").exists() or (local_path / ".eslintrc.js").exists():
                linter_configs.append("ESLint")
            if (local_path / ".prettierrc").exists() or (local_path / ".prettierrc.json").exists():
                linter_configs.append("Prettier")
            if (local_path / "ruff.toml").exists() or (local_path / ".ruff.toml").exists():
                linter_configs.append("Ruff")
            if (local_path / "pyproject.toml").exists():
                content = (local_path / "pyproject.toml").read_text()
                if "[tool.ruff]" in content:
                    linter_configs.append("Ruff")
                if "[tool.black]" in content:
                    linter_configs.append("Black")
                if "[tool.isort]" in content:
                    linter_configs.append("isort")
        
        conventions["linters"] = linter_configs
        
        return conventions

    def _generate_summary(self, analysis: dict) -> str:
        """Generate a human-readable summary of the analysis."""
        parts = []
        
        # Basic info
        repo_name = analysis.get("repo_name", "Unknown")
        parts.append(f"**{repo_name}** on branch `{analysis.get('branch', 'main')}`")
        
        # Frameworks
        frameworks = analysis.get("frameworks", [])
        if frameworks:
            fw_names = [f["name"] for f in frameworks[:3]]
            parts.append(f"Built with: {', '.join(fw_names)}")
        
        # Architecture
        arch = analysis.get("architecture", {})
        if arch.get("primary"):
            parts.append(f"Architecture: {arch['primary']['description']}")
        
        # Structure
        structure = analysis.get("structure", {})
        top_dirs = structure.get("top_level_directories", {})
        if top_dirs:
            important_dirs = [
                name for name, info in top_dirs.items()
                if info.get("purpose") != "Project files"
            ][:5]
            if important_dirs:
                parts.append(f"Key directories: {', '.join(important_dirs)}")
        
        # Dependencies
        deps = analysis.get("dependencies", {})
        prod_count = len(deps.get("production", []))
        dev_count = len(deps.get("development", []))
        if prod_count or dev_count:
            parts.append(f"Dependencies: {prod_count} production, {dev_count} development")
        
        # Entry points
        entry_points = analysis.get("entry_points", {})
        main_count = len(entry_points.get("main_files", []))
        cli_count = len(entry_points.get("cli_entry_points", []))
        api_count = len(entry_points.get("api_entry_points", []))
        
        if main_count or cli_count or api_count:
            ep_parts = []
            if main_count:
                ep_parts.append(f"{main_count} main")
            if cli_count:
                ep_parts.append(f"{cli_count} CLI")
            if api_count:
                ep_parts.append(f"{api_count} API")
            parts.append(f"Entry points: {', '.join(ep_parts)}")
        
        return "\n".join(parts)

    def _build_directory_tree(
        self,
        file_paths: list[str],
        max_depth: int,
    ) -> dict:
        """Build a nested directory tree structure."""
        tree = {"name": ".", "type": "directory", "children": {}}
        
        for path in sorted(file_paths):
            parts = Path(path).parts
            if len(parts) > max_depth:
                parts = parts[:max_depth]
            
            current = tree["children"]
            for i, part in enumerate(parts):
                is_file = (i == len(parts) - 1 and i == len(Path(path).parts) - 1)
                
                if part not in current:
                    current[part] = {
                        "name": part,
                        "type": "file" if is_file else "directory",
                        "children": {} if not is_file else None,
                    }
                
                if not is_file:
                    current = current[part]["children"]
        
        return tree

    def _annotate_tree(self, tree: dict) -> dict:
        """Add annotations to directory tree."""
        if tree.get("type") == "directory" and tree.get("children"):
            for name, child in tree["children"].items():
                if child.get("type") == "directory":
                    child["annotation"] = self._identify_directory_purpose(name)
                    self._annotate_tree(child)
        return tree

    def _count_directories(self, tree: dict) -> int:
        """Count directories in tree."""
        count = 0
        if tree.get("type") == "directory":
            count = 1
            if tree.get("children"):
                for child in tree["children"].values():
                    count += self._count_directories(child)
        return count
