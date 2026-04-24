"""
Feedback and context storage for standup drafts.

Approved standups are written to feedback_log.jsonl and replayed as few-shot
style examples on the next run so the LLM learns the user's preferred format.

Approved standups are also summarised into context_log.jsonl so the LLM can
reference recent work and write "continued work on X" instead of re-describing
the same task fresh every day.

Note: fcntl file locking is Unix-only (Linux/macOS). This module will not work
on Windows.
"""

import fcntl
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

FEEDBACK_LOG = Path(__file__).parent.parent / "feedback_log.jsonl"
CONTEXT_LOG = Path(__file__).parent.parent / "context_log.jsonl"
CONTEXT_WINDOW = 5


def _append_jsonl(path: Path, entry: dict) -> None:
    """Append a JSON entry to a .jsonl file with an exclusive file lock."""
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(entry) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def save_feedback(standup: str, approved: bool, reason: str = "") -> None:
    """Append a feedback entry to feedback_log.jsonl."""
    _append_jsonl(FEEDBACK_LOG, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "approved": approved,
        "reason": reason,
        "standup": standup,
    })


def save_context(standup: str) -> None:
    """Append the approved standup to context_log.jsonl for use as running context."""
    _append_jsonl(CONTEXT_LOG, {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "standup": standup,
    })


def load_recent_context(limit: int = CONTEXT_WINDOW) -> list[dict]:
    """Return the most recent approved standup entries as {date, standup} dicts."""
    if not CONTEXT_LOG.exists():
        return []
    recent: deque[dict] = deque(maxlen=limit)
    with open(CONTEXT_LOG) as f:
        for line in f:
            try:
                entry = json.loads(line)
                recent.append({"date": entry["date"], "standup": entry["standup"]})
            except (json.JSONDecodeError, KeyError):
                continue
    return list(recent)


def load_approved_examples(limit: int = 3) -> list[str]:
    """Return the standup text of the most recent approved entries."""
    if not FEEDBACK_LOG.exists():
        return []
    recent: deque[str] = deque(maxlen=limit)
    with open(FEEDBACK_LOG) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("approved"):
                    recent.append(entry["standup"])
            except (json.JSONDecodeError, KeyError):
                continue
    return list(recent)
