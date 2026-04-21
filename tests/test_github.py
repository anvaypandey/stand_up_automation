from unittest.mock import patch
from tests.helpers import mock_response
from collectors.github import fetch_github_activity

REPO_URL = "https://api.github.com/repos/org/myrepo"


def _pr(title, state, merged_at=None, pr_number=1):
    return {
        "title": title,
        "html_url": f"https://github.com/org/myrepo/pull/{pr_number}",
        "state": state,
        "repository_url": REPO_URL,
        "pull_request": {"merged_at": merged_at},
    }


def test_merged_pr_classified_correctly():
    items = [_pr("Fix bug", "closed", merged_at="2026-04-21T10:00:00Z")]
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": items}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert len(result["merged_prs"]) == 1
    assert result["merged_prs"][0]["title"] == "Fix bug"
    assert result["open_prs"] == []


def test_merged_pr_has_no_state_field():
    items = [_pr("Fix bug", "closed", merged_at="2026-04-21T10:00:00Z")]
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": items}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert "state" not in result["merged_prs"][0]


def test_closed_without_merge_is_excluded():
    items = [_pr("Abandoned PR", "closed", merged_at=None)]
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": items}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert result["merged_prs"] == []
    assert result["open_prs"] == []


def test_open_pr_classified_correctly():
    items = [_pr("WIP feature", "open", merged_at=None, pr_number=2)]
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": items}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert len(result["open_prs"]) == 1
    assert result["open_prs"][0]["title"] == "WIP feature"


def test_review_activity_collected():
    review_item = {
        "title": "Review this PR",
        "html_url": "https://github.com/org/myrepo/pull/3",
        "repository_url": REPO_URL,
        "state": "open",
        "pull_request": {"merged_at": None},
    }
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": []}),
        mock_response({"items": [review_item]}),
    ]):
        result = fetch_github_activity("token", "user")
    assert len(result["reviews"]) == 1
    assert result["reviews"][0]["title"] == "Review this PR"


def test_api_failure_returns_empty_dict():
    with patch("collectors.github.requests.get", return_value=mock_response({}, ok=False)):
        result = fetch_github_activity("token", "user")
    assert result == {"merged_prs": [], "open_prs": [], "reviews": []}


def test_no_commits_key_in_result():
    with patch("collectors.github.requests.get", return_value=mock_response({"items": []})):
        result = fetch_github_activity("token", "user")
    assert "commits" not in result


# --- adversarial ---

def test_pr_without_pull_request_key_open_state_classified():
    """'pull_request' key absent entirely — get('pull_request', {}) must not crash."""
    item = {
        "title": "No PR metadata",
        "html_url": "https://github.com/org/myrepo/pull/99",
        "state": "open",
        "repository_url": REPO_URL,
    }
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": [item]}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert result["open_prs"][0]["title"] == "No PR metadata"
    assert result["merged_prs"] == []


def test_first_request_failure_still_collects_reviews():
    """401 on the authored-PRs query must not abort the reviews query."""
    review_item = {
        "title": "Reviewed PR",
        "html_url": "https://github.com/org/myrepo/pull/7",
        "repository_url": REPO_URL,
    }
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({}, ok=False, status_code=401),
        mock_response({"items": [review_item]}),
    ]):
        result = fetch_github_activity("token", "user")
    assert result["merged_prs"] == []
    assert len(result["reviews"]) == 1


def test_repo_name_extracted_correctly():
    items = [_pr("PR", "open", pr_number=5)]
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": items}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert result["open_prs"][0]["repo"] == "myrepo"


def test_empty_string_merged_at_not_classified_as_merged():
    """merged_at='' is falsy — must land in neither merged_prs nor open_prs."""
    items = [_pr("Weird PR", "closed", merged_at="")]
    with patch("collectors.github.requests.get", side_effect=[
        mock_response({"items": items}),
        mock_response({"items": []}),
    ]):
        result = fetch_github_activity("token", "user")
    assert result["merged_prs"] == []
    assert result["open_prs"] == []
