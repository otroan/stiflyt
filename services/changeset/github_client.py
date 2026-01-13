"""GitHub client for creating PRs."""
import os
import json
import subprocess
from typing import Dict, Optional
from pathlib import Path


class GitHubClient:
    """Client for GitHub operations."""

    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        token: Optional[str] = None,
        use_cli: bool = True,
    ):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.use_cli = use_cli
        self.repo_url = f"https://github.com/{repo_owner}/{repo_name}.git"

    def create_pr(
        self,
        changeset_id: str,
        title: str,
        body: str,
        artifacts_dir: Path,
        base_branch: str = "main",
    ) -> str:
        """Create a PR with changeset artifacts. Returns PR URL."""
        branch_name = f"changeset/{changeset_id}"
        
        if self.use_cli:
            return self._create_pr_with_cli(
                branch_name, title, body, artifacts_dir, base_branch
            )
        else:
            return self._create_pr_with_api(
                branch_name, title, body, artifacts_dir, base_branch
            )

    def _create_pr_with_cli(
        self,
        branch_name: str,
        title: str,
        body: str,
        artifacts_dir: Path,
        base_branch: str,
    ) -> str:
        """Create PR using GitHub CLI."""
        import tempfile
        import shutil
        
        # Clone or use existing repo
        work_dir = Path(tempfile.mkdtemp())
        try:
            # Check if repo exists locally, otherwise clone
            repo_path = work_dir / self.repo_name
            if not repo_path.exists():
                subprocess.run(
                    ["git", "clone", self.repo_url, str(repo_path)],
                    check=True,
                    capture_output=True,
                )
            
            # Create branch
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            
            # Copy artifacts
            changeset_dir = repo_path / "changesets" / branch_name.split("/")[1]
            changeset_dir.mkdir(parents=True, exist_ok=True)
            
            for artifact_file in artifacts_dir.glob("*"):
                if artifact_file.is_file():
                    shutil.copy2(artifact_file, changeset_dir / artifact_file.name)
            
            # Commit
            subprocess.run(
                ["git", "add", "changesets/"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", f"Changeset: {title}"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            
            # Push
            subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            
            # Create PR
            result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--title", title,
                    "--body", body,
                    "--base", base_branch,
                    "--head", branch_name,
                ],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            
            pr_url = result.stdout.strip()
            return pr_url
            
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _create_pr_with_api(
        self,
        branch_name: str,
        title: str,
        body: str,
        artifacts_dir: Path,
        base_branch: str,
    ) -> str:
        """Create PR using GitHub REST API."""
        import requests
        
        if not self.token:
            raise ValueError("GITHUB_TOKEN required for API mode")
        
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }
        
        # This is simplified - full implementation would:
        # 1. Create branch via API
        # 2. Upload files via API
        # 3. Create PR
        
        # For MVP, we'll use CLI as it's simpler
        return self._create_pr_with_cli(branch_name, title, body, artifacts_dir, base_branch)
