"""Structured AI adapters for existing subscription logins."""

from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter
from .gemini_adapter import GeminiAdapter
from .local_adapter import LocalAdapter

__all__ = ["ClaudeAdapter", "CodexAdapter", "GeminiAdapter", "LocalAdapter"]
