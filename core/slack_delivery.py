import logging
import time
import requests
from datetime import date

HTTP_TIMEOUT = 10

log = logging.getLogger(__name__)
REACTION_POLL_INTERVAL = 5
APPROVE_EMOJI = "white_check_mark"   # ✅
REGEN_EMOJI = "arrows_clockwise"     # 🔁
SKIP_EMOJI = "next_track_button"     # ⏭️


def _build_blocks(title: str, standup_text: str, footer: str | None = None) -> list[dict]:
    """Convert standup mrkdwn text into Slack Block Kit blocks.

    Each double-newline-separated chunk becomes its own section block so that
    the three standup sections (Done / In Progress / Blockers) render as distinct
    visual groups with bold headers and bullet lists.
    """
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
        {"type": "divider"},
    ]

    for chunk in standup_text.split("\n\n"):
        chunk = chunk.strip()
        if chunk:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            })

    if footer:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": footer}],
        })

    return blocks


def _open_dm_channel(headers: dict, user_id: str) -> str:
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
    return channel_id


def post_standup_draft(
    bot_token: str, standup_text: str, user_id: str, timeout: int = 120
) -> tuple[str, str]:
    """Post a standup draft with reaction instructions. Returns (channel_id, message_ts)."""
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }
    channel_id = _open_dm_channel(headers, user_id)
    today = date.today().strftime("%A, %B %d")
    title = f"🤖 Your Daily Standup — {today}"
    footer = f"React to respond: ✅ approve · 🔁 regenerate (reply in thread with reason) · ⏭️ skip · Waiting {timeout}s…"

    msg_resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json={
            "channel": channel_id,
            "text": f"{title}\n\n{standup_text}",  # plain-text fallback for notifications
            "unfurl_links": False,
            "blocks": _build_blocks(title, standup_text, footer=footer),
        },
        timeout=HTTP_TIMEOUT,
    )
    result = msg_resp.json() if msg_resp.ok else {}
    if not result.get("ok"):
        raise RuntimeError(f"Failed to post draft: {result.get('error', f'HTTP {msg_resp.status_code}')}")

    return channel_id, result["ts"]


def poll_for_reaction(
    bot_token: str, channel_id: str, ts: str, user_id: str, timeout: int = 120
) -> tuple[str, str]:
    """Poll for emoji reactions on a draft message.

    Returns (action, reason) where action is 'approve', 'regenerate', 'skip', or 'timeout'.
    For 'regenerate', reason is taken from the first thread reply by the user.
    """
    headers = {"Authorization": f"Bearer {bot_token}"}
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(REACTION_POLL_INTERVAL)

        try:
            react_resp = requests.get(
                "https://slack.com/api/reactions.get",
                headers=headers,
                params={"channel": channel_id, "timestamp": ts, "full": True},
                timeout=HTTP_TIMEOUT,
            )
            react_data = react_resp.json() if react_resp.ok else {}
        except requests.exceptions.RequestException:
            continue
        if not react_data.get("ok"):
            continue

        reactions = {r["name"] for r in react_data.get("message", {}).get("reactions", [])}

        if APPROVE_EMOJI in reactions:
            return "approve", ""
        if SKIP_EMOJI in reactions:
            return "skip", ""
        if REGEN_EMOJI in reactions:
            reason = _fetch_thread_reply(headers, channel_id, ts, user_id)
            return "regenerate", reason

    return "timeout", ""


def _fetch_thread_reply(headers: dict, channel_id: str, ts: str, user_id: str) -> str:
    """Return the first thread reply from the user (used as regeneration reason)."""
    try:
        resp = requests.get(
            "https://slack.com/api/conversations.replies",
            headers=headers,
            params={"channel": channel_id, "ts": ts, "limit": 10},
            timeout=HTTP_TIMEOUT,
        )
        data = resp.json() if resp.ok else {}
    except requests.exceptions.RequestException:
        return ""
    for msg in (data.get("messages") or [])[1:]:  # skip parent
        if msg.get("user") == user_id and msg.get("text"):
            return msg["text"]
    return ""


def finalize_draft(bot_token: str, channel_id: str, ts: str, standup_text: str) -> None:
    """Update the draft message to the clean final version (removes reaction footer)."""
    today = date.today().strftime("%A, %B %d")
    title = f"🤖 Your Daily Standup — {today}"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        "https://slack.com/api/chat.update",
        headers=headers,
        json={
            "channel": channel_id,
            "ts": ts,
            "text": f"{title}\n\n{standup_text}",
            "blocks": _build_blocks(title, standup_text),
        },
        timeout=HTTP_TIMEOUT,
    )
    result = resp.json() if resp.ok else {}
    if not result.get("ok"):
        log.warning("Failed to finalize draft: %s", result.get("error", f"HTTP {resp.status_code}"))


def delete_message(bot_token: str, channel_id: str, ts: str) -> None:
    """Delete a Slack message (used to remove rejected or skipped drafts)."""
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        "https://slack.com/api/chat.delete",
        headers=headers,
        json={"channel": channel_id, "ts": ts},
        timeout=HTTP_TIMEOUT,
    )
    result = resp.json() if resp.ok else {}
    if not result.get("ok"):
        log.warning("Failed to delete message: %s", result.get("error", f"HTTP {resp.status_code}"))
