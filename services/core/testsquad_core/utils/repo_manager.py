import os
import shutil
import logging
import asyncio
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class RepositoryManager:
    """
    Manages local workspace directories for remote repositories.
    Ensures repositories are cloned and updated before indexing.
    """
    def __init__(self, base_path: str = "/tmp/testsquad-workspaces"):
        self.base_path = base_path
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path, exist_ok=True)
        else:
            self._cleanup_on_startup()

    def _cleanup_on_startup(self):
        """Clean up stale workspaces on startup."""
        if not os.path.isdir(self.base_path):
            return
        try:
            for entry in os.listdir(self.base_path):
                full_path = os.path.join(self.base_path, entry)
                if os.path.isdir(full_path) and self._is_stale_workspace(full_path):
                    self._ensure_workspace_clean(full_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup stale workspaces: {e}")

    def _is_stale_workspace(self, repo_path: str) -> bool:
        """Check if a workspace directory is stale/incomplete.
        
        Stale if:
        - No .git directory (clone was interrupted)
        - No .git/index (git clone incomplete)
        - Has .lock 文件 (another process is using it)
        - Directory older than max_age seconds
        """
        if not os.path.isdir(repo_path):
            return True
        
        # Check for git directory
        git_dir = os.path.join(repo_path, ".git")
        if not os.path.isdir(git_dir):
            return True
        
        # Check for incomplete git clone (no index file)
        git_index = os.path.join(git_dir, "index")
        if not os.path.isfile(git_index):
            return True
        
        # Check for stale lock files
        for root, dirs, files in os.walk(repo_path):
            if ".lock" in files:
                return True
        
        # Check age
        import time
        mtime = os.path.getmtime(repo_path)
        age_seconds = time.time() - mtime
        if age_seconds > 86400:  # 24 hours
            return True
        
        return False

    def _ensure_workspace_clean(self, repo_path: str) -> bool:
        """Ensure workspace is clean. Returns True if cleanup was needed."""
        if self._is_stale_workspace(repo_path):
            logger.info(f"Cleaning up stale workspace: {repo_path}")
            try:
                shutil.rmtree(repo_path)
                return True
            except OSError as e:
                logger.warning(f"Failed to remove stale workspace: {e}")
                # Try to rename as fallback
                import time
                backup = f"{repo_path}.stale.{int(time.time())}"
                try:
                    os.rename(repo_path, backup)
                    logger.info(f"Renamed stale workspace to {backup}")
                    return True
                except OSError:
                    return False
        return False

    def _get_repo_id(self, repo_url: str) -> str:
        """Generates a safe directory name from a repo URL/name."""
        # Replace common separators with underscores
        safe_name = repo_url.replace("https://github.com/", "").replace("github.com:", "").replace("/", "_").replace(".git", "")
        return safe_name

    async def ensure_local_repo(self, repo_url: str, github_token: Optional[str] = None) -> str:
        """
        Ensures the repository exists locally. Returns the absolute path to the repo root.
        """
        repo_id = self._get_repo_id(repo_url)
        repo_path = os.path.join(self.base_path, repo_id)
        
        # Check if we are running in a container
        in_container = os.path.exists("/.dockerenv")
        env_context = "Container" if in_container else "Host"
        
        # If it's already a full path that exists, return it (support for local dev)
        if os.path.isabs(repo_url) and os.path.exists(repo_url):
            logger.info(f"Using existing absolute path: {repo_url}")
            return repo_url

        if os.path.exists(repo_path) and os.path.isdir(repo_path):
            # Check if it's a valid git repo or stale
            if os.path.exists(os.path.join(repo_path, ".git")):
                if not self._is_stale_workspace(repo_path):
                    logger.info(f"[{env_context}] Repository {repo_id} exists. Performing git pull for latest changes...")
                    pull_process = await asyncio.create_subprocess_exec(
                        "git", "-C", repo_path, "pull",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await pull_process.communicate()
                    return repo_path
            
            # If we get here, workspace is stale/incomplete - clean it
            self._ensure_workspace_clean(repo_path)

        # Handle shorthand like "org/repo"
        if "/" in repo_url and not repo_url.startswith("http") and not repo_url.startswith("git@"):
            full_url = f"https://github.com/{repo_url}.git"
        else:
            full_url = repo_url

        # Inject token if provided (and not the literal string "None")
        if github_token and str(github_token).lower() != "none" and "https://" in full_url:
            # Architect's note: Using x-access-token for GitHub App/PAT compatibility
            token_prefix = f"https://x-access-token:{github_token}@"
            full_url = full_url.replace("https://", token_prefix)

        logger.info(f"[{env_context}] Cloning {repo_url} into {repo_path}...")
        
        # Ensure parent exists
        os.makedirs(self.base_path, exist_ok=True)
        
        # If directory exists but is empty or broken, remove it first to avoid git clone conflicts
        if os.path.exists(repo_path):
            logger.warning(f"[{env_context}] Cleaning up existing/broken directory at {repo_path} before clone.")
            try:
                shutil.rmtree(repo_path)
            except OSError as e:
                logger.warning(f"[{env_context}] Failed to remove directory {repo_path}: {e}")
                # Try to rename it as a fallback (e.g., if directory is held by another process)
                import time
                backup_path = repo_path + f".old.{int(time.time())}"
                try:
                    os.rename(repo_path, backup_path)
                    logger.info(f"[{env_context}] Renamed existing dir to {backup_path}")
                except OSError:
                    pass

        # Removed --depth 1 to avoid "invalid index-pack output" on some environments
        process = await asyncio.create_subprocess_exec(
            "git", "clone", full_url, repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            retryable = "already exists" in error_msg or "refs" in error_msg
            
            if retryable:
                logger.warning(f"[{env_context}] Git clone collision or refs error. Force purging {repo_path} and retrying...")
                if os.path.exists(repo_path):
                    shutil.rmtree(repo_path)
                # Second attempt
                process = await asyncio.create_subprocess_exec(
                    "git", "clone", full_url, repo_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode == 0:
                    return repo_path
                error_msg = stderr.decode().strip()

            logger.error(f"[{env_context}] Failed to clone repository: {error_msg}")
            raise Exception(f"Git clone failed: {error_msg}")

        return repo_path

    def cleanup(self, repo_url: str):
        """Removes the local workspace for a repository."""
        repo_id = self._get_repo_id(repo_url)
        repo_path = os.path.join(self.base_path, repo_id)
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
