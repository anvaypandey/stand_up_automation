import json
import pytest
from unittest.mock import patch
from core.feedback import save_context, load_recent_context


def test_save_and_load_context(tmp_path):
    log = tmp_path / "context_log.jsonl"
    with patch("core.feedback.CONTEXT_LOG", log):
        save_context("standup text")
        entries = load_recent_context()
    assert len(entries) == 1
    assert entries[0]["standup"] == "standup text"
    assert "date" in entries[0]


def test_load_returns_empty_when_file_absent(tmp_path):
    log = tmp_path / "nonexistent.jsonl"
    with patch("core.feedback.CONTEXT_LOG", log):
        assert load_recent_context() == []


def test_respects_limit(tmp_path):
    log = tmp_path / "context_log.jsonl"
    with patch("core.feedback.CONTEXT_LOG", log):
        for i in range(7):
            save_context(f"standup {i}")
        entries = load_recent_context(limit=3)
    assert len(entries) == 3
    assert entries[-1]["standup"] == "standup 6"


def test_corrupted_lines_skipped(tmp_path):
    log = tmp_path / "context_log.jsonl"
    log.write_text('{"date": "2026-04-20", "standup": "good"}\nnot json\n')
    with patch("core.feedback.CONTEXT_LOG", log):
        entries = load_recent_context()
    assert len(entries) == 1
    assert entries[0]["standup"] == "good"


def test_context_injected_into_summariser():
    from unittest.mock import patch, MagicMock
    from core.summariser import generate_standup

    msg = MagicMock()
    msg.content = "standup"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None

    context = [{"date": "2026-04-21", "standup": "Worked on auth service"}]
    with patch("core.summariser.litellm.completion", return_value=resp) as mock_comp:
        generate_standup({}, "gpt-4o", config={"recent_context": context})

    system_content = mock_comp.call_args.kwargs["messages"][0]["content"]
    full_text = " ".join(b["text"] for b in system_content)
    assert "2026-04-21" in full_text
    assert "Worked on auth service" in full_text


def test_no_context_still_works():
    from unittest.mock import patch, MagicMock
    from core.summariser import generate_standup

    msg = MagicMock()
    msg.content = "standup"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None

    with patch("core.summariser.litellm.completion", return_value=resp) as mock_comp:
        generate_standup({}, "gpt-4o", config={"recent_context": []})

    system_content = mock_comp.call_args.kwargs["messages"][0]["content"]
    assert len(system_content) == 1  # only the static block, no context block


def test_cache_control_on_static_block():
    from unittest.mock import patch, MagicMock
    from core.summariser import generate_standup

    msg = MagicMock()
    msg.content = "standup"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None

    with patch("core.summariser.litellm.completion", return_value=resp) as mock_comp:
        generate_standup({}, "gpt-4o")

    system_content = mock_comp.call_args.kwargs["messages"][0]["content"]
    assert system_content[0]["cache_control"] == {"type": "ephemeral"}


def test_cache_usage_logged(caplog):
    import logging
    from unittest.mock import patch, MagicMock
    from core.summariser import generate_standup

    msg = MagicMock()
    msg.content = "standup"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    usage = MagicMock()
    usage.cache_creation_input_tokens = 500
    usage.cache_read_input_tokens = 0
    resp.usage = usage

    with patch("core.summariser.litellm.completion", return_value=resp):
        with caplog.at_level(logging.INFO, logger="core.summariser"):
            generate_standup({}, "gpt-4o")

    assert "cache" in caplog.text.lower()
