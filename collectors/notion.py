import requests
from datetime import datetime, timezone
from collectors.utils import activity_since

HTTP_TIMEOUT = 10
NOTION_PAGE_SIZE = 20


def fetch_notion_activity(token: str, since: datetime | None = None) -> dict:
    """Fetch Notion pages last edited by the current user since the given datetime.

    Note: Notion's search API returns at most 20 results sorted by last_edited_time.
    If teammates are highly active, pages you edited may fall outside the first 20
    results and be missed. This is a Notion API limitation with no workaround.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    cutoff = since or activity_since()
    activity = {"edited_pages": []}

    # Resolve current user's Notion ID to filter out edits by teammates
    me_resp = requests.get("https://api.notion.com/v1/users/me", headers=headers, timeout=HTTP_TIMEOUT)
    my_id = me_resp.json().get("id", "") if me_resp.ok else ""
    if not my_id:
        print("⚠️  Could not resolve Notion user ID — results may include teammates' edits")

    resp = requests.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json={"sort": {"direction": "descending", "timestamp": "last_edited_time"}, "page_size": NOTION_PAGE_SIZE},
        timeout=HTTP_TIMEOUT,
    )
    if not resp.ok:
        print(f"⚠️  Notion request failed: {resp.status_code}")
        return activity

    for result in resp.json().get("results", []):
        last_edited = result.get("last_edited_time", "")
        try:
            edited_at = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if edited_at < cutoff:
            continue

        # Skip pages not edited by the current user
        last_edited_by = result.get("last_edited_by", {}).get("id", "")
        if my_id and last_edited_by != my_id:
            continue

        title = "Untitled"
        for prop in result.get("properties", {}).values():
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                if parts:
                    title = "".join(p.get("plain_text", "") for p in parts)
                    break

        activity["edited_pages"].append({
            "title": title,
            "url": result.get("url", ""),
            "last_edited": edited_at.date().isoformat(),
        })

    return activity
