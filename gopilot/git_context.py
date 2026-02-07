"""
Git Context - Local git repository interaction for copilot agent mode

Provides branch listing, diffs, changed files, and commit history
using only stdlib subprocess calls to the git CLI.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class GitContext:
    """Interact with a local git repository."""

    def __init__(self, repo_path: Optional[str] = None):
        """
        Initialize git context.

        Args:
            repo_path: Path to the git repository root.
                       Defaults to the current working directory.
        """
        self.repo_path = repo_path or os.getcwd()
        logger.info(f"GitContext initialized for: {self.repo_path}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_git(self, *args: str, check: bool = True) -> Optional[str]:
        """
        Execute a git command inside the repository.

        Args:
            *args: Arguments passed after ``git``.
            check: If True, return None on non-zero exit code.

        Returns:
            Stripped stdout string, or None on failure.
        """
        cmd = ["git", "-C", self.repo_path] + list(args)
        logger.debug(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check and result.returncode != 0:
                logger.warning(
                    f"git command failed ({result.returncode}): {result.stderr.strip()}"
                )
                return None
            return result.stdout.strip()
        except FileNotFoundError:
            logger.error("git executable not found")
            return None
        except subprocess.TimeoutExpired:
            logger.error("git command timed out")
            return None
        except Exception as exc:
            logger.error(f"git error: {exc}")
            return None

    def is_git_repo(self) -> bool:
        """Return True if the repo_path is inside a git repository."""
        return self._run_git("rev-parse", "--is-inside-work-tree") == "true"

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    def get_current_branch(self) -> Optional[str]:
        """Return the name of the currently checked-out branch."""
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def list_branches(self, all_branches: bool = False) -> list[str]:
        """
        List branches.

        Args:
            all_branches: Include remote-tracking branches when True.

        Returns:
            Sorted list of branch names.
        """
        args = ["branch", "--format=%(refname:short)"]
        if all_branches:
            args.append("--all")
        output = self._run_git(*args)
        if not output:
            return []
        return sorted(line.strip() for line in output.splitlines() if line.strip())

    # ------------------------------------------------------------------
    # Diff / changed-file operations
    # ------------------------------------------------------------------

    def get_diff(
        self,
        base: Optional[str] = None,
        target: Optional[str] = None,
        staged: bool = False,
        name_only: bool = False,
    ) -> Optional[str]:
        """
        Return a diff string.

        * No arguments → unstaged working-tree changes.
        * ``staged=True`` → staged (index) changes.
        * ``base`` only → diff between *base* and the working tree.
        * ``base`` + ``target`` → diff between two refs.

        Args:
            base: Base ref (branch / commit).
            target: Target ref.
            staged: Show staged changes instead of working-tree.
            name_only: Only list file names.

        Returns:
            Diff text, or None on error.
        """
        args = ["diff"]
        if name_only:
            args.append("--name-only")
        if staged:
            args.append("--cached")
        if base:
            args.append(base)
        if target:
            args.append(target)
        return self._run_git(*args)

    def get_changed_files(
        self,
        base: Optional[str] = None,
        target: Optional[str] = None,
        staged: bool = False,
    ) -> list[str]:
        """
        Return a list of changed file paths.

        See :meth:`get_diff` for parameter semantics.
        """
        output = self.get_diff(base=base, target=target, staged=staged, name_only=True)
        if not output:
            return []
        return [f.strip() for f in output.splitlines() if f.strip()]

    def get_staged_diff(self) -> Optional[str]:
        """Shortcut: return the staged (index) diff."""
        return self.get_diff(staged=True)

    # ------------------------------------------------------------------
    # Commit log
    # ------------------------------------------------------------------

    def get_commit_log(
        self,
        n: int = 10,
        branch: Optional[str] = None,
        oneline: bool = True,
    ) -> list[str]:
        """
        Return recent commits.

        Args:
            n: Maximum number of commits.
            branch: Branch/ref to inspect (defaults to HEAD).
            oneline: Use ``--oneline`` format.

        Returns:
            List of commit lines.
        """
        args = ["log", f"-{n}"]
        if oneline:
            args.append("--oneline")
        if branch:
            args.append(branch)
        output = self._run_git(*args)
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def get_branch_commits(
        self,
        base: str,
        target: Optional[str] = None,
        n: int = 50,
    ) -> list[str]:
        """
        Return commits on *target* that are not on *base*.

        Args:
            base: Base branch (e.g. ``main``).
            target: Target branch (defaults to HEAD).
            n: Maximum number of commits.

        Returns:
            Oneline commit list.
        """
        ref_range = f"{base}..{target}" if target else f"{base}..HEAD"
        args = ["log", "--oneline", f"-{n}", ref_range]
        output = self._run_git(*args)
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # File listing
    # ------------------------------------------------------------------

    def list_project_files(self) -> list[str]:
        """
        List all tracked files in the repository.

        Returns:
            Sorted list of file paths relative to repository root.
        """
        output = self._run_git("ls-files")
        if not output:
            return []
        return sorted(line.strip() for line in output.splitlines() if line.strip())

    # ------------------------------------------------------------------
    # File content helpers
    # ------------------------------------------------------------------

    def get_file_at_ref(self, path: str, ref: str = "HEAD") -> Optional[str]:
        """
        Return file content at a specific git ref.

        Args:
            path: Repository-relative file path.
            ref: Git ref (branch, tag, commit SHA).

        Returns:
            File content string, or None on error.
        """
        return self._run_git("show", f"{ref}:{path}")

    # ------------------------------------------------------------------
    # Summary helpers (used by the agent)
    # ------------------------------------------------------------------

    def get_status_summary(self) -> dict:
        """
        Build a summary dict of the current repository state.

        Returns:
            Dictionary with keys: branch, branches, staged_files,
            unstaged_files, recent_commits.
        """
        return {
            "branch": self.get_current_branch(),
            "branches": self.list_branches(),
            "staged_files": self.get_changed_files(staged=True),
            "unstaged_files": self.get_changed_files(),
            "recent_commits": self.get_commit_log(n=5),
        }
