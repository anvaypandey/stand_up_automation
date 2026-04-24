#!/usr/bin/env python3
"""
standup-bot: Automatically generate and post your daily standup to Slack.
Usage: python main.py [--dry-run]
"""

import argparse
import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from collectors.git import fetch_git_activity
from collectors.github import fetch_github_activity
from collectors.google_calendar import fetch_google_calendar_activity
from collectors.jira import fetch_jira_activity
from collectors.slack import fetch_slack_activity
from collectors.notion import fetch_notion_activity
from collectors.utils import activity_since
from core.healthcheck import run_healthchecks
from core.summariser import generate_standup, StandupConfig
from core.feedback import save_feedback, save_context, load_approved_examples, load_recent_context
from core.slack_delivery import post_standup_draft, poll_for_reaction, finalize_draft, delete_message

load_dotenv()

MAX_REGENERATIONS = 3
DEFAULT_MODEL = "claude-sonnet-4-6"
LOG_FILE = "standup.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def _build_configs() -> dict:
    """Read env vars and return a configs dict for all configured integrations."""
    configs: dict = {}

    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    if github_token and github_username:
        configs["github"] = {"token": github_token, "username": github_username}

    jira_url = os.getenv("JIRA_BASE_URL")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_API_TOKEN")
    if jira_url and jira_email and jira_token:
        configs["jira"] = {"base_url": jira_url, "email": jira_email, "api_token": jira_token}

    slack_token = os.getenv("SLACK_BOT_TOKEN")
    if slack_token:
        configs["slack"] = {"token": slack_token}

    notion_token = os.getenv("NOTION_TOKEN")
    if notion_token:
        configs["notion"] = {"token": notion_token}

    return configs


def _collect_activity(
    configs: dict,
    health: dict,
    slack_user_id: str | None,
    since: datetime,
) -> tuple[dict, list[str]]:
    """Run all configured collectors and return (activity, failed_collector_names)."""
    activity: dict = {}
    failed: list[str] = []

    if "github" in configs and health.get("github"):
        log.info("Fetching GitHub activity...")
        cfg = configs["github"]
        try:
            activity["github"] = fetch_github_activity(cfg["token"], cfg["username"], since=since)
        except Exception as e:
            log.warning("GitHub collector failed — skipping: %s", e)
            failed.append("GitHub")
    elif "github" not in configs:
        log.info("Skipping GitHub (GITHUB_TOKEN or GITHUB_USERNAME not set)")

    if "jira" in configs and health.get("jira"):
        log.info("Fetching Jira activity...")
        cfg = configs["jira"]
        try:
            activity["jira"] = fetch_jira_activity(cfg["base_url"], cfg["email"], cfg["api_token"], since=since)
        except Exception as e:
            log.warning("Jira collector failed — skipping: %s", e)
            failed.append("Jira")
    elif "jira" not in configs:
        log.info("Skipping Jira (JIRA_BASE_URL, JIRA_EMAIL, or JIRA_API_TOKEN not set)")

    if "slack" in configs and health.get("slack") and slack_user_id:
        log.info("Fetching Slack activity...")
        try:
            activity["slack"] = fetch_slack_activity(configs["slack"]["token"], since=since, user_id=slack_user_id)
        except Exception as e:
            log.warning("Slack collector failed — skipping: %s", e)
            failed.append("Slack")
    elif "slack" not in configs:
        log.info("Skipping Slack collection (SLACK_BOT_TOKEN not set)")

    if "notion" in configs and health.get("notion"):
        log.info("Fetching Notion activity...")
        try:
            activity["notion"] = fetch_notion_activity(configs["notion"]["token"], since=since)
        except Exception as e:
            log.warning("Notion collector failed — skipping: %s", e)
            failed.append("Notion")
    elif "notion" not in configs:
        log.info("Skipping Notion (NOTION_TOKEN not set)")

    git_repo_paths = [p for p in os.getenv("GIT_REPO_PATHS", "").split(",") if p.strip()]
    git_author = os.getenv("GIT_AUTHOR", "")
    if git_repo_paths and git_author:
        log.info("Fetching git commit activity...")
        try:
            activity["git"] = fetch_git_activity(git_repo_paths, git_author, since=since)
        except Exception as e:
            log.warning("Git collector failed — skipping: %s", e)
            failed.append("Git")
    elif git_repo_paths or git_author:
        log.info("Skipping git collector (both GIT_REPO_PATHS and GIT_AUTHOR must be set)")

    gcal_credentials = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "")
    if gcal_credentials:
        log.info("Fetching Google Calendar activity...")
        try:
            activity["google_calendar"] = fetch_google_calendar_activity(gcal_credentials, since=since)
        except Exception as e:
            log.warning("Google Calendar collector failed — skipping: %s", e)
            failed.append("Google Calendar")
    else:
        log.info("Skipping Google Calendar (GOOGLE_CALENDAR_CREDENTIALS not set)")

    return activity, failed


def _run_slack_feedback_loop(
    bot_token: str,
    slack_user_id: str,
    activity: dict,
    model: str,
    base_config: StandupConfig,
    standup: str,
) -> None:
    """Post draft to Slack DM and handle approve/regenerate/skip reactions."""
    slack_timeout = int(os.getenv("SLACK_FEEDBACK_TIMEOUT", "300"))
    rejected_drafts: list[dict] = []
    attempts = 0

    while True:
        log.info("Posting draft to Slack DM (reaction timeout: %ds)...", slack_timeout)
        try:
            channel_id, msg_ts = post_standup_draft(bot_token, standup, slack_user_id, timeout=slack_timeout)
        except (RuntimeError, ValueError) as e:
            log.error("Failed to post draft to Slack: %s", e)
            return

        print(f"\nDraft posted to Slack. React with ✅ approve · 🔁 regenerate · ⏭️ skip (waiting {slack_timeout}s)…\n")
        action, reason = poll_for_reaction(bot_token, channel_id, msg_ts, slack_user_id, timeout=slack_timeout)
        log.info("Slack feedback: action=%s reason=%s", action, reason or "(none)")

        if action in ("approve", "timeout"):
            if action == "approve":
                save_feedback(standup, approved=True)
                save_context(standup)
            finalize_draft(bot_token, channel_id, msg_ts, standup)
            log.info("Standup %s.", "approved" if action == "approve" else "left as posted (timeout)")
            return

        if action == "regenerate" and attempts < MAX_REGENERATIONS:
            save_feedback(standup, approved=False, reason=reason)
            rejected_drafts.append({"standup": standup, "reason": reason})
            delete_message(bot_token, channel_id, msg_ts)
            attempts += 1
            log.info("Regenerating standup (attempt %d)...", attempts)
            cfg: StandupConfig = {**base_config, "rejected_drafts": rejected_drafts}
            try:
                standup = generate_standup(activity, model, config=cfg)
            except Exception as e:
                log.error("Failed to regenerate: %s", e)
                return
        else:
            delete_message(bot_token, channel_id, msg_ts)
            log.info("Standup skipped.")
            return


def _run_terminal_feedback_loop(
    activity: dict,
    model: str,
    base_config: StandupConfig,
    standup: str,
) -> None:
    """Interactive terminal prompt for approve/regenerate/skip."""
    rejected_drafts: list[dict] = []
    attempts = 0

    while True:
        print("\n--- STANDUP DRAFT ---")
        print(standup)
        print("---------------------\n")

        regenerations_left = MAX_REGENERATIONS - attempts
        if regenerations_left > 0:
            prompt = "👍 Approve (u) / 👎 Regenerate (d) / ⏭️  Skip (s): "
        else:
            log.warning("Max regenerations reached.")
            prompt = "👍 Approve (u) / ⏭️  Skip (s): "

        try:
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            log.info("Skipping feedback.")
            return

        if choice == "u":
            log.info("Standup approved by user.")
            save_feedback(standup, approved=True)
            save_context(standup)
            return

        if choice == "d" and regenerations_left > 0:
            try:
                reason = input("Why? (optional — press Enter to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                reason = ""
            log.info("Standup rejected. Reason: %s", reason or "(none)")
            save_feedback(standup, approved=False, reason=reason)
            rejected_drafts.append({"standup": standup, "reason": reason})
            attempts += 1
            log.info("Regenerating standup (attempt %d)...", attempts)
            cfg: StandupConfig = {**base_config, "rejected_drafts": rejected_drafts}
            try:
                standup = generate_standup(activity, model, config=cfg)
            except Exception as e:
                log.error("Failed to regenerate: %s", e)
                return
        else:
            log.info("Skipping posting.")
            return


def main():
    parser = argparse.ArgumentParser(description="Generate and post your daily standup.")
    parser.add_argument("--dry-run", action="store_true", help="Print standup to stdout without posting to Slack.")
    args = parser.parse_args()

    log.info("Standup Bot starting%s...", " (dry run)" if args.dry_run else "")

    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    log.info("Using model: %s", model)

    since = activity_since()
    if datetime.now(timezone.utc).weekday() == 0:
        log.info("Monday detected — fetching activity since last Friday (%s UTC)", since.strftime("%Y-%m-%d %H:%M"))
    else:
        log.info("Fetching activity since %s UTC", since.strftime("%Y-%m-%d %H:%M"))

    configs = _build_configs()

    if configs:
        health, hc_slack_user_id = run_healthchecks(configs)
        if not any(health.values()):
            log.error("All configured integrations failed healthcheck — nothing to collect. Exiting.")
            return
    else:
        health, hc_slack_user_id = {}, None
        log.warning("No integrations configured — standup will be empty. Set at least one integration.")

    slack_token: str | None = None
    slack_user_id: str | None = os.getenv("SLACK_USER_ID") or None
    if "slack" in configs and health.get("slack"):
        slack_token = configs["slack"]["token"]
        if not slack_user_id:
            slack_user_id = hc_slack_user_id
    elif "slack" in configs:
        log.warning("Skipping Slack (healthcheck failed)")

    activity, failed_collectors = _collect_activity(configs, health, slack_user_id, since)

    if not activity:
        log.warning("No activity collected — standup will be empty.")

    base_config: StandupConfig = {
        "approved_examples": load_approved_examples(),
        "recent_context": load_recent_context(),
    }

    log.info("Generating standup...")
    try:
        standup = generate_standup(activity, model, config=base_config)
    except Exception as e:
        log.error("Failed to generate standup: %s", e)
        return

    if failed_collectors:
        standup += "\n\n⚠️ Data unavailable today: " + ", ".join(failed_collectors)

    if args.dry_run:
        print("\n--- STANDUP (DRY RUN) ---")
        print(standup)
        print("------------------------\n")
        log.info("Dry run — standup not posted.")
        return

    if slack_token and slack_user_id:
        _run_slack_feedback_loop(slack_token, slack_user_id, activity, model, base_config, standup)
    else:
        if slack_token:
            log.info("Slack feedback loop unavailable — authentication failed. Falling back to terminal.")
        _run_terminal_feedback_loop(activity, model, base_config, standup)


if __name__ == "__main__":
    main()
