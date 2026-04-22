import logging
import requests
from requests.auth import HTTPBasicAuth

HTTP_TIMEOUT = 10

log = logging.getLogger(__name__)


def _check_github(cfg: dict) -> bool:
    return requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {cfg['token']}", "Accept": "application/vnd.github.v3+json"},
        timeout=HTTP_TIMEOUT,
    ).ok


def _check_jira(cfg: dict) -> bool:
    return requests.get(
        f"{cfg['base_url']}/rest/api/3/myself",
        auth=HTTPBasicAuth(cfg["email"], cfg["api_token"]),
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    ).ok


def _check_slack(cfg: dict) -> tuple[bool, str | None]:
    """Returns (ok, user_id) — user_id is captured here to avoid a second auth.test call."""
    resp = requests.get(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {cfg['token']}"},
        timeout=HTTP_TIMEOUT,
    )
    data = resp.json() if resp.ok else {}
    ok = data.get("ok", False)
    return ok, data.get("user_id") if ok else None


def _check_notion(cfg: dict) -> bool:
    return requests.get(
        "https://api.notion.com/v1/users/me",
        headers={"Authorization": f"Bearer {cfg['token']}", "Notion-Version": "2022-06-28"},
        timeout=HTTP_TIMEOUT,
    ).ok


def run_healthchecks(configs: dict) -> tuple[dict[str, bool], str | None]:
    """Validate each configured integration token.

    Returns:
        results: {source: ok} for each configured source
        slack_user_id: resolved from the Slack auth.test call, or None
    """
    results: dict[str, bool] = {}
    slack_user_id: str | None = None

    for source, cfg in configs.items():
        try:
            if source == "github":
                results[source] = _check_github(cfg)
            elif source == "jira":
                results[source] = _check_jira(cfg)
            elif source == "slack":
                ok, uid = _check_slack(cfg)
                results[source] = ok
                if ok:
                    slack_user_id = uid
            elif source == "notion":
                results[source] = _check_notion(cfg)
        except Exception as e:
            log.warning("%s healthcheck error: %s", source.capitalize(), e)
            results[source] = False

    _log_summary(results)
    return results, slack_user_id


def _log_summary(results: dict[str, bool]) -> None:
    parts = [f"{'✅' if ok else '⚠️ '} {src}" for src, ok in results.items()]
    log.info("Healthcheck — %s", "  ".join(parts) if parts else "no integrations configured")
