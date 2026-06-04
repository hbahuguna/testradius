import logging
import traceback
from fastapi import Depends, HTTPException, Header, status
from github import Github, Auth, GithubException
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

async def get_github_client(x_github_token: str = Header(None)) -> Github:
    """
    Dependency to extract the GitHub token from the request header 
    and initialize an authenticated PyGithub client.
    """
    if not x_github_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-GitHub-Token header missing. Please ensure your provider token is passed.",
        )
    auth = Auth.Token(x_github_token)
    return Github(auth=auth)

async def list_repositories(g: Github) -> List[Dict[str, Any]]:
    """Fetch repositories accessible to the authenticated user."""
    try:
        user = g.get_user()
        repos = []
        # PyGithub PaginatedList - iterate with counter for safety
        count = 0
        for repo in user.get_repos():
            if count >= 100:
                break
            repos.append({
                "id": repo.id,
                "name": repo.name,
                "full_name": repo.full_name,
                "private": repo.private,
                "html_url": repo.html_url,
                "description": repo.description,
            })
            count += 1
        return repos
    except GithubException as e:
        if e.status == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid GitHub token")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing repositories: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

async def get_pr_files(g: Github, full_repo_name: str, pr_number: int) -> List[str]:
    """Fetch the list of file paths modified in a specific PR."""
    try:
        repo = g.get_repo(full_repo_name)
        pr = repo.get_pull(pr_number)
        return [f.filename for f in pr.get_files()]
    except Exception as e:
        logger.error(f"Error fetching files for PR {pr_number} in {full_repo_name}: {e}")
        return []

async def list_pull_requests(g: Github, full_repo_name: str) -> List[Dict[str, Any]]:
    """Fetch open pull requests for a specific repository."""
    try:
        repo = g.get_repo(full_repo_name)
        pulls = []
        
        # AVOID slicing PaginatedList directly ([:20]) as it causes IndexError in some PyGithub versions
        # when the list is empty or smaller than the slice. Use a manual counter instead.
        pull_requests = repo.get_pulls(state='open')
        count = 0
        for pr in pull_requests:
            if count >= 20:
                break
            
            try:
                # Defensive access to nested attributes
                user_login = "unknown"
                if pr.user:
                    user_login = pr.user.login
                
                head_sha = "unknown"
                if pr.head:
                    head_sha = pr.head.sha
                
                pulls.append({
                    "id": pr.id,
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "html_url": pr.html_url,
                    "user": user_login,
                    "head_sha": head_sha,
                    "created_at": pr.created_at.isoformat() if pr.created_at else None,
                })
                count += 1
            except Exception as item_err:
                logger.warning(f"Skipping PR in {full_repo_name} due to unexpected structure: {item_err}")
                continue
                
        return pulls
    except GithubException as e:
        if e.status == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid GitHub token")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing PRs for {full_repo_name}: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal Error: {str(e)}")
