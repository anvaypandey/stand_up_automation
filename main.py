#!/usr/bin/env python3
"""
standup-bot: Automatically generate and post your daily standup to Slack.
Usage: python main.py
"""

import os
import requests
from dotenv import load_dotenv
from collectors.github import fetch_github_activity
from collectors.jira import fetch_jira_activity
from collectors.slack import fetch_slack_activity
from collectors.notion import fetch_notion_activity
from core.summariser import generate_standup
from core.feedback import save_feedback, load_approved_examples
from core.slack_delivery import post_to_slack_dm

load_dotenv()

MAX_REGENERATIONS = 3
DEFAULT_MODEL = "claude-sonnet-4-6"
HTTP_TIMEOUT = 10


def _get_slack_user_id(token: str) -> str | None:
    """Resolve the bot's own Slack user ID from the token — called once and shared."""
    resp = requests.get(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    )
    data = resp.json() if resp.ok else {}
    if not data.get("ok"):
        print(f"⚠️  Could not resolve Slack user ID: {data.get('error', 'unknown error')}")
        return None
    return data.get("user_id")


def main():
    print("🤖 Standup Bot starting...")

    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    print(f"🧠 Using model: {model}")

    activity = {}
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    slack_user_id: str | None = None

    if slack_token:
        slack_user_id = _get_slack_user_id(slack_token)

    # GitHub (optional)
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    if github_token and github_username:
        print("📡 Fetching GitHub activity...")
        activity["github"] = fetch_github_activity(github_token, github_username)
    else:
        print("⏭️  Skipping GitHub (GITHUB_TOKEN or GITHUB_USERNAME not set)")

    # Jira (optional)
    jira_url = os.getenv("JIRA_BASE_URL")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_API_TOKEN")
    if jira_url and jira_email and jira_token:
        print("📋 Fetching Jira activity...")
        activity["jira"] = fetch_jira_activity(jira_url, jira_email, jira_token)
    else:
        print("⏭️  Skipping Jira (JIRA_BASE_URL, JIRA_EMAIL, or JIRA_API_TOKEN not set)")

    # Slack (optional for collection; also used for delivery)
    if slack_token and slack_user_id:
        print("💬 Fetching Slack activity...")
        activity["slack"] = fetch_slack_activity(slack_token, user_id=slack_user_id)
    elif slack_token:
        print("⏭️  Skipping Slack collection (token set but authentication failed)")
    else:
        print("⏭️  Skipping Slack collection (SLACK_BOT_TOKEN not set)")

    # Notion (optional)
    notion_token = os.getenv("NOTION_TOKEN")
    if notion_token:
        print("📝 Fetching Notion activity...")
        activity["notion"] = fetch_notion_activity(notion_token)
    else:
        print("⏭️  Skipping Notion (NOTION_TOKEN not set)")

    if not activity:
        print("⚠️  No data sources configured — standup will be empty. Set at least one integration.")

    approved_examples = load_approved_examples()
    rejected_drafts: list[dict] = []

    print("✨ Generating standup...")
    try:
        standup = generate_standup(activity, model, approved_examples=approved_examples)
    except Exception as e:
        print(f"❌ Failed to generate standup: {e}")
        return

    attempts = 0
    while True:
        print("\n--- STANDUP DRAFT ---")
        print(standup)
        print("---------------------\n")

        regenerations_left = MAX_REGENERATIONS - attempts
        if regenerations_left > 0:
            prompt = "👍 Approve and post (u) / 👎 Regenerate (d) / ⏭️  Skip posting (s): "
        else:
            print("⚠️  Max regenerations reached.")
            prompt = "👍 Approve and post (u) / ⏭️  Skip posting (s): "

        try:
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nSkipping feedback.")
            break

        if choice == "u":
            save_feedback(standup, approved=True)
            break
        elif choice == "d" and regenerations_left > 0:
            try:
                reason = input("Why? (optional — press Enter to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                reason = ""
            save_feedback(standup, approved=False, reason=reason)
            rejected_drafts.append({"standup": standup, "reason": reason})
            attempts += 1
            print("🔄 Regenerating...")
            try:
                standup = generate_standup(
                    activity, model,
                    rejected_drafts=rejected_drafts,
                    approved_examples=approved_examples,
                )
            except Exception as e:
                print(f"❌ Failed to regenerate: {e}")
                break
        else:
            print("⏭️  Skipping feedback and posting.")
            break

    if slack_token and slack_user_id:
        print("📨 Posting to Slack DM...")
        try:
            post_to_slack_dm(slack_token, standup, user_id=slack_user_id)
            print("✅ Standup posted successfully!")
        except (RuntimeError, ValueError) as e:
            print(f"❌ Failed to post to Slack: {e}")
    elif slack_token:
        print("ℹ️  Slack delivery skipped — authentication failed.")
    else:
        print("ℹ️  Slack delivery skipped — set SLACK_BOT_TOKEN to auto-post.")


if __name__ == "__main__":
    main()