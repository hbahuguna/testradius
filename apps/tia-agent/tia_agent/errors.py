"""Errors raised by the tia-agent."""

from __future__ import annotations

from typing import Optional


class TiaError(Exception):
    """Base error with a user-facing message."""

    exit_code = 1


class ConfigError(TiaError):
    exit_code = 2


class LicenseError(TiaError):
    exit_code = 3

    def __init__(self, message: str, *, status: Optional[str] = None, renewal_url: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.renewal_url = renewal_url


class BackendError(TiaError):
    exit_code = 4
    """TestRadius backend is unreachable or returned an error."""


class AnalysisError(TiaError):
    exit_code = 5
    """Analysis could not be completed (e.g. no instrumentation evidence)."""


class GitError(TiaError):
    exit_code = 6


class BackendLaunchError(TiaError):
    exit_code = 8
    """The bundled backend could not be started (docker/compose failure)."""


class GitHubError(TiaError):
    exit_code = 9
    """A GitHub API request failed (network, not found, rate limit)."""


class GitHubAuthError(GitHubError):
    """GitHub rejected the token or one is required to access the resource."""

    def __init__(self, message: str, *, needs_token: bool = True):
        super().__init__(message)
        self.needs_token = needs_token