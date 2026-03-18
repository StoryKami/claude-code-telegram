"""Tests for /context command and context usage tracking."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers.command import _build_context_message, context_command
from src.bot.orchestrator import MessageOrchestrator
from src.config import create_test_config


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def agentic_settings(tmp_dir):
    return create_test_config(approved_directory=str(tmp_dir), agentic_mode=True)


@pytest.fixture
def deps():
    return {
        "claude_integration": MagicMock(),
        "storage": MagicMock(),
        "security_validator": MagicMock(),
        "rate_limiter": MagicMock(),
        "audit_logger": MagicMock(),
    }


# --- _build_context_message unit tests ---


def test_build_context_message_format():
    """_build_context_message returns correctly formatted text."""
    usage = {
        "input_tokens": 10_000,
        "cache_read_input_tokens": 5_000,
        "cache_creation_input_tokens": 2_000,
        "output_tokens": 3_000,
    }
    text = _build_context_message(usage, session_turns=4)

    assert "Context Usage" in text
    assert "20,000" in text  # total_used = 10000+5000+2000+3000
    assert "200,000" in text
    assert "10.0%" in text
    assert "10,000" in text  # input_tokens
    assert "3,000" in text   # output_tokens
    assert "5,000" in text   # cache_read
    assert "Turns:     4" in text


def test_build_context_message_no_warning_below_75():
    """No warning shown when usage is below 75%."""
    usage = {
        "input_tokens": 100_000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
    }
    text = _build_context_message(usage, session_turns=1)

    assert "⚠️" not in text


def test_build_context_message_bar_filled():
    """Progress bar reflects usage percentage."""
    usage = {
        "input_tokens": 100_000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
    }
    text = _build_context_message(usage, session_turns=1)

    # 50% → 5 filled blocks
    assert "▓▓▓▓▓░░░░░" in text


# --- context_command handler tests ---


async def test_context_no_usage():
    """No last_usage in user_data returns guidance message."""
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"audit_logger": None}

    await context_command(update, context)

    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args.args[0]
    assert "No context data yet" in call_text


async def test_context_shows_usage():
    """When last_usage is set, /context returns formatted token info."""
    usage = {
        "input_tokens": 50_000,
        "cache_read_input_tokens": 10_000,
        "cache_creation_input_tokens": 0,
        "output_tokens": 5_000,
    }

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {"last_usage": usage, "session_turns": 3}
    context.bot_data = {"audit_logger": None}

    await context_command(update, context)

    update.message.reply_text.assert_called_once()
    call_kwargs = update.message.reply_text.call_args
    text = call_kwargs.args[0]
    assert "Context Usage" in text
    assert "65,000" in text  # 50000+10000+5000
    assert "Turns:     3" in text
    assert call_kwargs.kwargs.get("parse_mode") == "HTML"


async def test_context_warns_above_75pct():
    """When context usage ≥ 75%, a compact warning is shown."""
    usage = {
        "input_tokens": 160_000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
    }

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {"last_usage": usage, "session_turns": 10}
    context.bot_data = {"audit_logger": None}

    await context_command(update, context)

    text = update.message.reply_text.call_args.args[0]
    assert "⚠️" in text
    assert "/compact" in text


async def test_context_logs_audit():
    """context_command calls audit_logger when present."""
    usage = {
        "input_tokens": 1_000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 500,
    }

    update = MagicMock()
    update.effective_user.id = 99
    update.message.reply_text = AsyncMock()

    audit_logger = MagicMock()
    audit_logger.log_command = AsyncMock()

    context = MagicMock()
    context.user_data = {"last_usage": usage, "session_turns": 1}
    context.bot_data = {"audit_logger": audit_logger}

    await context_command(update, context)

    audit_logger.log_command.assert_awaited_once_with(99, "context", [], True)


# --- orchestrator integration tests ---


async def test_agentic_text_stores_usage(agentic_settings, deps):
    """After agentic_text, last_usage and session_turns are stored in user_data."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)

    mock_response = MagicMock()
    mock_response.session_id = "session-xyz"
    mock_response.content = "Hello!"
    mock_response.tools_used = []
    mock_response.usage = {
        "input_tokens": 500,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 50,
        "output_tokens": 200,
    }

    claude_integration = AsyncMock()
    claude_integration.run_command = AsyncMock(return_value=mock_response)

    update = MagicMock()
    update.effective_user.id = 1
    update.message.text = "test"
    update.message.message_id = 1
    update.message.chat.send_action = AsyncMock()
    update.message.reply_text = AsyncMock()

    progress_msg = AsyncMock()
    progress_msg.delete = AsyncMock()
    update.message.reply_text.return_value = progress_msg

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {
        "settings": agentic_settings,
        "claude_integration": claude_integration,
        "storage": None,
        "rate_limiter": None,
        "audit_logger": None,
    }

    await orchestrator.agentic_text(update, context)

    assert context.user_data.get("last_usage") == mock_response.usage
    assert context.user_data.get("session_turns") == 1


async def test_agentic_text_increments_turns(agentic_settings, deps):
    """session_turns increments on each successful agentic_text call."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)

    mock_response = MagicMock()
    mock_response.session_id = "session-xyz"
    mock_response.content = "Hello!"
    mock_response.tools_used = []
    mock_response.usage = {"input_tokens": 100, "output_tokens": 50}

    claude_integration = AsyncMock()
    claude_integration.run_command = AsyncMock(return_value=mock_response)

    update = MagicMock()
    update.effective_user.id = 1
    update.message.text = "test"
    update.message.message_id = 1
    update.message.chat.send_action = AsyncMock()
    update.message.reply_text = AsyncMock()

    progress_msg = AsyncMock()
    progress_msg.delete = AsyncMock()
    update.message.reply_text.return_value = progress_msg

    context = MagicMock()
    context.user_data = {"session_turns": 5}
    context.bot_data = {
        "settings": agentic_settings,
        "claude_integration": claude_integration,
        "storage": None,
        "rate_limiter": None,
        "audit_logger": None,
    }

    await orchestrator.agentic_text(update, context)

    assert context.user_data.get("session_turns") == 6


async def test_agentic_new_resets_turns(agentic_settings, deps):
    """/new resets session_turns to 0."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)

    update = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {
        "claude_session_id": "old-session",
        "session_turns": 7,
    }

    await orchestrator.agentic_new(update, context)

    assert context.user_data["claude_session_id"] is None
    assert context.user_data["session_turns"] == 0
