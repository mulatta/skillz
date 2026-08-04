"""buildbot-pr-check - Inspect Nixbot CI for a PR."""

from .cli import main
from .exceptions import (
    APIError,
    CheckError,
    GiteaAPIError,
    GitHubAPIError,
    InvalidPRURLError,
    NixbotAPIError,
)

__version__ = "0.2.0"

__all__ = [
    "APIError",
    "CheckError",
    "GitHubAPIError",
    "GiteaAPIError",
    "InvalidPRURLError",
    "NixbotAPIError",
    "main",
]
