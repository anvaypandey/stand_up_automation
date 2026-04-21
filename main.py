#!/usr/bin/env python3
"""
standup-bot: Automatically generate and post your daily standup to Slack.
Usage: python main.py
"""

import logging
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from collectors.github import fetch_github_activity
from collectors.jira import fetch_jira_activity
from collectors.slack import fetch_slack_activity
from collectors.notion import fetch_notion_activity
from collectors.utils import activity_since
from core.summariser import generate_standup
from core.feedback import save_feedback, load_approved_examples
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


def _get_slack_user_id(token: str) -> str | None:
    """Resolve the bot's own Slack user ID from the token — called once and shared."""
    resp = requests.get(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    )
    data = resp.json() if resp.ok else {}
    if not data.get("ok"):
        log.warning("Could not resolve Slack user ID: %s", data.get('error', 'unknown error'))
        return None
    return data.get("user_id")


def main():
    log.info("Standup Bot starting...")

    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    log.info("Using model: %s", model)

    since = activity_since()
    if datetime.now(timezone.utc).weekday() == 0:
        log.info("Monday detected — fetching activity since last Friday (%s UTC)", since.strftime("%Y-%m-%d %H:%M"))
    else:
        log.info("Fetching activity since %s UTC", since.strftime("%Y-%m-%d %H:%M"))

    activity = {}
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    slack_user_id: str | None = os.getenv("SLACK_USER_ID") or None

    if slack_token and not slack_user_id:
        slack_user_id = _get_slack_user_id(slack_token)

    # GitHub (optional)
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    if github_token and github_username:
        log.info("Fetching GitHub activity...")
        activity["github"] = fetch_github_activity(github_token, github_username, since=since)
    else:
        log.info("Skipping GitHub (GITHUB_TOKEN or GITHUB_USERNAME not set)")

    # Jira (optional)
    jira_url = os.getenv("JIRA_BASE_URL")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_API_TOKEN")
    if jira_url and jira_email and jira_token:
        log.info("Fetching Jira activity...")
        activity["jira"] = fetch_jira_activity(jira_url, jira_email, jira_token, since=since)
    else:
        log.info("Skipping Jira (JIRA_BASE_URL, JIRA_EMAIL, or JIRA_API_TOKEN not set)")

    # Slack (optional for collection; also used for delivery)
    if slack_token and slack_user_id:
        log.info("Fetching Slack activity...")
        activity["slack"] = fetch_slack_activity(slack_token, since=since, user_id=slack_user_id)
    elif slack_token:
        log.info("Skipping Slack collection (token set but authentication failed)")
    else:
        log.info("Skipping Slack collection (SLACK_BOT_TOKEN not set)")

    # Notion (optional)
    notion_token = os.getenv("NOTION_TOKEN")
    if notion_token:
        log.info("Fetching Notion activity...")
        activity["notion"] = fetch_notion_activity(notion_token, since=since)
    else:
        log.info("Skipping Notion (NOTION_TOKEN not set)")

    if not activity:
        log.warning("No data sources configured — standup will be empty. Set at least one integration.")

    approved_examples = load_approved_examples()
    rejected_drafts: list[dict] = []

    log.info("Generating standup...")
    try:
        standup = generate_standup(activity, model, approved_examples=approved_examples)
    except Exception as e:
        log.error("Failed to generate standup: %s", e)
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
                    )
                except Exception as e:
                    log.error("Failed to regenerate: %s", e)
                    break
            else:
                log.info("Skipping posting.")
                break


if __name__ == "__main__":
    main()