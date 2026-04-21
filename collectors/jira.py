import requests
from datetime import datetime, timezone
from requests.auth import HTTPBasicAuth
from collectors.utils import activity_since

HTTP_TIMEOUT = 10
JIRA_MAX_RESULTS = 20
COMMENT_PREVIEW_LENGTH = 100


def extract_comment_text(body) -> str:
    """Extract plain text from a Jira comment body (ADF or legacy string)."""
    if isinstance(body, str):
        return body[:COMMENT_PREVIEW_LENGTH]
    # ADF format: {"type": "doc", "content": [{"type": "paragraph", "content": [...]}]}
    if isinstance(body, dict):
        texts = []
        for block in body.get("content", []):
            for node in block.get("content", []):
                if node.get("type") == "text":
                    texts.append(node.get("text", ""))
        return "".join(texts)[:COMMENT_PREVIEW_LENGTH]
    return ""


def fetch_jira_activity(base_url: str, email: str, api_token: str, since: datetime | None = None) -> dict:
    """Fetch Jira issues updated/transitioned since the given datetime (defaults to activity_since())."""
    auth = HTTPBasicAuth(email, api_token)
    headers = {"Accept": "application/json"}
    cutoff = since or activity_since()
    since_str = cutoff.strftime("%Y-%m-%d %H:%M")

    activity = {"done": [], "in_progress": [], "todo": [], "commented": []}

    jql = f'assignee = currentUser() AND updated >= "{since_str}" ORDER BY updated DESC'
    resp = requests.get(
        f"{base_url}/rest/api/3/search",
        headers=headers,
        auth=auth,
        params={"jql": jql, "maxResults": JIRA_MAX_RESULTS, "fields": "summary,status,assignee,comment"},
        timeout=HTTP_TIMEOUT,
    )
    if not resp.ok:
        print(f"⚠️  Jira request failed: {resp.status_code}")
        return activity

    for issue in resp.json().get("issues", []):
        fields = issue.get("fields")
        if not fields:
            continue
        status = fields.get("status", {}).get("statusCategory", {}).get("key", "")
        entry = {
            "key": issue["key"],
            "summary": fields.get("summary", ""),
            "url": f"{base_url}/browse/{issue['key']}",
        }

        if status == "done":
            activity["done"].append(entry)
        elif status == "indeterminate":
            activity["in_progress"].append(entry)
        elif status:
            activity["todo"].append(entry)

        comments = fields.get("comment", {}).get("comments", [])
        for c in comments:
            try:
                comment_time = datetime.fromisoformat(c.get("updated", "").replace("Z", "+00:00"))
                if comment_time >= cutoff:
                    activity["commented"].append({**entry, "comment_preview": extract_comment_text(c.get("body", ""))})
                    break
            except (ValueError, TypeError):
                continue

    return activity
