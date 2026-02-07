"""
LSP Handlers - Completion and hover functionality
"""

import logging
import re
from typing import Any, Optional

from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class LSPHandlers:
    """Handlers for LSP requests using Ollama."""

    def __init__(self, ollama_client: OllamaClient):
        """
        Initialize LSP handlers.

        Args:
            ollama_client: Configured Ollama client instance
        """
        self.ollama = ollama_client
        self._document_store: dict[str, str] = {}
        logger.info("LSP handlers initialized")

    def store_document(self, uri: str, text: str) -> None:
        """
        Store document content for later reference.

        Args:
            uri: Document URI
            text: Document content
        """
        self._document_store[uri] = text
        logger.debug(f"Stored document: {uri} ({len(text)} chars)")

    def get_document(self, uri: str) -> Optional[str]:
        """
        Retrieve stored document content.

        Args:
            uri: Document URI

        Returns:
            Document content or None if not found
        """
        return self._document_store.get(uri)

    def _get_language_from_uri(self, uri: str) -> str:
        """
        Detect programming language from file extension.

        Args:
            uri: Document URI

        Returns:
            Language identifier
        """
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".lua": "lua",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "zsh",
            ".sql": "sql",
            ".html": "html",
            ".css": "css",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".toml": "toml",
        }
        for ext, lang in ext_map.items():
            if uri.endswith(ext):
                return lang
        return "text"

    def handle_completion(
        self,
        uri: str,
        position: dict[str, int],
        context: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """
        Handle textDocument/completion request.

        Args:
            uri: Document URI
            position: Cursor position {line, character}
            context: Completion context

        Returns:
            List of completion items
        """
        document = self.get_document(uri)
        if not document:
            logger.warning(f"Document not found: {uri}")
            return []

        lines = document.split("\n")
        line_num = position.get("line", 0)
        char_num = position.get("character", 0)

        # Get code before and after cursor
        code_before_lines = lines[:line_num]
        if line_num < len(lines):
            code_before_lines.append(lines[line_num][:char_num])

        code_after_lines = []
        if line_num < len(lines):
            code_after_lines.append(lines[line_num][char_num:])
        code_after_lines.extend(lines[line_num + 1 :])

        code_before = "\n".join(code_before_lines)
        code_after = "\n".join(code_after_lines)

        # Limit context window
        code_before = code_before[-2000:] if len(code_before) > 2000 else code_before
        code_after = code_after[:500] if len(code_after) > 500 else code_after

        language = self._get_language_from_uri(uri)

        logger.debug(
            f"Completion request at {uri}:{line_num}:{char_num} ({language})"
        )

        # Get completion from Ollama
        completion = self.ollama.complete_code(
            code_before=code_before,
            code_after=code_after,
            language=language,
        )

        if not completion:
            logger.warning("No completion received from Ollama")
            return []

        # Clean up completion
        completion = self._clean_completion(completion)

        if not completion.strip():
            return []

        # Create completion item
        items = [
            {
                "label": completion.split("\n")[0][:50] + "..."
                if len(completion.split("\n")[0]) > 50
                else completion.split("\n")[0],
                "kind": 1,  # Text
                "detail": "AI Completion (gopilot)",
                "insertText": completion,
                "insertTextFormat": 1,  # PlainText
                "documentation": {
                    "kind": "markdown",
                    "value": f"```{language}\n{completion}\n```",
                },
            }
        ]

        logger.debug(f"Returning {len(items)} completion items")
        return items

    def _clean_completion(self, text: str) -> str:
        """
        Clean up completion text.

        Args:
            text: Raw completion from Ollama

        Returns:
            Cleaned completion text
        """
        # Remove markdown code blocks if present
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

        # Remove common prefixes/artifacts
        text = re.sub(r"^(Completion:|Output:|Result:)\s*", "", text, flags=re.IGNORECASE)

        # Strip leading/trailing whitespace but preserve indentation
        lines = text.split("\n")
        if lines:
            # Remove empty leading lines
            while lines and not lines[0].strip():
                lines.pop(0)
            # Remove empty trailing lines
            while lines and not lines[-1].strip():
                lines.pop()

        return "\n".join(lines)

    def handle_hover(
        self,
        uri: str,
        position: dict[str, int],
    ) -> Optional[dict[str, Any]]:
        """
        Handle textDocument/hover request.

        Args:
            uri: Document URI
            position: Cursor position {line, character}

        Returns:
            Hover information or None
        """
        document = self.get_document(uri)
        if not document:
            logger.warning(f"Document not found: {uri}")
            return None

        lines = document.split("\n")
        line_num = position.get("line", 0)

        if line_num >= len(lines):
            return None

        line = lines[line_num]
        char_num = position.get("character", 0)

        # Extract word under cursor
        word = self._get_word_at_position(line, char_num)
        if not word:
            return None

        # Get surrounding context (a few lines)
        start_line = max(0, line_num - 5)
        end_line = min(len(lines), line_num + 5)
        context = "\n".join(lines[start_line:end_line])

        language = self._get_language_from_uri(uri)

        logger.debug(f"Hover request for '{word}' at {uri}:{line_num}:{char_num}")

        # Get explanation from Ollama
        explanation = self.ollama.explain_code(
            code=context,
            language=language,
        )

        if not explanation:
            return None

        return {
            "contents": {
                "kind": "markdown",
                "value": f"**AI Explanation (gopilot)**\n\n{explanation}",
            },
            "range": {
                "start": {"line": line_num, "character": 0},
                "end": {"line": line_num, "character": len(line)},
            },
        }

    def _get_word_at_position(self, line: str, char: int) -> str:
        """
        Extract the word at a given position in a line.

        Args:
            line: Line of text
            char: Character position

        Returns:
            Word at position or empty string
        """
        if not line or char < 0 or char > len(line):
            return ""

        # Find word boundaries
        start = char
        end = char

        while start > 0 and (line[start - 1].isalnum() or line[start - 1] == "_"):
            start -= 1

        while end < len(line) and (line[end].isalnum() or line[end] == "_"):
            end += 1

        return line[start:end]
