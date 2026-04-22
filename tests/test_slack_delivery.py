import pytest
from unittest.mock import patch
from tests.helpers import mock_response
from core.slack_delivery import post_standup_draft, finalize_draft, delete_message

DM_OPEN_OK = {"ok": True, "channel": {"id": "D123"}}
POST_OK = {"ok": True, "ts": "1234567890.000001"}


# ── post_standup_draft ────────────────────────────────────────────────────────

def test_post_standup_draft_returns_channel_and_ts():
    with patch("core.slack_delivery.requests.post", side_effect=[
        mock_response(DM_OPEN_OK),
        mock_response(POST_OK),
    ]):
        channel_id, ts = post_standup_draft("token", "standup text", "U123")
    assert channel_id == "D123"
    assert ts == "1234567890.000001"


def test_post_standup_draft_text_contains_standup():
    with patch("core.slack_delivery.requests.post") as mock_post:
        mock_post.side_effect = [mock_response(DM_OPEN_OK), mock_response(POST_OK)]
        post_standup_draft("token", "my standup content", "U123")
    _, kwargs = mock_post.call_args_list[1]
    assert "my standup content" in kwargs["json"]["text"]


def test_post_standup_draft_unfurl_links_disabled():
    with patch("core.slack_delivery.requests.post") as mock_post:
        mock_post.side_effect = [mock_response(DM_OPEN_OK), mock_response(POST_OK)]
        post_standup_draft("token", "text", "U123")
    _, kwargs = mock_post.call_args_list[1]
    assert kwargs["json"]["unfurl_links"] is False


def test_post_standup_draft_raises_on_dm_open_failure():
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": False, "error": "user_not_found"})):
        with pytest.raises(RuntimeError, match="Failed to open DM"):
            post_standup_draft("token", "text", "U123")


def test_post_standup_draft_raises_on_post_failure():
    with patch("core.slack_delivery.requests.post", side_effect=[
        mock_response(DM_OPEN_OK),
        mock_response({"ok": False, "error": "channel_not_found"}),
    ]):
        with pytest.raises(RuntimeError, match="Failed to post draft"):
            post_standup_draft("token", "text", "U123")


def test_post_standup_draft_dm_open_ok_but_no_channel_key_raises():
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": True})):
        with pytest.raises(RuntimeError, match="Failed to open DM"):
            post_standup_draft("token", "text", "U123")


# ── finalize_draft ────────────────────────────────────────────────────────────

def test_finalize_draft_calls_chat_update():
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": True})) as mock_post:
        finalize_draft("token", "D123", "123.456", "standup text")
    url = mock_post.call_args.args[0]
    assert "chat.update" in url


def test_finalize_draft_text_contains_standup():
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": True})) as mock_post:
        finalize_draft("token", "D123", "123.456", "final standup")
    assert "final standup" in mock_post.call_args.kwargs["json"]["text"]


def test_finalize_draft_logs_warning_on_failure(caplog):
    import logging
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": False, "error": "message_not_found"})):
        with caplog.at_level(logging.WARNING, logger="core.slack_delivery"):
            finalize_draft("token", "D123", "123.456", "text")
    assert "Failed to finalize draft" in caplog.text
    assert "message_not_found" in caplog.text


# ── delete_message ────────────────────────────────────────────────────────────

def test_delete_message_calls_chat_delete():
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": True})) as mock_post:
        delete_message("token", "D123", "123.456")
    url = mock_post.call_args.args[0]
    assert "chat.delete" in url


def test_delete_message_logs_warning_on_failure(caplog):
    import logging
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": False, "error": "cant_delete_message"})):
        with caplog.at_level(logging.WARNING, logger="core.slack_delivery"):
            delete_message("token", "D123", "123.456")
    assert "Failed to delete message" in caplog.text
    assert "cant_delete_message" in caplog.text
