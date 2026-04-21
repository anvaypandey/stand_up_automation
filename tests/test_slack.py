from unittest.mock import patch
from tests.helpers import mock_response
from collectors.slack import fetch_slack_activity

CHANNELS = [{"id": "C1", "name": "engineering"}]
HISTORY_MINE = {"ok": True, "messages": [{"user": "U_ME", "text": "hello"}]}


def test_uses_provided_user_id_without_auth_test():
    """auth.test must NOT be called when caller already provides user_id."""
    with patch("collectors.slack.requests.get") as mock_get:
        mock_get.side_effect = [
            mock_response({"ok": True, "channels": CHANNELS}),
            mock_response(HISTORY_MINE),
        ]
        result = fetch_slack_activity("token", user_id="U_ME")

    urls = [c.args[0] for c in mock_get.call_args_list]
    assert not any("auth.test" in u for u in urls)
    assert len(result["messages_sent"]) == 1


def test_resolves_user_id_via_auth_test_when_not_provided():
    """auth.test must be called first when user_id is absent."""
    with patch("collectors.slack.requests.get") as mock_get:
        mock_get.side_effect = [
            mock_response({"ok": True, "user_id": "U_ME"}),     # auth.test
            mock_response({"ok": True, "channels": CHANNELS}),  # users.conversations
            mock_response(HISTORY_MINE),                        # conversations.history
        ]
        result = fetch_slack_activity("token")

    first_url = mock_get.call_args_list[0].args[0]
    assert "auth.test" in first_url
    assert len(result["messages_sent"]) == 1


def test_auth_test_failure_returns_empty():
    with patch("collectors.slack.requests.get", return_value=mock_response({"ok": False, "error": "invalid_auth"})):
        result = fetch_slack_activity("token")
    assert result == {"messages_sent": [], "mentions": [], "channels_active": []}


def test_conversations_failure_returns_empty():
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "user_id": "U_ME"}),
        mock_response({"ok": False, "error": "missing_scope"}),
    ]):
        result = fetch_slack_activity("token")
    assert result == {"messages_sent": [], "mentions": [], "channels_active": []}


def test_history_ok_false_skips_channel():
    """HTTP 200 with ok=False must be treated as failure for that channel."""
    with patch("collectors.slack.requests.get") as mock_get:
        mock_get.side_effect = [
            mock_response({"ok": True, "channels": CHANNELS}),
            mock_response({"ok": False, "error": "channel_not_found"}),
        ]
        result = fetch_slack_activity("token", user_id="U_ME")
    assert result["messages_sent"] == []


def test_ratelimited_stops_fetching():
    channels = [{"id": "C1", "name": "ch1"}, {"id": "C2", "name": "ch2"}]
    with patch("collectors.slack.requests.get") as mock_get:
        mock_get.side_effect = [
            mock_response({"ok": True, "channels": channels}),
            mock_response({"ok": False, "error": "ratelimited"}),
        ]
        fetch_slack_activity("token", user_id="U_ME")
    # Only one history call — loop broke after rate limit
    history_calls = [c for c in mock_get.call_args_list if "history" in c.args[0]]
    assert len(history_calls) == 1


def test_mention_detected():
    history = {"ok": True, "messages": [{"user": "U_OTHER", "text": "hey <@U_ME> check this"}]}
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "channels": CHANNELS}),
        mock_response(history),
    ]):
        result = fetch_slack_activity("token", user_id="U_ME")
    assert len(result["mentions"]) == 1
    assert result["mentions"][0]["from_user"] == "U_OTHER"


def test_active_channel_recorded():
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "channels": CHANNELS}),
        mock_response(HISTORY_MINE),
    ]):
        result = fetch_slack_activity("token", user_id="U_ME")
    assert "engineering" in result["channels_active"]


# --- adversarial ---

def test_channel_without_name_key_falls_back_to_channel_id():
    """channel.get('name', cid) — missing 'name' must fall back to id."""
    nameless = [{"id": "C_NONAME"}]
    history = {"ok": True, "messages": [{"user": "U_ME", "text": "hi"}]}
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "channels": nameless}),
        mock_response(history),
    ]):
        result = fetch_slack_activity("token", user_id="U_ME")
    assert result["messages_sent"][0]["channel"] == "C_NONAME"


def test_channels_null_in_response_does_not_crash():
    """API returns 'channels': null — None[:15] would TypeError. BUG."""
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "channels": None}),
    ]):
        result = fetch_slack_activity("token", user_id="U_ME")
    assert result["messages_sent"] == []


def test_auth_test_empty_user_id_collects_nothing():
    """auth.test ok=True but user_id='' — must not silently match every message."""
    history = {"ok": True, "messages": [{"user": "", "text": "msg"}]}
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "user_id": ""}),
        mock_response({"ok": True, "channels": CHANNELS}),
        mock_response(history),
    ]):
        result = fetch_slack_activity("token")
    assert result["messages_sent"] == []
    assert result["mentions"] == []


def test_message_without_user_key_does_not_match():
    """msg.get('user') is None — must never equal user_id."""
    history = {"ok": True, "messages": [{"text": "ghost message"}]}
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "channels": CHANNELS}),
        mock_response(history),
    ]):
        result = fetch_slack_activity("token", user_id="U_ME")
    assert result["messages_sent"] == []


def test_message_preview_truncated_at_120_chars():
    long_text = "a" * 200
    history = {"ok": True, "messages": [{"user": "U_ME", "text": long_text}]}
    with patch("collectors.slack.requests.get", side_effect=[
        mock_response({"ok": True, "channels": CHANNELS}),
        mock_response(history),
    ]):
        result = fetch_slack_activity("token", user_id="U_ME")
    assert len(result["messages_sent"][0]["preview"]) == 120
