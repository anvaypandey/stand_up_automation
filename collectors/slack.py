import requests
from datetime import datetime, timezone
from collectors.utils import activity_since

HTTP_TIMEOUT = 10
CONVERSATIONS_FETCH_LIMIT = 50
CHANNEL_SCAN_LIMIT = 15
HISTORY_LIMIT = 50
MESSAGE_PREVIEW_LENGTH = 120


def fetch_slack_activity(token: str, since: datetime | None = None, user_id: str | None = None) -> dict:
    """Fetch messages sent and mentions received from Slack."""
    headers = {"Authorization": f"Bearer {token}"}
    oldest = str((since or activity_since()).timestamp())
    activity = {"messages_sent": [], "mentions": [], "channels_active": []}

    # Resolve user ID if not provided
    if not user_id:
        resp = requests.get("https://slack.com/api/auth.test", headers=headers, timeout=HTTP_TIMEOUT)
        identity = resp.json() if resp.ok else {}
        if not identity.get("ok"):
            print(f"⚠️  Slack auth failed: {identity.get('error', 'unknown error')}")
            return activity
        user_id = identity.get("user_id", "")
        if not user_id:
            print("⚠️  Slack auth.test returned no user_id — cannot collect activity")
            return activity

    channels_resp = requests.get(
        "https://slack.com/api/users.conversations",
        headers=headers,
        params={"types": "public_channel,private_channel", "limit": CONVERSATIONS_FETCH_LIMIT},
        timeout=HTTP_TIMEOUT,
    )
    channels_data = channels_resp.json() if channels_resp.ok else {}
    if not channels_data.get("ok"):
        print(f"⚠️  Could not fetch Slack channels: {channels_data.get('error', 'unknown error')}")
        return activity

    active_channels: set[str] = set()

    for channel in (channels_data.get("channels") or [])[:CHANNEL_SCAN_LIMIT]:
        cid = channel["id"]
        cname = channel.get("name", cid)

        history_resp = requests.get(
            "https://slack.com/api/conversations.history",
            headers=headers,
            params={"channel": cid, "oldest": oldest, "limit": HISTORY_LIMIT},
            timeout=HTTP_TIMEOUT,
        )
        history_data = history_resp.json() if history_resp.ok else {}
        if not history_data.get("ok"):
            if history_data.get("error") == "ratelimited":
                print("⚠️  Slack rate limited — skipping remaining channels")
                break
            continue

        for msg in history_data.get("messages", []):
            text = msg.get("text", "")
            if msg.get("user") == user_id:
                activity["messages_sent"].append({"channel": cname, "preview": text[:MESSAGE_PREVIEW_LENGTH]})
                active_channels.add(cname)
            elif f"<@{user_id}>" in text:
                activity["mentions"].append({"channel": cname, "preview": text[:MESSAGE_PREVIEW_LENGTH], "from_user": msg.get("user", "unknown")})

    activity["channels_active"] = list(active_channels)
    return activity
