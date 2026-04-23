import json
import litellm

litellm.telemetry = False

DATA_SOURCES = ("github", "jira", "slack", "notion", "git")

SYSTEM_PROMPT = """You are a helpful engineering assistant that writes concise daily standup updates.
Given raw activity data from GitHub, Jira, Slack, and Notion, produce a standup message with three sections:
✅ Done, 🔄 In Progress, and 🚧 Blockers/Waiting.

Rules:
- Be concise — each bullet max 1 line
- Use plain English, not ticket numbers alone (include a short description)
- Include links where relevant using Slack mrkdwn format: <url|label>
- If there are no clear blockers, write "None identified"
- Do NOT include fluff or filler phrases
- Output in Slack mrkdwn format (use *bold* for section headers)
"""

MAX_TOKENS = 1500
LLM_TIMEOUT = 60


def _build_first_message(activity_data: dict, approved_examples: list[str]) -> str:
    parts = []

    if approved_examples:
        parts.append("Here are examples of standups I've approved before — use them as a style guide:\n")
        for i, example in enumerate(approved_examples, 1):
            parts.append(f"EXAMPLE {i}:\n{example}")
        parts.append("---")

    parts.append("Here is my activity from the last 24 hours. Please write my standup update.")
    for source in DATA_SOURCES:
        parts.append(f"\n{source.upper()} ACTIVITY:\n{json.dumps(activity_data.get(source, {}), indent=2)}")

    return "\n\n".join(parts)


def generate_standup(
    activity_data: dict,
    model: str,
    rejected_drafts: list[dict] | None = None,
    approved_examples: list[str] | None = None,
) -> str:
    """Generate a standup using any LiteLLM-supported model."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_first_message(activity_data, approved_examples or [])},
    ]

    for draft in rejected_drafts or []:
        messages.append({"role": "assistant", "content": draft["standup"]})
        critique = "That version wasn't quite right."
        if draft.get("reason"):
            critique += f" {draft['reason']}."
        critique += " Please try again."
        messages.append({"role": "user", "content": critique})

    response = litellm.completion(model=model, messages=messages, max_tokens=MAX_TOKENS, timeout=LLM_TIMEOUT)

    choices = response.choices or []
    if not choices:
        raise RuntimeError("LLM returned no choices — check your model name and API key.")
    content = choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response — the request may have been filtered.")
    return content
