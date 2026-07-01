"""URL parsing for PR URLs and nixbot web URLs."""

import re
import urllib.parse
from dataclasses import dataclass

from .exceptions import InvalidPRURLError


@dataclass
class PRInfo:
    platform: str  # "github" | "gitea"
    host: str  # forge hostname
    owner: str
    repo: str
    pr_num: str


@dataclass
class NixbotRef:
    """Reference into a nixbot instance parsed from a web URL."""

    base_url: str  # https://host
    forge: str
    owner: str
    repo: str
    build_num: int


def is_safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme == "https" and bool(parsed.netloc)
    except (ValueError, AttributeError):
        return False


def is_nixbot_build_url(url: str) -> bool:
    try:
        parse_nixbot_url(url)
    except InvalidPRURLError:
        return False
    return True


def get_pr_info(pr_url: str) -> PRInfo:
    """Extract platform/host/owner/repo/pr_num from a GitHub or Gitea PR URL."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if m:
        return PRInfo("github", "github.com", m.group(1), m.group(2), m.group(3))

    m = re.match(r"https://([^/]+)/([^/]+)/([^/]+)/pulls/(\d+)", pr_url)
    if m:
        return PRInfo("gitea", m.group(1), m.group(2), m.group(3), m.group(4))

    raise InvalidPRURLError(f"Invalid PR URL: {pr_url}. Supported: GitHub and Gitea")


def parse_nixbot_url(url: str) -> NixbotRef:
    """Parse ``https://ci/repos/<forge>/<owner>/<repo>/builds/<n>``."""
    p = urllib.parse.urlparse(url)
    if not p.scheme or not p.netloc:
        raise InvalidPRURLError(f"Not a nixbot URL: {url}")
    m = re.search(r"/repos/([^/]+)/([^/]+)/([^/]+)/builds/(\d+)", p.path)
    if not m:
        raise InvalidPRURLError(f"Not a nixbot build URL: {url}")
    return NixbotRef(
        base_url=f"{p.scheme}://{p.netloc}",
        forge=m.group(1),
        owner=m.group(2),
        repo=m.group(3),
        build_num=int(m.group(4)),
    )
