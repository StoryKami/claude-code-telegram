"""Tests for /cost command and session cost accumulation."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    audit = MagicMock()
    audit.log_command = AsyncMock()
    storage = MagicMock()
    storage.save_claude_interaction = AsyncMock()
    return {
        "claude_integration": MagicMock(),
        "storage": storage,
        "security_validator": MagicMock(),
        "rate_limiter": MagicMock(),
        "audit_logger": audit,
    }


# ---------------------------------------------------------------------------
# _build_cost_message
# ---------------------------------------------------------------------------

def test_build_cost_message_format():
    """`_build_cost_message` shows cost and token breakdown."""
    from src.bot.handlers.command import _build_cost_message

    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": 100,
    }
    text = _build_cost_message(0.0123, usage)

    assert "$0.0123" in text
    assert "1,800" in text  # total = 1000+500+200+100
    assert "1,000" in text  # input
    assert "500" in text    # output
    assert "200" in text    # cache read
    assert "100" in text    # cache write


def test_build_cost_message_zero_usage():
    """`_build_cost_message` handles all-zero usage gracefully."""
    from src.bot.handlers.command import _build_cost_message

    text = _build_cost_message(0.0, {})
    assert "$0.0000" in text
    assert "0" in text


# ---------------------------------------------------------------------------
# /cost command handler
# ---------------------------------------------------------------------------

async def test_cost_no_usage():
    """/cost with no session data replies with guidance message."""
    from src.bot.handlers.command import cost_command

    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"audit_logger": None}

    await cost_command(update, context)

    update.message.reply_text.assert_called_once()
    assert "No usage data" in update.message.reply_text.call_args[0][0]


async def test_cost_shows_accumulated_data():
    """/cost shows accumulated cost and usage when data exists."""
    from src.bot.handlers.command import cost_command

    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {
        "session_cost_usd": 0.0456,
        "session_total_usage": {
            "input_tokens": 2000,
            "output_tokens": 800,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 200,
        },
    }
    context.bot_data = {"audit_logger": None}

    await cost_command(update, context)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "$0.0456" in text
    assert "2,000" in text


async def test_cost_logs_audit():
    """/cost logs the command via audit_logger."""
    from src.bot.handlers.command import cost_command

    audit = MagicMock()
    audit.log_command = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {
        "session_cost_usd": 0.01,
        "session_total_usage": {"input_tokens": 100, "output_tokens": 50},
    }
    context.bot_data = {"audit_logger": audit}

    await cost_command(update, context)

    audit.log_command.assert_called_once_with(42, "cost", [], True)


# ---------------------------------------------------------------------------
# Cost accumulation in agentic_text
# ---------------------------------------------------------------------------

def _make_update(tmp_dir):
    update = MagicMock()
    update.effective_user.id = 42
    update.effective_user.first_name = "Bob"
    update.message.text = "Hello"

    chat = MagicMock()
    chat.type = "private"
    chat.id = 99
    chat.send_action = AsyncMock()
    update.message.chat = chat
    update.message.message_thread_id = None
    update.message.reply_text = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    update.effective_chat = chat
    update.effective_message = update.message
    return update


def _make_context(deps, agentic_settings, tmp_dir):
    context = MagicMock()
    context.user_data = {"current_directory": str(tmp_dir)}
    context.bot_data = {k: v for k, v in deps.items()}
    context.bot_data["settings"] = agentic_settings
    context.bot_data["rate_limiter"] = None
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


async def test_agentic_text_accumulates_cost(agentic_settings, deps, tmp_dir):
    """agentic_text accumulates session_cost_usd after each turn."""
    from src.claude.sdk_integration import ClaudeResponse

    mock_response = MagicMock(spec=ClaudeResponse)
    mock_response.session_id = "sess-abc"
    mock_response.response = "OK"
    mock_response.content = "OK"
    mock_response.working_directory = str(tmp_dir)
    mock_response.cost = 0.0123
    mock_response.usage = {
        "input_tokens": 500,
        "output_tokens": 100,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(return_value=mock_response)
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_update(tmp_dir)
    context = _make_context(deps, agentic_settings, tmp_dir)

    await orchestrator.agentic_text(update, context)

    assert context.user_data.get("session_cost_usd") == pytest.approx(0.0123)


async def test_agentic_text_accumulates_tokens(agentic_settings, deps, tmp_dir):
    """agentic_text accumulates session_total_usage tokens across turns."""
    from src.claude.sdk_integration import ClaudeResponse

    mock_response = MagicMock(spec=ClaudeResponse)
    mock_response.session_id = "sess-abc"
    mock_response.response = "OK"
    mock_response.content = "OK"
    mock_response.working_directory = str(tmp_dir)
    mock_response.cost = 0.005
    mock_response.usage = {
        "input_tokens": 300,
        "output_tokens": 150,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 10,
    }

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(return_value=mock_response)
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_update(tmp_dir)
    context = _make_context(deps, agentic_settings, tmp_dir)
    # Pre-populate with existing accumulated data
    context.user_data["session_cost_usd"] = 0.010
    context.user_data["session_total_usage"] = {
        "input_tokens": 200,
        "output_tokens": 100,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 5,
    }

    await orchestrator.agentic_text(update, context)

    total = context.user_data["session_total_usage"]
    assert total["input_tokens"] == 500   # 200 + 300
    assert total["output_tokens"] == 250  # 100 + 150
    assert total["cache_read_input_tokens"] == 80    # 30 + 50
    assert total["cache_creation_input_tokens"] == 15  # 5 + 10
    assert context.user_data["session_cost_usd"] == pytest.approx(0.015)


async def test_agentic_new_resets_cost(agentic_settings, deps):
    """agentic_new resets session_cost_usd and session_total_usage."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)

    update = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {
        "claude_session_id": "old",
        "session_cost_usd": 1.23,
        "session_total_usage": {"input_tokens": 9999},
    }

    await orchestrator.agentic_new(update, context)

    assert context.user_data["session_cost_usd"] == 0.0
    assert context.user_data["session_total_usage"] == {}
