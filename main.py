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
from core.summariser import generate_standup
from core.feedback import save_feedback, save_context, load_approved_examples, load_recent_context
from core.slack_delivery import post_standup_draft, poll_for_reaction, finalize_draft, delete_message

load_dotenv()

MAX_REGENERATIONS = 3
DEFAULT_MODEL = "claude-sonnet-4-6"
HTTP_TIMEOUT = 10
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

    slack_token = os.getenv("SLACK_BOT_TOKEN")
    slack_user_id: str | None = os.getenv("SLACK_USER_ID") or None
    git_repo_paths = [p for p in os.getenv("GIT_REPO_PATHS", "").split(",") if p.strip()]
    git_author = os.getenv("GIT_AUTHOR", "")
    gcal_credentials = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "")

    # Build configs dict for all configured integrations
    configs: dict = {}
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    if github_token and github_username:
        configs["github"] = {"token": github_token}

    jira_url = os.getenv("JIRA_BASE_URL")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_API_TOKEN")
    if jira_url and jira_email and jira_token:
        configs["jira"] = {"base_url": jira_url, "email": jira_email, "api_token": jira_token}

    if slack_token:
        configs["slack"] = {"token": slack_token}

    notion_token = os.getenv("NOTION_TOKEN")
    if notion_token:
        configs["notion"] = {"token": notion_token}

    # Startup healthcheck — validate all tokens before collecting
    if configs:
        health, hc_slack_user_id = run_healthchecks(configs)
        if not any(health.values()):
            log.error("All configured integrations failed healthcheck — nothing to collect. Exiting.")
            return
    else:
        health, hc_slack_user_id = {}, None
        log.warning("No integrations configured — standup will be empty. Set at least one integration.")

    # Use the user ID resolved during the healthcheck auth.test call (no second round trip)
    if slack_token and health.get("slack"):
        if not slack_user_id:
            slack_user_id = hc_slack_user_id
    elif slack_token:
        log.warning("Skipping Slack (healthcheck failed)")
        slack_token = None

    # Collect activity — each source is wrapped independently (circuit breaker)
    activity = {}
    failed_collectors: list[str] = []

    if "github" in configs and health.get("github"):
        log.info("Fetching GitHub activity...")
        try:
            activity["github"] = fetch_github_activity(github_token, github_username, since=since)
        except Exception as e:
            log.warning("GitHub collector failed — skipping: %s", e)
            failed_collectors.append("GitHub")
    elif "github" not in configs:
        log.info("Skipping GitHub (GITHUB_TOKEN or GITHUB_USERNAME not set)")

    if "jira" in configs and health.get("jira"):
        log.info("Fetching Jira activity...")
        try:
            activity["jira"] = fetch_jira_activity(jira_url, jira_email, jira_token, since=since)
        except Exception as e:
            log.warning("Jira collector failed — skipping: %s", e)
            failed_collectors.append("Jira")
    elif "jira" not in configs:
        log.info("Skipping Jira (JIRA_BASE_URL, JIRA_EMAIL, or JIRA_API_TOKEN not set)")

    if slack_token and slack_user_id and health.get("slack"):
        log.info("Fetching Slack activity...")
        try:
            activity["slack"] = fetch_slack_activity(slack_token, since=since, user_id=slack_user_id)
        except Exception as e:
            log.warning("Slack collector failed — skipping: %s", e)
            failed_collectors.append("Slack")
    elif "slack" not in configs:
        log.info("Skipping Slack collection (SLACK_BOT_TOKEN not set)")

    if "notion" in configs and health.get("notion"):
        log.info("Fetching Notion activity...")
        try:
            activity["notion"] = fetch_notion_activity(notion_token, since=since)
        except Exception as e:
            log.warning("Notion collector failed — skipping: %s", e)
            failed_collectors.append("Notion")
    elif "notion" not in configs:
        log.info("Skipping Notion (NOTION_TOKEN not set)")

    # Git (local — no healthcheck needed, no network call)
    if git_repo_paths and git_author:
        log.info("Fetching git commit activity...")
        try:
            activity["git"] = fetch_git_activity(git_repo_paths, git_author, since=since)
        except Exception as e:
            log.warning("Git collector failed — skipping: %s", e)
            failed_collectors.append("Git")
    elif git_repo_paths or git_author:
        log.info("Skipping git collector (both GIT_REPO_PATHS and GIT_AUTHOR must be set)")

    # Google Calendar (optional — no healthcheck, credentials validated on first call)
    if gcal_credentials:
        log.info("Fetching Google Calendar activity...")
        try:
            activity["google_calendar"] = fetch_google_calendar_activity(gcal_credentials, since=since)
        except Exception as e:
            log.warning("Google Calendar collector failed — skipping: %s", e)
            failed_collectors.append("Google Calendar")
    else:
        log.info("Skipping Google Calendar (GOOGLE_CALENDAR_CREDENTIALS not set)")

    if not activity:
        log.warning("No activity collected — standup will be empty.")

    approved_examples = load_approved_examples()
    recent_context = load_recent_context()
    rejected_drafts: list[dict] = []

    log.info("Generating standup...")
    try:
        standup = generate_standup(activity, model, approved_examples=approved_examples, recent_context=recent_context)
    except Exception as e:
        log.error("Failed to generate standup: %s", e)
        return

    if failed_collectors:
        standup += "\n\n⚠️ Data unavailable today: " + ", ".join(failed_collectors)

    # Dry run: print and exit without posting
    if args.dry_run:
        print("\n--- STANDUP (DRY RUN) ---")
        print(standup)
        print("------------------------\n")
        log.info("Dry run — standup not posted.")
        return

    if slack_token and slack_user_id:
        # Slack-native feedback loop: post draft, poll reactions, finalize or regenerate
        slack_timeout = int(os.getenv("SLACK_FEEDBACK_TIMEOUT", "300"))
        attempts = 0
        while True:
            log.info("Posting draft to Slack DM (reaction timeout: %ds)...", slack_timeout)
            try:
                channel_id, msg_ts = post_standup_draft(
                    slack_token, standup, slack_user_id, timeout=slack_timeout
                )
            except (RuntimeError, ValueError) as e:
                log.error("Failed to post draft to Slack: %s", e)
                return

            print(f"\nDraft posted to Slack. React with ✅ approve · 🔁 regenerate · ⏭️ skip (waiting {slack_timeout}s)…\n")
            action, reason = poll_for_reaction(
                slack_token, channel_id, msg_ts, slack_user_id, timeout=slack_timeout
            )
            log.info("Slack feedback: action=%s reason=%s", action, reason or "(none)")

            if action in ("approve", "timeout"):
                if action == "approve":
                    save_feedback(standup, approved=True)
                    save_context(standup)
                finalize_draft(slack_token, channel_id, msg_ts, standup)
                log.info("Standup %s.", "approved" if action == "approve" else "left as posted (timeout)")
                break
            elif action == "regenerate" and attempts < MAX_REGENERATIONS:
                save_feedback(standup, approved=False, reason=reason)
                rejected_drafts.append({"standup": standup, "reason": reason})
                delete_message(slack_token, channel_id, msg_ts)
                attempts += 1
                log.info("Regenerating standup (attempt %d)...", attempts)
                try:
                    standup = generate_standup(
                        activity, model,
                        rejected_drafts=rejected_drafts,
                        approved_examples=approved_examples,
                        recent_context=recent_context,
                    )
                except Exception as e:
                    log.error("Failed to regenerate: %s", e)
                    return
            else:
                # skip or max regenerations reached
                delete_message(slack_token, channel_id, msg_ts)
                log.info("Standup skipped.")
                break
    else:
        # Terminal feedback loop (no Slack token configured)
        if slack_token:
            log.info("Slack feedback loop unavailable — authentication failed. Falling back to terminal.")
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
                break

            if choice == "u":
                log.info("Standup approved by user.")
                save_feedback(standup, approved=True)
                save_context(standup)
                break
            elif choice == "d" and regenerations_left > 0:
                try:
                    reason = input("Why? (optional — press Enter to skip): ").strip()
                except (EOFError, KeyboardInterrupt):
                    reason = ""
                log.info("Standup rejected. Reason: %s", reason or "(none)")
                save_feedback(standup, approved=False, reason=reason)
                rejected_drafts.append({"standup": standup, "reason": reason})
                attempts += 1
                log.info("Regenerating standup (attempt %d)...", attempts)
                try:
                    standup = generate_standup(
                        activity, model,
                        rejected_drafts=rejected_drafts,
                        approved_examples=approved_examples,
                        recent_context=recent_context,
                    )
                except Exception as e:
                    log.error("Failed to regenerate: %s", e)
                    break
            else:
                log.info("Skipping posting.")
                break


if __name__ == "__main__":
    main()
