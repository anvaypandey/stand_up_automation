from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from tests.helpers import mock_response
from collectors.notion import fetch_notion_activity

MY_ID = "notion-user-me"


def _page(title, edited_by_id, hours_ago=1, use_z_suffix=False):
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    if use_z_suffix:
        edited_at = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        edited_at = dt.isoformat()
    return {
        "last_edited_time": edited_at,
        "last_edited_by": {"id": edited_by_id},
        "url": "https://notion.so/page-1",
        "properties": {
            "Title": {"type": "title", "title": [{"plain_text": title}]}
        },
    }


def test_includes_pages_edited_by_current_user():
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [_page("My Page", MY_ID)]})):
        result = fetch_notion_activity("token")
    assert len(result["edited_pages"]) == 1
    assert result["edited_pages"][0]["title"] == "My Page"


def test_excludes_pages_edited_by_teammates():
    pages = [
        _page("My Page", MY_ID),
        _page("Their Page", "someone-else"),
    ]
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": pages})):
        result = fetch_notion_activity("token")
    assert len(result["edited_pages"]) == 1
    assert result["edited_pages"][0]["title"] == "My Page"


def test_excludes_pages_older_than_cutoff():
    old_page = _page("Old Page", MY_ID, hours_ago=48)
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [old_page]})):
        result = fetch_notion_activity("token")
    assert result["edited_pages"] == []


def test_handles_z_suffix_timestamps():
    """Notion API returns Z-suffixed timestamps; fromisoformat normalisation must work."""
    page = _page("Z Page", MY_ID, use_z_suffix=True)
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [page]})):
        result = fetch_notion_activity("token")
    assert len(result["edited_pages"]) == 1
    assert result["edited_pages"][0]["title"] == "Z Page"


def test_last_edited_is_date_string():
    """last_edited in output must be YYYY-MM-DD, not a raw datetime string."""
    page = _page("My Page", MY_ID)
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [page]})):
        result = fetch_notion_activity("token")
    last_edited = result["edited_pages"][0]["last_edited"]
    assert len(last_edited) == 10
    assert last_edited.count("-") == 2


def test_unknown_user_id_includes_all_recent_pages():
    """When /users/me fails, my_id is empty and the user filter is skipped."""
    pages = [_page("Any Page", "whoever")]
    with patch("collectors.notion.requests.get", return_value=mock_response({}, ok=False)), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": pages})):
        result = fetch_notion_activity("token")
    assert len(result["edited_pages"]) == 1


def test_search_api_failure_returns_empty():
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({}, ok=False)):
        result = fetch_notion_activity("token")
    assert result == {"edited_pages": []}


def test_untitled_page_fallback():
    page = _page("", MY_ID)
    page["properties"] = {}
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [page]})):
        result = fetch_notion_activity("token")
    assert result["edited_pages"][0]["title"] == "Untitled"


# --- adversarial ---

def test_page_without_last_edited_by_key_excluded_when_user_id_known():
    """last_edited_by key absent → last_edited_by_id=''. With my_id set,
    '' != my_id → page is silently filtered out. This is the current behaviour."""
    page = _page("My Page", MY_ID)
    del page["last_edited_by"]
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [page]})):
        result = fetch_notion_activity("token")
    assert result["edited_pages"] == []


def test_title_property_with_empty_parts_falls_back_to_untitled():
    """title property exists but parts=[] — 'if parts:' must keep 'Untitled'."""
    page = _page("", MY_ID)
    page["properties"]["Title"]["title"] = []
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [page]})):
        result = fetch_notion_activity("token")
    assert result["edited_pages"][0]["title"] == "Untitled"


def test_multi_part_title_concatenated():
    """Title with two plain_text parts must be joined, not just first part used."""
    page = _page("ignored", MY_ID)
    page["properties"]["Title"]["title"] = [
        {"plain_text": "Part One "},
        {"plain_text": "Part Two"},
    ]
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [page]})):
        result = fetch_notion_activity("token")
    assert result["edited_pages"][0]["title"] == "Part One Part Two"


def test_invalid_timestamp_page_skipped_without_crash():
    """Garbage last_edited_time must be caught and page silently skipped."""
    page = _page("Valid Page", MY_ID)
    bad_page = {**page, "last_edited_time": "not-a-date", "properties": {"Title": {"type": "title", "title": [{"plain_text": "Bad"}]}}}
    with patch("collectors.notion.requests.get", return_value=mock_response({"id": MY_ID})), \
         patch("collectors.notion.requests.post", return_value=mock_response({"results": [bad_page, page]})):
        result = fetch_notion_activity("token")
    assert len(result["edited_pages"]) == 1
    assert result["edited_pages"][0]["title"] != "Bad"
