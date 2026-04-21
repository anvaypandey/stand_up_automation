import requests
from datetime import date

HTTP_TIMEOUT = 10


def post_to_slack_dm(bot_token: str, standup_text: str, user_id: str | None = None) -> None:
    """Post the standup message as a DM to yourself via Slack bot."""
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }

    if not user_id:
        resp = requests.get("https://slack.com/api/auth.test", headers=headers, timeout=HTTP_TIMEOUT)
        identity = resp.json() if resp.ok else {}
        user_id = identity.get("user_id")
        if not user_id:
            raise ValueError("Could not determine Slack user ID. Check your bot token.")

    dm_resp = requests.post(
        "https://slack.com/api/conversations.open",
        headers=headers,
        json={"users": user_id},
        timeout=HTTP_TIMEOUT,
    )
    dm_data = dm_resp.json() if dm_resp.ok else {}
    if not dm_data.get("ok"):
        raise RuntimeError(f"Failed to open DM: {dm_data.get('error', f'HTTP {dm_resp.status_code}')}")
    channel_id = dm_data.get("channel", {}).get("id")
    if not channel_id:
        raise RuntimeError("Failed to open DM: response missing channel ID")

    today = date.today().strftime("%A, %B %d")
    msg_resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json={
            "channel": channel_id,
            "text": f"*🤖 Your Daily Standup — {today}*\n\n{standup_text}",
            "unfurl_links": False,
        },
        timeout=HTTP_TIMEOUT,
    )
    result = msg_resp.json() if msg_resp.ok else {}
    if not result.get("ok"):
        raise RuntimeError(f"Failed to post message: {result.get('error', f'HTTP {msg_resp.status_code}')}")
