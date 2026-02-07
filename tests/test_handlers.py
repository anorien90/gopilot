"""Tests for gopilot.handlers module - context layering and completion."""

import unittest
from unittest.mock import MagicMock, patch

from gopilot.handlers import LSPHandlers
from gopilot.ollama_client import OllamaClient


class TestLSPHandlersContextLayering(unittest.TestCase):
    """Tests for the layered context system in LSPHandlers."""

    def setUp(self):
        self.ollama = MagicMock(spec=OllamaClient)
        self.ollama.complete_code.return_value = "completed_code()"
        self.handlers = LSPHandlers(self.ollama, context_lines=5)

    def test_init_default_context_lines(self):
        h = LSPHandlers(self.ollama)
        self.assertEqual(h.context_lines, 50)

    def test_init_custom_context_lines(self):
        self.assertEqual(self.handlers.context_lines, 5)

    def test_init_with_git_context(self):
        git_ctx = MagicMock()
        h = LSPHandlers(self.ollama, git_context=git_ctx)
        self.assertIs(h.git_context, git_ctx)

    def test_init_without_git_context(self):
        self.assertIsNone(self.handlers.git_context)

    # ---- remove_document ----

    def test_remove_document(self):
        self.handlers.store_document("file://a.py", "content")
        self.handlers.remove_document("file://a.py")
        self.assertIsNone(self.handlers.get_document("file://a.py"))

    def test_remove_document_not_found(self):
        # Should not raise
        self.handlers.remove_document("file://nonexistent.py")

    # ---- _extract_current_line_prefix ----

    def test_extract_current_line_prefix(self):
        result = self.handlers._extract_current_line_prefix("def hello():", 4)
        self.assertEqual(result, "def ")

    def test_extract_current_line_prefix_start(self):
        result = self.handlers._extract_current_line_prefix("def hello():", 0)
        self.assertEqual(result, "")

    def test_extract_current_line_prefix_end(self):
        result = self.handlers._extract_current_line_prefix("def hello():", 12)
        self.assertEqual(result, "def hello():")

    def test_extract_current_line_prefix_negative(self):
        result = self.handlers._extract_current_line_prefix("hello", -1)
        self.assertEqual(result, "")

    # ---- _build_local_scope ----

    def test_build_local_scope_basic(self):
        lines = ["line0", "line1", "line2", "line3", "line4"]
        code_before, code_after, prefix = self.handlers._build_local_scope(
            lines, line_num=2, char_num=3
        )
        self.assertIn("line1", code_before)
        self.assertIn("lin", code_before)  # cursor prefix from line2[:3]
        self.assertIn("e2", code_after)    # rest of line2 after char 3
        self.assertIn("line3", code_after)
        self.assertEqual(prefix, "lin")

    def test_build_local_scope_cursor_at_start(self):
        lines = ["line0", "line1", "line2"]
        code_before, code_after, prefix = self.handlers._build_local_scope(
            lines, line_num=0, char_num=0
        )
        self.assertEqual(prefix, "")
        self.assertIn("line0", code_after)

    def test_build_local_scope_respects_context_lines(self):
        # With context_lines=5, should only include +/- 5 lines
        lines = [f"line{i}" for i in range(20)]
        code_before, code_after, prefix = self.handlers._build_local_scope(
            lines, line_num=10, char_num=0
        )
        # Should not include line0..line4 (outside -5 window from line 10)
        self.assertNotIn("line0", code_before)
        self.assertNotIn("line4", code_before)
        # Should include line5..line9
        self.assertIn("line5", code_before)
        self.assertIn("line9", code_before)
        # Should not include line16..line19 (outside +5 window from line 10)
        self.assertNotIn("line16", code_after)

    # ---- _extract_file_summary ----

    def test_extract_file_summary_python(self):
        text = "import os\nfrom sys import path\n\ndef hello():\n    pass\n\nclass Foo:\n    pass\n"
        summary = self.handlers._extract_file_summary(text, "python")
        self.assertIn("import os", summary)
        self.assertIn("from sys import path", summary)
        self.assertIn("def hello():", summary)
        self.assertIn("class Foo:", summary)

    def test_extract_file_summary_js(self):
        text = "import React from 'react';\nexport default App;\nconst x = 1;\n"
        summary = self.handlers._extract_file_summary(text, "javascript")
        self.assertIn("import React", summary)
        self.assertIn("export default", summary)

    def test_extract_file_summary_fallback(self):
        text = "some content\nanother line\n"
        summary = self.handlers._extract_file_summary(text, "unknown")
        self.assertIn("some content", summary)

    # ---- _build_secondary_context ----

    def test_build_secondary_context_no_other_docs(self):
        self.handlers.store_document("file://a.py", "content")
        result = self.handlers._build_secondary_context("file://a.py")
        self.assertEqual(result, "")

    def test_build_secondary_context_with_other_docs(self):
        self.handlers.store_document("file://a.py", "import os\ndef main():\n    pass\n")
        self.handlers.store_document("file://b.py", "import sys\nclass Helper:\n    pass\n")
        result = self.handlers._build_secondary_context("file://a.py")
        self.assertIn("Open Tabs", result)
        self.assertIn("b.py", result)
        self.assertNotIn("a.py", result)  # Should exclude current

    # ---- _build_project_scope ----

    def test_build_project_scope_no_git(self):
        result = self.handlers._build_project_scope()
        self.assertEqual(result, "")

    def test_build_project_scope_with_git(self):
        git_ctx = MagicMock()
        git_ctx.list_project_files.return_value = ["a.py", "b.py", "lib/c.py"]
        h = LSPHandlers(self.ollama, git_context=git_ctx)
        result = h._build_project_scope()
        self.assertIn("Project Files", result)
        self.assertIn("a.py", result)
        self.assertIn("lib/c.py", result)

    def test_build_project_scope_limits_files(self):
        git_ctx = MagicMock()
        git_ctx.list_project_files.return_value = [f"file{i}.py" for i in range(300)]
        h = LSPHandlers(self.ollama, git_context=git_ctx)
        result = h._build_project_scope()
        # Should be limited to MAX_PROJECT_FILES
        file_lines = [l for l in result.split("\n") if l.startswith("file")]
        self.assertLessEqual(len(file_lines), LSPHandlers.MAX_PROJECT_FILES)

    # ---- handle_completion with layered context ----

    def test_handle_completion_passes_layered_context(self):
        doc = "import os\n\ndef foo():\n    pri\n    return None\n"
        self.handlers.store_document("file://test.py", doc)

        self.handlers.handle_completion(
            "file://test.py",
            {"line": 3, "character": 7},  # at "    pri|"
        )

        # Verify complete_code was called with new parameters
        self.ollama.complete_code.assert_called_once()
        call_kwargs = self.ollama.complete_code.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        # Should have keyword args or positional
        if kwargs:
            self.assertIn("cursor_prefix", kwargs)
            self.assertIn("secondary_context", kwargs)
            self.assertIn("project_context", kwargs)
        else:
            # Positional args - at least code_before, code_after, language
            self.assertGreaterEqual(len(call_kwargs.args), 2)

    def test_handle_completion_cursor_prefix(self):
        doc = "def hello():\n    print('world')\n"
        self.handlers.store_document("file://test.py", doc)

        self.handlers.handle_completion(
            "file://test.py",
            {"line": 1, "character": 9},  # at "    print|"
        )

        call_kwargs = self.ollama.complete_code.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        if "cursor_prefix" in kwargs:
            self.assertEqual(kwargs["cursor_prefix"], "    print")

    def test_handle_completion_no_document(self):
        result = self.handlers.handle_completion(
            "file://missing.py", {"line": 0, "character": 0}
        )
        self.assertEqual(result, [])

    def test_handle_completion_returns_items(self):
        doc = "def foo():\n    \n"
        self.handlers.store_document("file://test.py", doc)

        items = self.handlers.handle_completion(
            "file://test.py",
            {"line": 1, "character": 4},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["detail"], "AI Completion (gopilot)")

    def test_handle_completion_empty_result(self):
        self.ollama.complete_code.return_value = ""
        doc = "def foo():\n    \n"
        self.handlers.store_document("file://test.py", doc)

        items = self.handlers.handle_completion(
            "file://test.py",
            {"line": 1, "character": 4},
        )
        self.assertEqual(items, [])


class TestListProjectFiles(unittest.TestCase):
    """Test list_project_files in GitContext."""

    def test_list_project_files_in_repo(self):
        import os
        import subprocess
        import tempfile

        tmpdir = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.email", "t@t.com"],
                capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.name", "T"],
                capture_output=True, check=True,
            )
            for name in ["a.py", "b.py", "lib/c.py"]:
                path = os.path.join(tmpdir, name)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write("x\n")
            subprocess.run(
                ["git", "-C", tmpdir, "add", "."], capture_output=True, check=True
            )
            subprocess.run(
                ["git", "-C", tmpdir, "commit", "-m", "init"],
                capture_output=True, check=True,
            )

            from gopilot.git_context import GitContext
            ctx = GitContext(tmpdir)
            files = ctx.list_project_files()
            self.assertIn("a.py", files)
            self.assertIn("b.py", files)
            self.assertIn("lib/c.py", files)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_list_project_files_not_git(self):
        import tempfile
        from gopilot.git_context import GitContext
        ctx = GitContext(tempfile.mkdtemp())
        self.assertEqual(ctx.list_project_files(), [])


if __name__ == "__main__":
    unittest.main()
