import json
from unittest.mock import MagicMock, patch

from build_tools.generate_changelog import (
    parse_existing_changelog,
    kolibri_version_key,
    is_prerelease,
    format_changelog_entry,
    github_timestamp_to_debian,
    fetch_github_releases,
    filter_new_releases,
    generate_release_entries,
)

SAMPLE_CHANGELOG = """\
kolibri-source (0.19.1-0ubuntu1) noble; urgency=medium

  * New upstream release

 -- Learning Equality \\(Learning Equality\\'s public signing key\\) <accounts@learningequality.org>>  Tue, 20 Jan 2026 13:55:06 -0800

kolibri-source (0.19.0-0ubuntu1) noble; urgency=medium

  * New upstream release

 -- Learning Equality \\(Learning Equality\\'s public signing key\\) <accounts@learningequality.org>>  Wed, 10 Dec 2025 16:26:58 -0800
"""


def test_parse_existing_changelog_returns_latest_version():
    latest_version, latest_revision, existing_content = parse_existing_changelog(SAMPLE_CHANGELOG)
    assert latest_version == "0.19.1"
    assert latest_revision == 1


def test_parse_existing_changelog_preserves_content():
    latest_version, latest_revision, existing_content = parse_existing_changelog(SAMPLE_CHANGELOG)
    assert existing_content == SAMPLE_CHANGELOG


def test_version_ordering_basic():
    versions = ["0.17.0", "0.19.1", "0.18.0", "0.19.0"]
    assert sorted(versions, key=kolibri_version_key) == [
        "0.17.0", "0.18.0", "0.19.0", "0.19.1"
    ]


def test_version_ordering_with_prerelease():
    versions = ["0.19.1", "0.19.2-alpha0", "0.19.1-rc0", "0.19.0"]
    assert sorted(versions, key=kolibri_version_key) == [
        "0.19.0", "0.19.1-rc0", "0.19.1", "0.19.2-alpha0"
    ]


def test_is_prerelease():
    assert is_prerelease("0.19.2-alpha0") is True
    assert is_prerelease("0.19.1-rc0") is True
    assert is_prerelease("0.19.1-beta1") is True
    assert is_prerelease("0.19.1") is False
    assert is_prerelease("0.19.0") is False


def test_version_newer_than():
    assert kolibri_version_key("0.19.2") > kolibri_version_key("0.19.1")
    assert kolibri_version_key("0.19.1-rc0") < kolibri_version_key("0.19.1")


def test_format_changelog_entry():
    entry = format_changelog_entry(
        version="0.19.2",
        ubuntu_revision=1,
        distribution="noble",
        message="New upstream release",
        maintainer="Learning Equality \\(Learning Equality\\'s public signing key\\) <accounts@learningequality.org>>",
        timestamp="Thu, 31 Oct 2025 16:09:14 +0100",
    )
    expected = """\
kolibri-source (0.19.2-0ubuntu1) noble; urgency=medium

  * New upstream release

 -- Learning Equality \\(Learning Equality\\'s public signing key\\) <accounts@learningequality.org>>  Thu, 31 Oct 2025 16:09:14 +0100
"""
    assert entry == expected


def test_format_changelog_entry_prerelease():
    """Prerelease versions use ~ in Debian version string."""
    entry = format_changelog_entry(
        version="0.19.2-alpha0",
        ubuntu_revision=1,
        distribution="noble",
        message="New upstream release",
        maintainer="Learning Equality \\(Learning Equality\\'s public signing key\\) <accounts@learningequality.org>>",
        timestamp="Thu, 06 Feb 2026 19:46:25 +0000",
    )
    assert "kolibri-source (0.19.2~alpha0-0ubuntu1)" in entry


def test_github_timestamp_to_debian():
    result = github_timestamp_to_debian("2026-01-20T16:54:38Z")
    assert result == "Tue, 20 Jan 2026 16:54:38 +0000"


def test_github_timestamp_to_debian_another():
    result = github_timestamp_to_debian("2025-10-31T15:09:14Z")
    assert result == "Fri, 31 Oct 2025 15:09:14 +0000"


def _mock_urlopen_pages(pages):
    """Create a mock for urllib that returns paginated results.

    pages: list of (response_body, next_link_or_none)
    """
    responses = []
    for body, next_link in pages:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(body).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        if next_link:
            mock_response.headers = {"Link": f'<{next_link}>; rel="next"'}
        else:
            mock_response.headers = {}
        responses.append(mock_response)
    return responses


def test_fetch_github_releases_single_page():
    releases = [
        {"tag_name": "v0.19.1", "prerelease": False, "published_at": "2026-01-20T16:54:38Z"},
        {"tag_name": "v0.19.0", "prerelease": False, "published_at": "2025-12-10T16:26:58Z"},
    ]
    mock_responses = _mock_urlopen_pages([(releases, None)])

    with patch("build_tools.generate_changelog.urlopen", side_effect=mock_responses):
        result = fetch_github_releases()

    assert len(result) == 2
    assert result[0]["tag_name"] == "v0.19.1"


def test_fetch_github_releases_pagination():
    page1 = [
        {"tag_name": "v0.19.1", "prerelease": False, "published_at": "2026-01-20T16:54:38Z"},
    ]
    page2 = [
        {"tag_name": "v0.19.0", "prerelease": False, "published_at": "2025-12-10T16:26:58Z"},
    ]
    mock_responses = _mock_urlopen_pages([
        (page1, "https://api.github.com/repos/learningequality/kolibri/releases?page=2"),
        (page2, None),
    ])

    with patch("build_tools.generate_changelog.urlopen", side_effect=mock_responses):
        result = fetch_github_releases()

    assert len(result) == 2
    assert result[0]["tag_name"] == "v0.19.1"
    assert result[1]["tag_name"] == "v0.19.0"


def test_filter_new_releases_excludes_old():
    releases = [
        {"tag_name": "v0.19.2", "prerelease": False, "published_at": "2026-02-06T19:46:25Z"},
        {"tag_name": "v0.19.1", "prerelease": False, "published_at": "2026-01-20T16:54:38Z"},
        {"tag_name": "v0.19.0", "prerelease": False, "published_at": "2025-12-10T16:26:58Z"},
    ]
    result = filter_new_releases(releases, latest_existing="0.19.1", build_version="0.19.2")
    assert len(result) == 1
    assert result[0]["tag_name"] == "v0.19.2"


def test_filter_new_releases_excludes_prereleases():
    releases = [
        {"tag_name": "v0.19.2", "prerelease": False, "published_at": "2026-02-06T19:46:25Z"},
        {"tag_name": "v0.19.2-rc0", "prerelease": True, "published_at": "2026-02-01T10:00:00Z"},
        {"tag_name": "v0.19.1", "prerelease": False, "published_at": "2026-01-20T16:54:38Z"},
    ]
    result = filter_new_releases(releases, latest_existing="0.19.1", build_version="0.19.2")
    assert len(result) == 1
    assert result[0]["tag_name"] == "v0.19.2"


def test_filter_new_releases_includes_current_prerelease():
    """If build version is itself a prerelease, include it."""
    releases = [
        {"tag_name": "0.19.2-alpha0", "prerelease": True, "published_at": "2026-02-06T19:46:25Z"},
        {"tag_name": "v0.19.1", "prerelease": False, "published_at": "2026-01-20T16:54:38Z"},
    ]
    result = filter_new_releases(releases, latest_existing="0.19.1", build_version="0.19.2-alpha0")
    assert len(result) == 1
    assert result[0]["tag_name"] == "0.19.2-alpha0"


def test_filter_new_releases_strips_v_prefix():
    releases = [
        {"tag_name": "v0.19.2", "prerelease": False, "published_at": "2026-02-06T19:46:25Z"},
    ]
    result = filter_new_releases(releases, latest_existing="0.19.1", build_version="0.19.2")
    assert len(result) == 1


def test_generate_release_entries():
    releases = [
        {"tag_name": "v0.19.2", "prerelease": False, "published_at": "2025-10-31T15:09:14Z"},
        {"tag_name": "v0.19.1", "prerelease": False, "published_at": "2025-10-03T17:47:04Z"},
    ]
    with patch("build_tools.generate_changelog.get_current_lts_codename", return_value="noble"):
        entries = generate_release_entries(releases)

    assert len(entries) == 2
    assert "0.19.2-0ubuntu1" in entries[0]["text"]
    assert "0.19.1-0ubuntu1" in entries[1]["text"]
    assert "noble" in entries[0]["text"]
    assert entries[0]["version"] == "0.19.2"
    assert entries[0]["ubuntu_revision"] == 1
