"""Custom exceptions for buildbot-pr-check."""


class CheckError(Exception):
    """Base exception for buildbot-pr-check errors."""


class InvalidPRURLError(CheckError):
    """Raised when PR URL is invalid or unsupported."""


class APIError(CheckError):
    """Raised when API calls fail."""


class NixbotAPIError(APIError):
    """Raised when Nixbot API calls fail."""


class GitHubAPIError(APIError):
    """Raised when GitHub API calls fail."""


class GiteaAPIError(APIError):
    """Raised when Gitea API calls fail."""
