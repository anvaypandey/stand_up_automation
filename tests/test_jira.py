from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from tests.helpers import mock_response
from collectors.jira import fetch_jira_activity, extract_comment_text

BASE_URL = "https://company.atlassian.net"


# --- extract_comment_text ---

def test_extract_plain_string():
    assert extract_comment_text("plain comment") == "plain comment"


def test_extract_adf_body():
    body = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "ADF "},
                {"type": "text", "text": "comment"},
            ]}
        ],
    }
    assert extract_comment_text(body) == "ADF comment"


def test_extract_unknown_type_returns_empty():
    assert extract_comment_text(42) == ""
    assert extract_comment_text(None) == ""


def test_extract_truncates_at_100():
    assert len(extract_comment_text("x" * 200)) == 100


# --- fetch_jira_activity ---

def _issue(key, status_key, comment_updated=None, comment_body="a comment"):
    comments = []
    if comment_updated:
        comments = [{"updated": comment_updated, "body": comment_body}]
    return {
        "key": key,
        "fields": {
            "summary": f"Summary of {key}",
            "status": {"statusCategory": {"key": status_key}},
            "comment": {"comments": comments},
        },
    }


def test_done_issue_classified():
    issues = [_issue("ENG-1", "done")]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert len(result["done"]) == 1
    assert result["done"][0]["key"] == "ENG-1"
    assert result["in_progress"] == []


def test_in_progress_issue_classified():
    issues = [_issue("ENG-2", "indeterminate")]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert len(result["in_progress"]) == 1


def test_todo_issue_classified():
    issues = [_issue("ENG-3", "new")]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert len(result["todo"]) == 1


def test_recent_comment_included():
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    issues = [_issue("ENG-4", "done", comment_updated=recent)]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert len(result["commented"]) == 1


def test_adf_comment_body_extracted_via_pipeline():
    adf_body = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "ADF preview text"}]}],
    }
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    issues = [_issue("ENG-6", "done", comment_updated=recent, comment_body=adf_body)]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert result["commented"][0]["comment_preview"] == "ADF preview text"


def test_old_comment_excluded():
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    issues = [_issue("ENG-5", "done", comment_updated=old)]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert result["commented"] == []


def test_api_failure_returns_empty():
    with patch("collectors.jira.requests.get", return_value=mock_response({}, ok=False)):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert result == {"done": [], "in_progress": [], "todo": [], "commented": []}


def test_issue_url_constructed_correctly():
    issues = [_issue("ENG-99", "done")]
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": issues})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert result["done"][0]["url"] == f"{BASE_URL}/browse/ENG-99"


# --- adversarial ---

def test_comment_missing_body_key_does_not_crash():
    """c['body'] is a hard key lookup; KeyError is NOT in the except clause. BUG."""
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    issue = {
        "key": "ENG-20",
        "fields": {
            "summary": "Missing body",
            "status": {"statusCategory": {"key": "done"}},
            "comment": {"comments": [{"updated": recent}]},  # no "body" key
        },
    }
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": [issue]})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert isinstance(result["commented"], list)


def test_issue_missing_fields_key_does_not_crash():
    """issue['fields'] is a hard lookup with no surrounding try/except. BUG."""
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": [{"key": "ENG-21"}]})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert result["done"] == []


def test_status_category_missing_does_not_crash():
    """fields['status']['statusCategory']['key'] — any level absent → KeyError. BUG."""
    issue = {
        "key": "ENG-22",
        "fields": {
            "summary": "Bad status",
            "status": {},  # no statusCategory
            "comment": {"comments": []},
        },
    }
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": [issue]})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert result["done"] == []


def test_only_first_recent_comment_per_issue_recorded():
    """Two recent comments on one issue — break means only one entry in commented."""
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    issue = {
        "key": "ENG-23",
        "fields": {
            "summary": "Multi-comment",
            "status": {"statusCategory": {"key": "done"}},
            "comment": {"comments": [
                {"updated": recent, "body": "first"},
                {"updated": recent, "body": "second"},
            ]},
        },
    }
    with patch("collectors.jira.requests.get", return_value=mock_response({"issues": [issue]})):
        result = fetch_jira_activity(BASE_URL, "user@co.com", "token")
    assert len(result["commented"]) == 1


def test_adf_block_without_inner_content_key_returns_empty():
    """ADF block missing inner 'content' — must return '' not crash."""
    body = {"type": "doc", "content": [{"type": "paragraph"}]}  # no inner "content"
    assert extract_comment_text(body) == ""


def test_extract_adf_long_multinode_text_truncated():
    """ADF nodes that together exceed 100 chars must be truncated."""
    node = {"type": "text", "text": "x" * 60}
    body = {"type": "doc", "content": [{"type": "paragraph", "content": [node, node]}]}
    assert len(extract_comment_text(body)) == 100
