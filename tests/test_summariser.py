import pytest
from unittest.mock import patch, MagicMock
from core.summariser import generate_standup


def _litellm_response(content):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_returns_llm_content():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("my standup")):
        result = generate_standup({"github": {}}, "gpt-4o")
    assert result == "my standup"


def test_correct_model_passed_to_litellm():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "my-provider/my-model-v2")
    assert mock_comp.call_args.kwargs["model"] == "my-provider/my-model-v2"


def test_empty_choices_raises():
    resp = MagicMock()
    resp.choices = []
    with patch("core.summariser.litellm.completion", return_value=resp):
        with pytest.raises(RuntimeError, match="no choices"):
            generate_standup({}, "gpt-4o")


def test_none_content_raises():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response(None)):
        with pytest.raises(RuntimeError, match="empty response"):
            generate_standup({}, "gpt-4o")


def test_rejected_draft_builds_multiturn_messages():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o", config={"rejected_drafts": [{"standup": "bad draft", "reason": "too verbose"}]})

    messages = mock_comp.call_args.kwargs["messages"]
    # system + user + assistant (rejected) + user (critique)
    assert len(messages) == 4
    assert messages[2]["role"] == "assistant"
    assert messages[2]["content"] == "bad draft"
    assert messages[3]["role"] == "user"
    assert "too verbose" in messages[3]["content"]


def test_multiple_rejections_build_full_conversation():
    drafts = [
        {"standup": "draft 1", "reason": "reason 1"},
        {"standup": "draft 2", "reason": "reason 2"},
    ]
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o", config={"rejected_drafts": drafts})

    messages = mock_comp.call_args.kwargs["messages"]
    # system + user + (assistant + user) * 2
    assert len(messages) == 6


def test_approved_examples_injected_into_first_message():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o", config={"approved_examples": ["example standup text"]})

    first_user_msg = mock_comp.call_args.kwargs["messages"][1]["content"]
    assert "example standup text" in first_user_msg


def test_no_examples_no_preamble():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o", config={"approved_examples": []})

    first_user_msg = mock_comp.call_args.kwargs["messages"][1]["content"]
    assert "style guide" not in first_user_msg


def test_system_prompt_always_first():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o")

    messages = mock_comp.call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"


# --- adversarial ---

def test_rejected_draft_without_reason_key_does_not_crash():
    """draft missing 'reason' key — draft.get('reason') must return None gracefully."""
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o", config={"rejected_drafts": [{"standup": "bad draft"}]})
    messages = mock_comp.call_args.kwargs["messages"]
    assert messages[3]["role"] == "user"
    assert "Please try again" in messages[3]["content"]


def test_choices_none_raises_runtime_error():
    """response.choices = None — 'None or []' gives [], must raise RuntimeError."""
    resp = MagicMock()
    resp.choices = None
    with patch("core.summariser.litellm.completion", return_value=resp):
        with pytest.raises(RuntimeError, match="no choices"):
            generate_standup({}, "gpt-4o")


def test_litellm_exception_propagates():
    """If litellm.completion raises, the exception must bubble up unswallowed."""
    with patch("core.summariser.litellm.completion", side_effect=Exception("API timeout")):
        with pytest.raises(Exception, match="API timeout"):
            generate_standup({}, "gpt-4o")


def test_max_tokens_1500_passed_to_litellm():
    with patch("core.summariser.litellm.completion", return_value=_litellm_response("ok")) as mock_comp:
        generate_standup({}, "gpt-4o")
    assert mock_comp.call_args.kwargs["max_tokens"] == 1500
