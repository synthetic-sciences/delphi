"""
Synsc Context - Unified MCP Server for Code, Research Paper, and Dataset Indexing.

Provides deep context to AI agents through:
- GitHub repository indexing and semantic code search
- Research paper indexing from arXiv and local PDFs
- HuggingFace dataset card indexing and semantic search
- Symbol extraction and analysis
- Citation, equation, and code snippet extraction from papers
"""

__version__ = "1.2.0"
__author__ = "InkVell"

from synsc.config import get_config, SynscConfig

__all__ = ["get_config", "SynscConfig", "__version__"]
