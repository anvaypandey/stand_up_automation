import json
import pytest
from unittest.mock import patch
from core.feedback import save_feedback, load_approved_examples


def test_save_and_load_approved(tmp_path):
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("standup text", approved=True)
        examples = load_approved_examples()
    assert examples == ["standup text"]


def test_rejected_entries_excluded_from_examples(tmp_path):
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("bad standup", approved=False, reason="too long")
        save_feedback("good standup", approved=True)
        examples = load_approved_examples()
    assert examples == ["good standup"]


def test_load_returns_empty_when_file_absent(tmp_path):
    log = tmp_path / "nonexistent.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        examples = load_approved_examples()
    assert examples == []


def test_load_respects_limit(tmp_path):
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        for i in range(5):
            save_feedback(f"standup {i}", approved=True)
        examples = load_approved_examples(limit=3)
    assert len(examples) == 3
    assert examples == ["standup 2", "standup 3", "standup 4"]


def test_saved_entry_has_required_fields(tmp_path):
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("my standup", approved=True, reason="great")
    entry = json.loads(log.read_text().strip())
    assert entry["approved"] is True
    assert entry["standup"] == "my standup"
    assert entry["reason"] == "great"
    assert "timestamp" in entry


def test_corrupted_lines_are_skipped(tmp_path):
    log = tmp_path / "feedback_log.jsonl"
    log.write_text('{"approved": true, "standup": "good"}\nnot valid json\n{"approved": true, "standup": "also good"}\n')
    with patch("core.feedback.FEEDBACK_LOG", log):
        examples = load_approved_examples()
    assert examples == ["good", "also good"]


def test_multiple_saves_append_not_overwrite(tmp_path):
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("first", approved=True)
        save_feedback("second", approved=True)
        examples = load_approved_examples(limit=10)
    assert examples == ["first", "second"]


# --- adversarial ---

def test_limit_zero_returns_empty(tmp_path):
    """deque(maxlen=0) keeps nothing — must return []."""
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("something", approved=True)
        examples = load_approved_examples(limit=0)
    assert examples == []


def test_standup_with_newlines_saves_as_single_jsonl_line(tmp_path):
    """Newlines inside standup text must be JSON-escaped, not written as literal newlines."""
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("line1\nline2\nline3", approved=True)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1  # one JSONL record, not three lines


def test_load_approved_skips_entry_missing_standup_key(tmp_path):
    """Entry with no 'standup' key — KeyError caught by except clause."""
    log = tmp_path / "feedback_log.jsonl"
    log.write_text('{"approved": true}\n{"approved": true, "standup": "good"}\n')
    with patch("core.feedback.FEEDBACK_LOG", log):
        examples = load_approved_examples()
    assert examples == ["good"]


def test_timestamp_is_utc_iso_format(tmp_path):
    """Timestamp field must be an ISO 8601 string with timezone info."""
    log = tmp_path / "feedback_log.jsonl"
    with patch("core.feedback.FEEDBACK_LOG", log):
        save_feedback("standup", approved=True)
    entry = json.loads(log.read_text().strip())
    ts = entry["timestamp"]
    assert "T" in ts and ("+" in ts or ts.endswith("Z"))
