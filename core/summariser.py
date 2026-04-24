import json
import logging
from typing import TypedDict
import litellm

litellm.telemetry = False

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful engineering assistant that writes concise daily standup updates.
Given raw activity data from GitHub, Jira, Slack, Notion, local git commits, and Google Calendar meetings, produce a standup message with three sections:
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


class StandupConfig(TypedDict, total=False):
    rejected_drafts: list[dict]
    approved_examples: list[str]
    recent_context: list[dict]


def _build_system_content(recent_context: list[dict]) -> list[dict]:
    """Build the system message content.

    The static system prompt block is marked for Anthropic prompt caching;
    the dynamic context block is not, so it doesn't bust the cached prefix.
    """
    static_block: dict = {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }

    if not recent_context:
        return [static_block]

    lines = [f"- {e['date']}: {e['standup'].splitlines()[0]}" for e in recent_context]
    context_text = "Recent context from your previous standups (use this to write 'continued work on X' where relevant):\n" + "\n".join(lines)

    return [static_block, {"type": "text", "text": context_text}]


def _build_first_message(activity_data: dict, approved_examples: list[str]) -> str:
    parts = []

    if approved_examples:
        parts.append("Here are examples of standups I've approved before — use them as a style guide:\n")
        for i, example in enumerate(approved_examples, 1):
            parts.append(f"EXAMPLE {i}:\n{example}")
        parts.append("---")

    parts.append("Here is my activity from the last 24 hours. Please write my standup update.")
    for source, data in activity_data.items():
        parts.append(f"\n{source.upper()} ACTIVITY:\n{json.dumps(data, indent=2)}")

    return "\n\n".join(parts)


def generate_standup(activity_data: dict, model: str, config: StandupConfig | None = None) -> str:
    """Generate a standup using any LiteLLM-supported model."""
    cfg = config or {}
    recent_context: list[dict] = cfg.get("recent_context") or []
    approved_examples: list[str] = cfg.get("approved_examples") or []
    rejected_drafts: list[dict] = cfg.get("rejected_drafts") or []

    messages = [
        {"role": "system", "content": _build_system_content(recent_context)},
        {"role": "user", "content": _build_first_message(activity_data, approved_examples)},
    ]

    for draft in rejected_drafts:
        messages.append({"role": "assistant", "content": draft["standup"]})
        critique = "That version wasn't quite right."
        if draft.get("reason"):
            critique += f" {draft['reason']}."
        critique += " Please try again."
        messages.append({"role": "user", "content": critique})

    response = litellm.completion(model=model, messages=messages, max_tokens=MAX_TOKENS, timeout=LLM_TIMEOUT)

    _log_cache_usage(response)

    choices = response.choices or []
    if not choices:
        raise RuntimeError("LLM returned no choices — check your model name and API key.")
    content = choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response — the request may have been filtered.")
    return content


def _log_cache_usage(response) -> None:
    usage = getattr(response, "usage", None)
    if not usage:
        return
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    if created or read:
        log.info("Prompt cache — created: %d tokens  read: %d tokens", created, read)
