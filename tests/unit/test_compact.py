"""Tests for /compact command and PreCompact hook."""

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
# /compact command handler
# ---------------------------------------------------------------------------

async def test_compact_no_session():
    """/compact with no active session replies with 'No active session'."""
    from src.bot.handlers.command import compact_command

    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"audit_logger": None, "claude_integration": MagicMock()}

    await compact_command(update, context)

    update.message.reply_text.assert_called_once()
    assert "No active session" in update.message.reply_text.call_args[0][0]


async def test_compact_calls_sdk_and_resets_count():
    """/compact sends /compact prompt to SDK and resets session_message_count."""
    from src.bot.handlers.command import compact_command

    mock_response = MagicMock()
    mock_response.session_id = "new-session-456"

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(return_value=mock_response)

    mock_msg = MagicMock()
    mock_msg.edit_text = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock(return_value=mock_msg)

    context = MagicMock()
    context.user_data = {"claude_session_id": "old-session-123", "session_message_count": 15}
    context.bot_data = {"audit_logger": None, "claude_integration": mock_claude}

    await compact_command(update, context)

    mock_claude.run_command.assert_called_once()
    call_kwargs = mock_claude.run_command.call_args.kwargs
    assert call_kwargs["prompt"] == "/compact"
    assert call_kwargs["session_id"] == "old-session-123"

    assert context.user_data["claude_session_id"] == "new-session-456"
    assert context.user_data["session_message_count"] == 0


async def test_compact_sdk_failure_shows_error():
    """/compact shows error message when SDK raises."""
    from src.bot.handlers.command import compact_command

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(side_effect=Exception("SDK error"))

    mock_msg = MagicMock()
    mock_msg.edit_text = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock(return_value=mock_msg)

    context = MagicMock()
    context.user_data = {"claude_session_id": "sess-123"}
    context.bot_data = {"audit_logger": None, "claude_integration": mock_claude}

    await compact_command(update, context)

    mock_msg.edit_text.assert_called_once()
    assert "❌" in mock_msg.edit_text.call_args[0][0]


# ---------------------------------------------------------------------------
# PreCompact hook wiring in agentic_text
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


async def test_agentic_text_passes_pre_compact_hook(agentic_settings, deps, tmp_dir):
    """agentic_text passes PreCompact hook to run_command."""
    mock_response = MagicMock()
    mock_response.session_id = "sess-abc"
    mock_response.response = "OK"
    mock_response.working_directory = str(tmp_dir)
    mock_response.cost_usd = 0.0

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(return_value=mock_response)
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_update(tmp_dir)
    context = _make_context(deps, agentic_settings, tmp_dir)

    await orchestrator.agentic_text(update, context)

    mock_claude.run_command.assert_called_once()
    call_kwargs = mock_claude.run_command.call_args.kwargs
    assert "hooks" in call_kwargs
    assert "PreCompact" in call_kwargs["hooks"]


async def test_pre_compact_hook_sends_notification_on_auto(agentic_settings, deps, tmp_dir):
    """PreCompact hook sends Telegram message when trigger is 'auto'."""
    captured_hooks = {}

    mock_response = MagicMock()
    mock_response.session_id = "sess-abc"
    mock_response.response = "OK"
    mock_response.working_directory = str(tmp_dir)
    mock_response.cost_usd = 0.0

    async def capture_run(**kwargs):
        captured_hooks.update(kwargs.get("hooks", {}))
        return mock_response

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(side_effect=capture_run)
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_update(tmp_dir)
    context = _make_context(deps, agentic_settings, tmp_dir)

    await orchestrator.agentic_text(update, context)

    assert "PreCompact" in captured_hooks
    hook_fn = captured_hooks["PreCompact"][0].hooks[0]
    await hook_fn({"trigger": "auto"}, None, {})

    context.bot.send_message.assert_called_once()
    call_kwargs = context.bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 99
    assert "Auto-compact" in call_kwargs["text"]


async def test_pre_compact_hook_silent_on_manual(agentic_settings, deps, tmp_dir):
    """PreCompact hook does NOT send notification when trigger is 'manual'."""
    captured_hooks = {}

    mock_response = MagicMock()
    mock_response.session_id = "sess-abc"
    mock_response.response = "OK"
    mock_response.working_directory = str(tmp_dir)
    mock_response.cost_usd = 0.0

    async def capture_run(**kwargs):
        captured_hooks.update(kwargs.get("hooks", {}))
        return mock_response

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(side_effect=capture_run)
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_update(tmp_dir)
    context = _make_context(deps, agentic_settings, tmp_dir)

    await orchestrator.agentic_text(update, context)

    hook_fn = captured_hooks["PreCompact"][0].hooks[0]
    await hook_fn({"trigger": "manual"}, None, {})

    context.bot.send_message.assert_not_called()
