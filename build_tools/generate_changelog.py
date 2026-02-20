#!/usr/bin/env python3
"""Generate updated debian/changelog from GitHub releases and packaging CHANGELOG."""

import json
import re
from datetime import datetime
from email.utils import format_datetime
from urllib.request import urlopen, Request

from packaging.version import Version

GITHUB_API_URL = "https://api.github.com/repos/learningequality/kolibri/releases"


# Regex to match the first line of a Debian changelog entry
# e.g.: kolibri-source (0.19.1-0ubuntu1) noble; urgency=medium
CHANGELOG_HEADER_RE = re.compile(
    r"^(\S+)\s+\(([^)]+)\)\s+(\S+);\s+urgency=(\S+)"
)


def parse_debian_version(debian_version):
    """Extract upstream version from a Debian version string.

    '0.19.1-0ubuntu1' -> '0.19.1'
    '0.16.0~rc0-0ubuntu1' -> '0.16.0~rc0'
    """
    if "-" in debian_version:
        return debian_version.rsplit("-", 1)[0]
    return debian_version


def parse_existing_changelog(content):
    """Parse existing debian/changelog content.

    Returns (latest_upstream_version, latest_ubuntu_revision, full_content).
    """
    for line in content.splitlines():
        match = CHANGELOG_HEADER_RE.match(line)
        if match:
            debian_version = match.group(2)
            upstream_version = parse_debian_version(debian_version)
            # Convert ~ back to - for Kolibri version format
            upstream_version = upstream_version.replace("~", "-")
            revision_match = re.search(r"-0ubuntu(\d+)", debian_version)
            ubuntu_revision = int(revision_match.group(1)) if revision_match else 1
            return upstream_version, ubuntu_revision, content
    return None, 0, content


def normalize_version(version_str):
    """Normalize a Kolibri version string for packaging.version.Version.

    Converts hyphenated prerelease tags to PEP 440 format.
    '0.19.2-alpha0' -> '0.19.2a0', '0.19.1-rc0' -> '0.19.1rc0'
    """
    version_str = re.sub(r"-alpha(\d+)", r"a\1", version_str)
    version_str = re.sub(r"-beta(\d+)", r"b\1", version_str)
    version_str = re.sub(r"-rc(\d+)", r"rc\1", version_str)
    return version_str


def kolibri_version_key(version_str):
    """Return a sort key for a Kolibri version string."""
    return Version(normalize_version(version_str))


def is_prerelease(version_str):
    """Check if a Kolibri version string is a prerelease."""
    return Version(normalize_version(version_str)).is_prerelease


PACKAGE_NAME = "kolibri-source"
MAINTAINER = (
    "Learning Equality \\(Learning Equality\\'s public signing key\\) "
    "<accounts@learningequality.org>>"
)


def version_to_debian(version_str):
    """Convert a Kolibri version to Debian version format.

    Prerelease separators become ~ (sorts before release in dpkg).
    '0.19.1' -> '0.19.1'
    '0.19.2-alpha0' -> '0.19.2~alpha0'
    """
    result = re.sub(r"-(alpha|beta|rc)", r"~\1", version_str)
    result = re.sub(r"\.dev", r"~dev", result)
    return result


def format_changelog_entry(version, ubuntu_revision, distribution, message,
                           maintainer, timestamp):
    """Format a single Debian changelog entry."""
    deb_version = version_to_debian(version)
    return (
        f"{PACKAGE_NAME} ({deb_version}-0ubuntu{ubuntu_revision}) "
        f"{distribution}; urgency=medium\n"
        f"\n"
        f"  * {message}\n"
        f"\n"
        f" -- {maintainer}  {timestamp}\n"
    )


def github_timestamp_to_debian(iso_timestamp):
    """Convert ISO 8601 timestamp to Debian changelog format.

    '2026-01-20T16:54:38Z' -> 'Tue, 20 Jan 2026 16:54:38 +0000'
    """
    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return format_datetime(dt, usegmt=False)


def _parse_link_header(headers):
    """Parse GitHub Link header to find next page URL."""
    link = headers.get("Link", "")
    for part in link.split(","):
        if 'rel="next"' in part:
            url = part.split(";")[0].strip().strip("<>")
            return url
    return None


def fetch_github_releases():
    """Fetch all Kolibri releases from GitHub API, handling pagination."""
    all_releases = []
    url = GITHUB_API_URL + "?per_page=100"

    while url:
        req = Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urlopen(req) as response:
            data = json.loads(response.read())
            all_releases.extend(data)
            url = _parse_link_header(response.headers)

    return all_releases


def strip_v_prefix(tag_name):
    """Strip leading 'v' from a tag name."""
    return tag_name.lstrip("v")


def filter_new_releases(releases, latest_existing, build_version):
    """Filter GitHub releases to only those newer than latest_existing.

    - Excludes prereleases, UNLESS the release matches build_version
    - Excludes versions <= latest_existing
    - Returns filtered list sorted by version ascending
    """
    latest_key = kolibri_version_key(latest_existing)
    filtered = []

    for release in releases:
        version = strip_v_prefix(release["tag_name"])

        # Skip if not newer than latest existing
        if kolibri_version_key(version) <= latest_key:
            continue

        # Skip prereleases unless it's the current build version
        if release["prerelease"] and version != build_version:
            continue

        filtered.append(release)

    # Sort by version ascending (oldest first, so newest is prepended last)
    filtered.sort(key=lambda r: kolibri_version_key(strip_v_prefix(r["tag_name"])))
    return filtered


def get_current_lts_codename():
    """Get the codename of the current Ubuntu LTS release using distro-info."""
    from distro_info import UbuntuDistroInfo
    ubuntu = UbuntuDistroInfo()
    return ubuntu.lts()


def generate_release_entries(releases):
    """Generate changelog entry dicts from GitHub release data.

    Returns list of dicts with keys: version, ubuntu_revision, text
    """
    distribution = get_current_lts_codename()
    entries = []

    for release in releases:
        version = strip_v_prefix(release["tag_name"])
        timestamp = github_timestamp_to_debian(release["published_at"])
        text = format_changelog_entry(
            version=version,
            ubuntu_revision=1,
            distribution=distribution,
            message="New upstream release",
            maintainer=MAINTAINER,
            timestamp=timestamp,
        )
        entries.append({
            "version": version,
            "ubuntu_revision": 1,
            "text": text,
        })

    return entries
