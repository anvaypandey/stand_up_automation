"""
Feedback storage for standup drafts.

Approved standups are written to feedback_log.jsonl and replayed as few-shot
style examples on the next run so the LLM learns the user's preferred format.
"""

import fcntl
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

FEEDBACK_LOG = Path(__file__).parent.parent / "feedback_log.jsonl"


def save_feedback(standup: str, approved: bool, reason: str = "") -> None:
    """Append a feedback entry to feedback_log.jsonl, with an exclusive file lock."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "approved": approved,
        "reason": reason,
        "standup": standup,
    }
    with open(FEEDBACK_LOG, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(entry) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


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
