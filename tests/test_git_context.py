"""Tests for gopilot.git_context module."""

import os
import subprocess
import tempfile
import unittest

from gopilot.git_context import GitContext


class TestGitContext(unittest.TestCase):
    """Tests that exercise GitContext against a real temporary git repo."""

    def setUp(self):
        """Create a temporary git repository for each test."""
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(
            ["git", "init", self.tmpdir], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "config", "user.name", "Test"],
            capture_output=True,
            check=True,
        )
        # Create an initial commit so HEAD exists
        init_file = os.path.join(self.tmpdir, "README.md")
        with open(init_file, "w") as f:
            f.write("# test repo\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "."], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "commit", "-m", "initial commit"],
            capture_output=True,
            check=True,
        )
        self.ctx = GitContext(self.tmpdir)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- basic state ----

    def test_is_git_repo(self):
        self.assertTrue(self.ctx.is_git_repo())

    def test_is_not_git_repo(self):
        ctx = GitContext(tempfile.mkdtemp())
        self.assertFalse(ctx.is_git_repo())

    def test_get_current_branch(self):
        branch = self.ctx.get_current_branch()
        self.assertIsNotNone(branch)
        # Default branch name varies (master / main), just check non-empty
        self.assertTrue(len(branch) > 0)

    # ---- branches ----

    def test_list_branches(self):
        branches = self.ctx.list_branches()
        self.assertIsInstance(branches, list)
        self.assertGreater(len(branches), 0)

    def test_list_branches_after_new_branch(self):
        subprocess.run(
            ["git", "-C", self.tmpdir, "branch", "feature-x"],
            capture_output=True,
            check=True,
        )
        branches = self.ctx.list_branches()
        self.assertIn("feature-x", branches)

    # ---- diff / changed files ----

    def test_get_diff_no_changes(self):
        diff = self.ctx.get_diff()
        # No uncommitted changes -> empty or None
        self.assertTrue(diff is not None)

    def test_get_changed_files_with_modification(self):
        filepath = os.path.join(self.tmpdir, "README.md")
        with open(filepath, "a") as f:
            f.write("new line\n")
        changed = self.ctx.get_changed_files()
        self.assertIn("README.md", changed)

    def test_get_staged_diff(self):
        filepath = os.path.join(self.tmpdir, "new.txt")
        with open(filepath, "w") as f:
            f.write("hello\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "new.txt"],
            capture_output=True,
            check=True,
        )
        diff = self.ctx.get_staged_diff()
        self.assertIsNotNone(diff)
        self.assertIn("hello", diff)

    def test_get_changed_files_between_branches(self):
        subprocess.run(
            ["git", "-C", self.tmpdir, "checkout", "-b", "feature-y"],
            capture_output=True,
            check=True,
        )
        filepath = os.path.join(self.tmpdir, "feature.py")
        with open(filepath, "w") as f:
            f.write("print('hi')\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "."], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "commit", "-m", "feature commit"],
            capture_output=True,
            check=True,
        )
        # Get the default branch name
        default = subprocess.run(
            ["git", "-C", self.tmpdir, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        # Switch back and compare
        subprocess.run(
            ["git", "-C", self.tmpdir, "checkout", "-"],
            capture_output=True,
            check=True,
        )
        changed = self.ctx.get_changed_files(
            base=self.ctx.get_current_branch(), target="feature-y"
        )
        self.assertIn("feature.py", changed)

    # ---- commit log ----

    def test_get_commit_log(self):
        log = self.ctx.get_commit_log(n=5)
        self.assertIsInstance(log, list)
        self.assertGreater(len(log), 0)
        self.assertIn("initial commit", log[0])

    def test_get_branch_commits(self):
        # Create a new branch with a commit
        subprocess.run(
            ["git", "-C", self.tmpdir, "checkout", "-b", "br1"],
            capture_output=True,
            check=True,
        )
        filepath = os.path.join(self.tmpdir, "b.txt")
        with open(filepath, "w") as f:
            f.write("b\n")
        subprocess.run(
            ["git", "-C", self.tmpdir, "add", "."], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", self.tmpdir, "commit", "-m", "branch commit"],
            capture_output=True,
            check=True,
        )
        # Get the initial branch name
        subprocess.run(
            ["git", "-C", self.tmpdir, "checkout", "-"],
            capture_output=True,
            check=True,
        )
        base = self.ctx.get_current_branch()
        commits = self.ctx.get_branch_commits(base=base, target="br1")
        self.assertGreater(len(commits), 0)
        self.assertIn("branch commit", commits[0])

    # ---- file at ref ----

    def test_get_file_at_ref(self):
        content = self.ctx.get_file_at_ref("README.md", "HEAD")
        self.assertIsNotNone(content)
        self.assertIn("# test repo", content)

    # ---- status summary ----

    def test_get_status_summary(self):
        summary = self.ctx.get_status_summary()
        self.assertIn("branch", summary)
        self.assertIn("branches", summary)
        self.assertIn("staged_files", summary)
        self.assertIn("unstaged_files", summary)
        self.assertIn("recent_commits", summary)


if __name__ == "__main__":
    unittest.main()
