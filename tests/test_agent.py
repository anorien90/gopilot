"""Tests for gopilot.agent module."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gopilot.agent import CopilotAgent, _truncate
from gopilot.git_context import GitContext
from gopilot.ollama_client import OllamaClient


class TestTruncate(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(_truncate("abc", 10), "abc")

    def test_long_text_truncated(self):
        result = _truncate("a" * 20, 10)
        self.assertTrue(result.startswith("a" * 10))
        self.assertIn("truncated", result)


class TestCopilotAgent(unittest.TestCase):
    """Tests for CopilotAgent using a real temp git repo + mocked Ollama."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init", self.tmpdir], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", self.tmpdir, "config", "user.email", "t@t.com"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "config", "user.name", "T"],
            capture_output=True,
            check=True,
        )
        with open(os.path.join(self.tmpdir, "a.txt"), "w") as f:
            f.write("hello\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "."], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "commit", "-m", "init"],
            capture_output=True,
            check=True,
        )

        self.git = GitContext(self.tmpdir)
        self.ollama = MagicMock(spec=OllamaClient)
        self.ollama.generate.return_value = "AI response"
        self.agent = CopilotAgent(self.ollama, self.git)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- process_query ----

    def test_process_query_calls_ollama(self):
        result = self.agent.process_query("What is this repo?")
        self.assertEqual(result, "AI response")
        self.ollama.generate.assert_called_once()
        call_kwargs = self.ollama.generate.call_args
        self.assertIn("system", call_kwargs.kwargs or call_kwargs[1])

    # ---- review_changes ----

    def test_review_changes_no_diff(self):
        result = self.agent.review_changes()
        self.assertEqual(result, "No changes detected to review.")

    def test_review_changes_with_diff(self):
        with open(os.path.join(self.tmpdir, "a.txt"), "a") as f:
            f.write("world\n")
        result = self.agent.review_changes()
        self.assertEqual(result, "AI response")
        self.ollama.generate.assert_called_once()

    # ---- suggest_commit_message ----

    def test_suggest_commit_message_no_changes(self):
        result = self.agent.suggest_commit_message()
        self.assertEqual(result, "No changes detected.")

    def test_suggest_commit_message_with_staged(self):
        with open(os.path.join(self.tmpdir, "b.txt"), "w") as f:
            f.write("new\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "b.txt"],
            capture_output=True,
            check=True,
        )
        result = self.agent.suggest_commit_message()
        self.assertEqual(result, "AI response")

    # ---- explain_diff ----

    def test_explain_diff_no_changes(self):
        branch = self.git.get_current_branch()
        result = self.agent.explain_diff(base=branch)
        self.assertIn("No differences", result)

    def test_explain_diff_between_branches(self):
        subprocess.run(
            ["git", "-C", self.tmpdir, "checkout", "-b", "feat"],
            capture_output=True,
            check=True,
        )
        with open(os.path.join(self.tmpdir, "c.txt"), "w") as f:
            f.write("feat\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "."], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "commit", "-m", "feat work"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "checkout", "-"],
            capture_output=True,
            check=True,
        )
        base = self.git.get_current_branch()
        result = self.agent.explain_diff(base=base, target="feat")
        self.assertEqual(result, "AI response")

    # ---- summarize_branch ----

    def test_summarize_branch(self):
        result = self.agent.summarize_branch()
        self.assertEqual(result, "AI response")

    # ---- handle_agent_request ----

    def test_handle_agent_request_status(self):
        resp = self.agent.handle_agent_request("status", {})
        self.assertIn("result", resp)
        self.assertIn("branch", resp["result"])

    def test_handle_agent_request_unknown(self):
        resp = self.agent.handle_agent_request("nope", {})
        self.assertIn("error", resp)

    def test_handle_agent_request_query(self):
        resp = self.agent.handle_agent_request("query", {"query": "hi"})
        self.assertEqual(resp["result"], "AI response")

    # ---- get_context_for_completion ----

    def test_get_context_for_completion(self):
        ctx = self.agent.get_context_for_completion()
        self.assertIn("[branch:", ctx)


class TestCopilotAgentLSPIntegration(unittest.TestCase):
    """Test the agent request through the LSP server dispatch."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init", self.tmpdir], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", self.tmpdir, "config", "user.email", "t@t.com"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "config", "user.name", "T"],
            capture_output=True,
            check=True,
        )
        with open(os.path.join(self.tmpdir, "a.txt"), "w") as f:
            f.write("x\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "."], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "commit", "-m", "init"],
            capture_output=True,
            check=True,
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_server_agent_request(self):
        from gopilot.server import LSPServer

        server = LSPServer(repo_path=self.tmpdir)
        self.assertIsNotNone(server.agent)

        # Status action does not need Ollama
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "gopilot/agent",
                "params": {"action": "status", "params": {}},
            }
        )
        self.assertIsNotNone(response)
        self.assertEqual(response["id"], 1)
        self.assertIn("branch", response["result"]["result"])

    def test_server_agent_not_available_outside_git(self):
        non_git = tempfile.mkdtemp()
        try:
            from gopilot.server import LSPServer

            server = LSPServer(repo_path=non_git)
            self.assertIsNone(server.agent)

            response = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "gopilot/agent",
                    "params": {"action": "status", "params": {}},
                }
            )
            self.assertIn("error", response["result"])
        finally:
            import shutil

            shutil.rmtree(non_git, ignore_errors=True)

    def test_initialize_advertises_agent_capabilities(self):
        from gopilot.server import LSPServer

        server = LSPServer(repo_path=self.tmpdir)
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "initialize",
                "params": {"rootUri": f"file://{self.tmpdir}"},
            }
        )
        result = response["result"]
        self.assertIn("agentCapabilities", result["serverInfo"])
        self.assertIn("query", result["serverInfo"]["agentCapabilities"]["actions"])


if __name__ == "__main__":
    unittest.main()
