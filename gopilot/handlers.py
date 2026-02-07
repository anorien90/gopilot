"""
LSP Handlers - Completion and hover functionality
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, TYPE_CHECKING

from .ollama_client import OllamaClient

if TYPE_CHECKING:
    from .git_context import GitContext

logger = logging.getLogger(__name__)


class LSPHandlers:
    """Handlers for LSP requests using Ollama."""

    # Maximum number of project files to include in context (prevents overwhelming the model)
    MAX_PROJECT_FILES = 200

    def __init__(
        self,
        ollama_client: OllamaClient,
        git_context: Optional["GitContext"] = None,
        context_lines: int = 50,
    ):
        """
        Initialize LSP handlers.

        Args:
            ollama_client: Configured Ollama client instance
            git_context: Optional git context for project scope
            context_lines: Number of lines around cursor for local scope (default: 50)
        """
        self.ollama = ollama_client
        self.git_context = git_context
        self.context_lines = context_lines
        self._document_store: dict[str, str] = {}
        logger.info(
            f"LSP handlers initialized (context_lines={context_lines}, "
            f"git_context={'enabled' if git_context else 'disabled'})"
        )

    def store_document(self, uri: str, text: str) -> None:
        """
        Store document content for later reference.

        Args:
            uri: Document URI
            text: Document content
        """
        self._document_store[uri] = text
        logger.debug(f"Stored document: {uri} ({len(text)} chars)")

    def remove_document(self, uri: str) -> None:
        """
        Remove document from storage (when tab closes).

        Args:
            uri: Document URI
        """
        if uri in self._document_store:
            del self._document_store[uri]
            logger.debug(f"Removed document: {uri}")

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

    def _extract_current_line_prefix(self, line: str, char_pos: int) -> str:
        """
        Extract text on current line up to cursor position.

        Args:
            line: The current line text
            char_pos: Character position (cursor)

        Returns:
            Text from line start to cursor
        """
        if char_pos < 0:
            return ""
        return line[:char_pos]

    def _build_local_scope(
        self, lines: list[str], line_num: int, char_num: int
    ) -> tuple[str, str, str]:
        """
        Build local scope context around cursor.

        Args:
            lines: All document lines
            line_num: Current line number (0-indexed)
            char_num: Current character position

        Returns:
            Tuple of (code_before, code_after, cursor_prefix)
        """
        # Calculate range
        start_line = max(0, line_num - self.context_lines)
        end_line = min(len(lines), line_num + self.context_lines + 1)

        # Build code before cursor (within local scope)
        code_before_lines = lines[start_line:line_num]
        if line_num < len(lines):
            cursor_prefix = lines[line_num][:char_num]
            code_before_lines.append(cursor_prefix)
        else:
            cursor_prefix = ""

        # Build code after cursor (within local scope)
        code_after_lines = []
        if line_num < len(lines):
            code_after_lines.append(lines[line_num][char_num:])
        code_after_lines.extend(lines[line_num + 1 : end_line])

        code_before = "\n".join(code_before_lines)
        code_after = "\n".join(code_after_lines)

        return code_before, code_after, cursor_prefix

    def _extract_file_summary(self, text: str, language: str) -> str:
        """
        Extract key structural elements from a file for secondary context.

        Args:
            text: Document content
            language: Programming language

        Returns:
            Summary string with imports and signatures
        """
        lines = text.split("\n")
        summary_lines = []

        # Language-specific patterns
        if language == "python":
            # Combine iterations for efficiency - collect both imports and definitions
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Imports (typically in first 100 lines)
                if i < 100 and stripped.startswith(("import ", "from ")):
                    summary_lines.append(stripped)
                # Function and class definitions (throughout file)
                elif stripped.startswith(("def ", "class ", "async def ")):
                    # Extract just the signature
                    if ":" in stripped:
                        sig = stripped.split(":")[0] + ":"
                        summary_lines.append(sig)

        elif language in ("javascript", "typescript"):
            for line in lines[:100]:
                stripped = line.strip()
                if stripped.startswith(("import ", "export ", "const ", "let ", "var ")):
                    summary_lines.append(stripped[:80])  # Limit length

        # Generic fallback - just grab first few non-empty lines
        if not summary_lines:
            for line in lines[:20]:
                if line.strip():
                    summary_lines.append(line.strip()[:80])
                if len(summary_lines) >= 10:
                    break

        return "\n".join(summary_lines[:30])  # Max 30 lines

    def _build_secondary_context(self, current_uri: str) -> str:
        """
        Build secondary context from other open documents.

        Args:
            current_uri: URI of the active document (to exclude)

        Returns:
            Formatted secondary context string
        """
        if len(self._document_store) <= 1:
            return ""

        context_parts = []
        context_parts.append("=== Open Tabs (Secondary Context) ===")

        for uri, text in self._document_store.items():
            if uri == current_uri:
                continue

            # Extract file path from URI
            file_path = uri.replace("file://", "")
            language = self._get_language_from_uri(uri)

            # Get summary
            summary = self._extract_file_summary(text, language)

            context_parts.append(f"\n--- {file_path} ({language}) ---")
            if summary:
                context_parts.append(summary)

        return "\n".join(context_parts) if len(context_parts) > 1 else ""

    def _build_project_scope(self) -> str:
        """
        Build project scope context from git repository.

        Returns:
            Formatted project file listing
        """
        if not self.git_context:
            return ""

        files = self.git_context.list_project_files()
        if not files:
            return ""

        # Limit to reasonable number to avoid overwhelming the model with too many files
        if len(files) > self.MAX_PROJECT_FILES:
            files = files[:self.MAX_PROJECT_FILES]

        return "=== Project Files ===\n" + "\n".join(files)

    def handle_completion(
        self,
        uri: str,
        position: dict[str, int],
        context: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """
        Handle textDocument/completion request with layered context.

        Context priority (highest to lowest):
        1. Local scope: +/- context_lines around cursor
        2. Primary context: Current file structure
        3. Secondary context: Other open tabs
        4. Project scope: All project files

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

        # Build local scope (highest priority)
        code_before, code_after, cursor_prefix = self._build_local_scope(
            lines, line_num, char_num
        )

        # Build secondary context (other open tabs)
        secondary_context = self._build_secondary_context(uri)

        # Build project scope (file listing)
        project_context = self._build_project_scope()

        language = self._get_language_from_uri(uri)

        logger.debug(
            f"Completion request at {uri}:{line_num}:{char_num} ({language})"
        )
        logger.debug(
            f"Context: local={len(code_before)+len(code_after)} chars, "
            f"secondary={len(secondary_context)} chars, "
            f"project={len(project_context)} chars, "
            f"cursor_prefix='{cursor_prefix}'"
        )

        # Get completion from Ollama with layered context
        completion = self.ollama.complete_code(
            code_before=code_before,
            code_after=code_after,
            language=language,
            cursor_prefix=cursor_prefix,
            secondary_context=secondary_context,
            project_context=project_context,
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
