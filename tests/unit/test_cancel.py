"""Tests for /cancel command, Stop/Stop-All buttons, and interrupt mechanism."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.orchestrator import MessageOrchestrator
from src.config import create_test_config


# ---------------------------------------------------------------------------
# ClaudeSDKManager.interrupt()
# ---------------------------------------------------------------------------

async def test_interrupt_returns_false_when_no_active_client():
    """interrupt() returns False when no command is running for the user."""
    from src.claude.sdk_integration import ClaudeSDKManager
    from src.config import create_test_config

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        config = create_test_config(approved_directory=tmp)
        manager = ClaudeSDKManager(config)

        result = await manager.interrupt(user_id=42)

        assert result is False


async def test_interrupt_cancels_task_and_returns_true():
    """interrupt() cancels the active task and returns True."""
    import asyncio as _asyncio

    from src.claude.sdk_integration import ClaudeSDKManager
    from src.config import create_test_config

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        config = create_test_config(approved_directory=tmp)
        manager = ClaudeSDKManager(config)

        # Create a real task that blocks indefinitely
        async def _forever() -> None:
            await _asyncio.sleep(9999)

        task = _asyncio.create_task(_forever())
        manager._active_tasks[99] = task

        result = await manager.interrupt(user_id=99)

        assert result is True
        assert task.cancelling() > 0 or task.cancelled()


async def test_interrupt_handles_process_terminate_failure():
    """interrupt() returns True even if subprocess terminate() raises."""
    from src.claude.sdk_integration import ClaudeSDKManager
    from src.config import create_test_config

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        config = create_test_config(approved_directory=tmp)
        manager = ClaudeSDKManager(config)

        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock(side_effect=OSError("process already dead"))
        manager._active_processes[7] = mock_proc
        manager._active_clients[7] = MagicMock()

        result = await manager.interrupt(user_id=7)

        assert result is True


# ---------------------------------------------------------------------------
# ClaudeIntegration.interrupt()
# ---------------------------------------------------------------------------

async def test_facade_interrupt_delegates_to_sdk_manager():
    """ClaudeIntegration.interrupt() delegates to sdk_manager.interrupt()."""
    from src.claude.facade import ClaudeIntegration
    from src.config import create_test_config

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        config = create_test_config(approved_directory=tmp)
        integration = ClaudeIntegration(config)

        integration.sdk_manager.interrupt = AsyncMock(return_value=True)

        result = await integration.interrupt(user_id=55)

        assert result is True
        integration.sdk_manager.interrupt.assert_called_once_with(55)


# ---------------------------------------------------------------------------
# /cancel command handler
# ---------------------------------------------------------------------------

async def test_cancel_no_active_task():
    """/cancel with no running task replies with 'No active task'."""
    from src.bot.handlers.command import cancel_command

    mock_claude = MagicMock()
    mock_claude.interrupt = AsyncMock(return_value=False)

    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"claude_integration": mock_claude, "audit_logger": None}

    await cancel_command(update, context)

    update.message.reply_text.assert_called_once()
    assert "No active task" in update.message.reply_text.call_args[0][0]


async def test_cancel_active_task_interrupted():
    """/cancel with running task sends '🛑 Cancelled.' reply."""
    from src.bot.handlers.command import cancel_command

    mock_claude = MagicMock()
    mock_claude.interrupt = AsyncMock(return_value=True)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"claude_integration": mock_claude, "audit_logger": None}

    await cancel_command(update, context)

    update.message.reply_text.assert_called_once()
    assert "Cancelled" in update.message.reply_text.call_args[0][0]
    mock_claude.interrupt.assert_called_once_with(42)


async def test_cancel_logs_audit():
    """/cancel logs to audit_logger."""
    from src.bot.handlers.command import cancel_command

    mock_claude = MagicMock()
    mock_claude.interrupt = AsyncMock(return_value=True)

    audit = MagicMock()
    audit.log_command = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 7
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"claude_integration": mock_claude, "audit_logger": audit}

    await cancel_command(update, context)

    audit.log_command.assert_called_once_with(7, "cancel", [], True)


async def test_cancel_no_integration():
    """/cancel without claude_integration replies with error."""
    from src.bot.handlers.command import cancel_command

    update = MagicMock()
    update.effective_user.id = 1
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"claude_integration": None, "audit_logger": None}

    await cancel_command(update, context)

    update.message.reply_text.assert_called_once()
    assert "❌" in update.message.reply_text.call_args[0][0]


# ---------------------------------------------------------------------------
# Stop / Stop All inline buttons (_agentic_callback)
# ---------------------------------------------------------------------------

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
    mock_claude = MagicMock()
    mock_claude.interrupt = AsyncMock(return_value=True)
    return {
        "claude_integration": mock_claude,
        "storage": MagicMock(),
        "security_validator": MagicMock(),
        "rate_limiter": MagicMock(),
        "audit_logger": audit,
    }


def _make_callback(data: str, user_id: int) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()
    query.from_user.id = user_id
    update = MagicMock()
    update.callback_query = query
    return update


async def test_stop_button_interrupts_and_removes_markup(agentic_settings, deps, tmp_dir):
    """Stop button calls interrupt() and removes inline keyboard."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_callback("stop:42", user_id=42)

    context = MagicMock()
    context.user_data = {}
    context.bot_data = deps

    await orchestrator._agentic_callback(update, context)

    deps["claude_integration"].interrupt.assert_awaited_once_with(42)
    update.callback_query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    update.callback_query.message.reply_text.assert_awaited_once()
    assert "Stopped" in update.callback_query.message.reply_text.call_args[0][0]
    # stop_all_until should NOT be set
    assert "stop_all_until" not in context.user_data


async def test_stop_all_button_sets_timestamp(agentic_settings, deps, tmp_dir):
    """Stop All button sets stop_all_until timestamp."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)
    update = _make_callback("stop_all:42", user_id=42)

    context = MagicMock()
    context.user_data = {}
    context.bot_data = deps

    before = datetime.now(timezone.utc)
    await orchestrator._agentic_callback(update, context)
    after = datetime.now(timezone.utc)

    deps["claude_integration"].interrupt.assert_awaited_once_with(42)
    assert "stop_all_until" in context.user_data
    ts = context.user_data["stop_all_until"]
    assert before <= ts <= after
    assert "dropped" in update.callback_query.message.reply_text.call_args[0][0].lower()


async def test_stop_button_rejected_for_wrong_user(agentic_settings, deps, tmp_dir):
    """Stop button shows alert if pressed by a different user."""
    orchestrator = MessageOrchestrator(agentic_settings, deps)
    # Button owner is 42, but pressed by 99
    update = _make_callback("stop:42", user_id=99)

    context = MagicMock()
    context.user_data = {}
    context.bot_data = deps

    await orchestrator._agentic_callback(update, context)

    update.callback_query.answer.assert_awaited_once_with(
        "This button is not for you.", show_alert=True
    )
    deps["claude_integration"].interrupt.assert_not_awaited()


async def test_stop_all_drops_queued_message(agentic_settings, deps, tmp_dir):
    """agentic_text silently drops messages within the stop_all grace period."""
    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock()
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.text = "Hello"
    update.message.date = datetime.now(timezone.utc)
    update.message.reply_text = AsyncMock()
    chat = MagicMock()
    chat.type = "private"
    chat.send_action = AsyncMock()
    update.message.chat = chat
    update.effective_chat = chat

    context = MagicMock()
    context.user_data = {
        # Set 2 seconds ago — within 10s grace period
        "stop_all_until": datetime.now(timezone.utc) - timedelta(seconds=2),
    }
    context.bot_data = deps
    context.bot_data["settings"] = agentic_settings
    context.bot_data["rate_limiter"] = None

    await orchestrator.agentic_text(update, context)

    mock_claude.run_command.assert_not_awaited()
    update.message.reply_text.assert_not_called()


async def test_stop_all_clears_flag_for_newer_messages(agentic_settings, deps, tmp_dir):
    """agentic_text clears stop_all_until after the grace period expires."""
    mock_response = MagicMock()
    mock_response.session_id = "s1"
    mock_response.content = "hi"
    mock_response.response = "hi"
    mock_response.working_directory = str(tmp_dir)
    mock_response.cost = 0.0
    mock_response.usage = {}

    mock_claude = MagicMock()
    mock_claude.run_command = AsyncMock(return_value=mock_response)
    deps["claude_integration"] = mock_claude

    orchestrator = MessageOrchestrator(agentic_settings, deps)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.text = "Hello"
    # stop_all was set 15 seconds ago — grace period (10s) expired
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=15)
    update.message.date = datetime.now(timezone.utc)
    update.message.reply_text = AsyncMock(return_value=MagicMock(
        edit_text=AsyncMock(), edit_reply_markup=AsyncMock(), delete=AsyncMock()
    ))
    update.message.message_id = 1
    chat = MagicMock()
    chat.type = "private"
    chat.id = 99
    chat.send_action = AsyncMock()
    update.message.chat = chat
    update.message.message_thread_id = None
    update.effective_chat = chat
    update.effective_message = update.message

    context = MagicMock()
    context.user_data = {
        "stop_all_until": cutoff,
        "current_directory": str(tmp_dir),
    }
    context.bot_data = {k: v for k, v in deps.items()}
    context.bot_data["settings"] = agentic_settings
    context.bot_data["rate_limiter"] = None
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    await orchestrator.agentic_text(update, context)

    # Flag should be cleared
    assert "stop_all_until" not in context.user_data
    # Claude was called
    mock_claude.run_command.assert_awaited_once()
