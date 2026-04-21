import requests
from datetime import datetime, timezone
from collectors.utils import activity_since

HTTP_TIMEOUT = 10
PR_AUTHOR_LIMIT = 20
PR_REVIEW_LIMIT = 10


def fetch_github_activity(token: str, username: str, since: datetime | None = None) -> dict:
    """Fetch PRs and review activity since the given datetime (defaults to activity_since())."""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    since = (since or activity_since()).strftime("%Y-%m-%d")
    activity = {"merged_prs": [], "open_prs": [], "reviews": []}

    # PRs authored by user
    resp = requests.get(
        "https://api.github.com/search/issues",
        headers=headers,
        params={"q": f"author:{username} type:pr updated:>{since}", "per_page": PR_AUTHOR_LIMIT},
        timeout=HTTP_TIMEOUT,
    )
    if resp.ok:
        for item in resp.json().get("items", []):
            entry = {
                "title": item["title"],
                "url": item["html_url"],
                "repo": item["repository_url"].split("/")[-1],
            }
            merged_at = item.get("pull_request", {}).get("merged_at")
            if merged_at:
                activity["merged_prs"].append(entry)
            elif item["state"] == "open":
                activity["open_prs"].append(entry)
            # closed-but-not-merged PRs are intentionally omitted

    # PRs reviewed by user
    resp = requests.get(
        "https://api.github.com/search/issues",
        headers=headers,
        params={"q": f"reviewed-by:{username} type:pr updated:>{since}", "per_page": PR_REVIEW_LIMIT},
        timeout=HTTP_TIMEOUT,
    )
    if resp.ok:
        for item in resp.json().get("items", []):
            activity["reviews"].append({
                "title": item["title"],
                "url": item["html_url"],
                "repo": item["repository_url"].split("/")[-1],
            })

    return activity
