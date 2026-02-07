"""
Copilot Agent - AI-powered git-aware code assistant

Works as a GitHub Copilot-style agent that understands local git branches
and provides intelligent code review, commit message suggestions,
branch summaries, and interactive Q&A over repository context.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .git_context import GitContext
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# Maximum diff length sent to the model (characters).
_MAX_DIFF_CHARS = 4000


def _truncate(text: str, limit: int = _MAX_DIFF_CHARS) -> str:
    """Truncate text to *limit* characters with an indicator."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


class CopilotAgent:
    """Git-aware copilot agent backed by a local Ollama model."""

    def __init__(self, ollama_client: OllamaClient, git_context: GitContext):
        """
        Initialize the agent.

        Args:
            ollama_client: Configured Ollama client.
            git_context: GitContext bound to a local repository.
        """
        self.ollama = ollama_client
        self.git = git_context
        logger.info("CopilotAgent initialized")

    # ------------------------------------------------------------------
    # Public high-level actions
    # ------------------------------------------------------------------

    def process_query(self, query: str) -> Optional[str]:
        """
        Process a free-form natural-language query using repository
        context (current branch, recent commits, staged diff).

        Args:
            query: User question or instruction.

        Returns:
            AI-generated response text, or None on error.
        """
        status = self.git.get_status_summary()
        context_parts = [
            f"Current branch: {status.get('branch', 'unknown')}",
            f"Local branches: {', '.join(status.get('branches', []))}",
        ]
        staged = status.get("staged_files", [])
        if staged:
            context_parts.append(f"Staged files: {', '.join(staged)}")
        unstaged = status.get("unstaged_files", [])
        if unstaged:
            context_parts.append(f"Unstaged files: {', '.join(unstaged)}")
        commits = status.get("recent_commits", [])
        if commits:
            context_parts.append("Recent commits:\n" + "\n".join(commits))

        context_text = "\n".join(context_parts)

        system = (
            "You are a GitHub Copilot-style agent embedded in a developer's "
            "local environment. You have access to the git repository context "
            "shown below. Answer the developer's question concisely and helpfully.\n\n"
            f"Repository context:\n{context_text}"
        )
        return self.ollama.generate(prompt=query, system=system)

    def review_changes(self, base_branch: Optional[str] = None) -> Optional[str]:
        """
        Review current changes (staged or working-tree diff) and
        return AI-generated feedback.

        Args:
            base_branch: Compare against this branch instead of
                         looking at the working-tree diff.

        Returns:
            Review text, or None.
        """
        if base_branch:
            diff = self.git.get_diff(base=base_branch)
        else:
            diff = self.git.get_staged_diff()
            if not diff:
                diff = self.git.get_diff()

        if not diff:
            return "No changes detected to review."

        system = (
            "You are a senior code reviewer. Review the following diff and "
            "provide actionable feedback. Focus on bugs, readability, "
            "performance, and security. Be concise."
        )
        prompt = f"Review this diff:\n```diff\n{_truncate(diff)}\n```"
        return self.ollama.generate(prompt=prompt, system=system)

    def suggest_commit_message(self) -> Optional[str]:
        """
        Suggest a commit message based on the currently staged changes.

        Returns:
            Suggested commit message, or None.
        """
        diff = self.git.get_staged_diff()
        if not diff:
            diff = self.git.get_diff()
        if not diff:
            return "No changes detected."

        system = (
            "You are a commit message generator. Based on the diff provided, "
            "write a clear, conventional commit message. Use the format:\n"
            "<type>(<scope>): <description>\n\n<body>\n\n"
            "Types: feat, fix, docs, style, refactor, test, chore."
        )
        prompt = f"Generate a commit message for:\n```diff\n{_truncate(diff)}\n```"
        return self.ollama.generate(prompt=prompt, system=system)

    def explain_diff(
        self,
        base: str,
        target: Optional[str] = None,
    ) -> Optional[str]:
        """
        Explain the diff between two branches in plain language.

        Args:
            base: Base branch name.
            target: Target branch (defaults to current HEAD).

        Returns:
            Explanation text, or None.
        """
        diff = self.git.get_diff(base=base, target=target)
        if not diff:
            return "No differences found between the specified branches."

        commits = self.git.get_branch_commits(base=base, target=target)
        commits_text = "\n".join(commits) if commits else "(no unique commits)"

        system = (
            "You are a technical writer. Explain the following code changes "
            "between two git branches in clear, concise language suitable for "
            "a pull request description."
        )
        prompt = (
            f"Commits:\n{commits_text}\n\n"
            f"Diff:\n```diff\n{_truncate(diff)}\n```"
        )
        return self.ollama.generate(prompt=prompt, system=system)

    def summarize_branch(self, branch: Optional[str] = None) -> Optional[str]:
        """
        Summarize work done on a branch.

        Args:
            branch: Branch to summarize (defaults to current branch).

        Returns:
            Summary text, or None.
        """
        branch = branch or self.git.get_current_branch()
        if not branch:
            return None

        commits = self.git.get_commit_log(n=20, branch=branch)
        if not commits:
            return f"No commits found on branch '{branch}'."

        system = (
            "You are a project manager assistant. Summarize the work done "
            "on this branch based on the commit history. Be concise."
        )
        prompt = (
            f"Branch: {branch}\n"
            f"Commits:\n" + "\n".join(commits)
        )
        return self.ollama.generate(prompt=prompt, system=system)

    # ------------------------------------------------------------------
    # Structured helpers (used by LSP custom methods)
    # ------------------------------------------------------------------

    def get_context_for_completion(self) -> str:
        """
        Return a compact context string suitable for enriching
        code-completion prompts with git awareness.
        """
        branch = self.git.get_current_branch() or "unknown"
        staged = self.git.get_changed_files(staged=True)
        parts = [f"[branch:{branch}]"]
        if staged:
            parts.append(f"[staged:{','.join(staged[:5])}]")
        return " ".join(parts)

    def handle_agent_request(self, action: str, params: dict) -> dict[str, Any]:
        """
        Dispatch an agent request by *action* name.

        Supported actions:
            query, review, commit_message, explain_diff,
            summarize_branch, status

        Args:
            action: Action identifier.
            params: Action-specific parameters.

        Returns:
            Dict with ``result`` or ``error`` key.
        """
        try:
            if action == "query":
                text = self.process_query(params.get("query", ""))
            elif action == "review":
                text = self.review_changes(params.get("base_branch"))
            elif action == "commit_message":
                text = self.suggest_commit_message()
            elif action == "explain_diff":
                text = self.explain_diff(
                    base=params.get("base", "main"),
                    target=params.get("target"),
                )
            elif action == "summarize_branch":
                text = self.summarize_branch(params.get("branch"))
            elif action == "status":
                return {"result": self.git.get_status_summary()}
            else:
                return {"error": f"Unknown agent action: {action}"}

            if text is None:
                return {"error": "Failed to generate response (Ollama unreachable?)"}
            return {"result": text}
        except Exception as exc:
            logger.exception(f"Agent error for action={action}: {exc}")
            return {"error": str(exc)}


if __name__ == "__main__"
    agent = Agent(git=Git())
    agent.handle_agent_request(action="query", params={"query": ""})
