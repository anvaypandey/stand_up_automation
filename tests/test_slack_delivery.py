import pytest
from unittest.mock import patch
from tests.helpers import mock_response
from core.slack_delivery import post_to_slack_dm

DM_OPEN_OK = {"ok": True, "channel": {"id": "D123"}}
POST_OK = {"ok": True}


def test_does_not_call_auth_test_when_user_id_provided():
    with patch("core.slack_delivery.requests.get") as mock_get, \
         patch("core.slack_delivery.requests.post", side_effect=[
             mock_response(DM_OPEN_OK),
             mock_response(POST_OK),
         ]):
        post_to_slack_dm("token", "standup text", user_id="U123")
    mock_get.assert_not_called()


def test_calls_auth_test_when_user_id_absent():
    with patch("core.slack_delivery.requests.get", return_value=mock_response({"ok": True, "user_id": "U456"})) as mock_get, \
         patch("core.slack_delivery.requests.post", side_effect=[
             mock_response(DM_OPEN_OK),
             mock_response(POST_OK),
         ]):
        post_to_slack_dm("token", "standup text")
    mock_get.assert_called_once()
    assert "auth.test" in mock_get.call_args.args[0]


def test_raises_when_auth_test_cannot_resolve_user():
    with patch("core.slack_delivery.requests.get", return_value=mock_response({"ok": False})):
        with pytest.raises(ValueError, match="Could not determine Slack user ID"):
            post_to_slack_dm("token", "standup text")


def test_raises_when_dm_open_fails():
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": False, "error": "user_not_found"})):
        with pytest.raises(RuntimeError, match="Failed to open DM"):
            post_to_slack_dm("token", "standup text", user_id="U123")


def test_raises_when_message_post_fails():
    with patch("core.slack_delivery.requests.post", side_effect=[
        mock_response(DM_OPEN_OK),
        mock_response({"ok": False, "error": "channel_not_found"}),
    ]):
        with pytest.raises(RuntimeError, match="Failed to post message"):
            post_to_slack_dm("token", "standup text", user_id="U123")


def test_standup_text_appears_in_posted_message():
    with patch("core.slack_delivery.requests.post") as mock_post:
        mock_post.side_effect = [mock_response(DM_OPEN_OK), mock_response(POST_OK)]
        post_to_slack_dm("token", "my standup content", user_id="U123")

    _, kwargs = mock_post.call_args_list[1]
    assert "my standup content" in kwargs["json"]["text"]


def test_returns_none():
    with patch("core.slack_delivery.requests.post", side_effect=[
        mock_response(DM_OPEN_OK),
        mock_response(POST_OK),
    ]):
        result = post_to_slack_dm("token", "text", user_id="U123")
    assert result is None


# --- adversarial ---

def test_dm_open_ok_true_but_no_channel_key_raises_runtime_error():
    """conversations.open ok=True but 'channel' key absent — dm_data['channel']['id']
    is a hard lookup. Currently raises KeyError instead of RuntimeError. BUG."""
    with patch("core.slack_delivery.requests.post", return_value=mock_response({"ok": True})):
        with pytest.raises(RuntimeError, match="Failed to open DM"):
            post_to_slack_dm("token", "text", user_id="U123")


def test_message_post_http_failure_includes_status_code():
    """When chat.postMessage HTTP fails (ok=False, no 'error' key), status code shown."""
    with patch("core.slack_delivery.requests.post", side_effect=[
        mock_response(DM_OPEN_OK),
        mock_response({}, ok=False, status_code=503),
    ]):
        with pytest.raises(RuntimeError, match="503"):
            post_to_slack_dm("token", "text", user_id="U123")


def test_unfurl_links_disabled_in_posted_message():
    """unfurl_links must be False to prevent Slack from expanding URLs in the standup."""
    with patch("core.slack_delivery.requests.post") as mock_post:
        mock_post.side_effect = [mock_response(DM_OPEN_OK), mock_response(POST_OK)]
        post_to_slack_dm("token", "text", user_id="U123")
    _, kwargs = mock_post.call_args_list[1]
    assert kwargs["json"]["unfurl_links"] is False
