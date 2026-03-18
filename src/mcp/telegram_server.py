"""MCP server exposing Telegram-specific tools to Claude.

Runs as a stdio transport server. The ``send_image_to_user`` tool validates
file existence and extension, then returns a success string. Actual Telegram
delivery is handled by the bot's stream callback which intercepts the tool
call.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

mcp = FastMCP("telegram")


@mcp.tool()
async def send_image_to_user(file_path: str, caption: str = "") -> str:
    """Send an image file to the Telegram user.

    Args:
        file_path: Absolute path to the image file.
        caption: Optional caption to display with the image.

    Returns:
        Confirmation string when the image is queued for delivery.
    """
    path = Path(file_path)

    if not path.is_absolute():
        return f"Error: path must be absolute, got '{file_path}'"

    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return (
            f"Error: unsupported image extension '{path.suffix}'. "
            f"Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )

    if not path.is_file():
        return f"Error: file not found: {file_path}"

    return f"Image queued for delivery: {path.name}"


@mcp.tool()
async def present_choices(
    question: str,
    choices: list[str],
    allow_custom: bool = False,
) -> str:
    """Present choices to the Telegram user as inline buttons.

    Use this tool when you want the user to pick one option from a list.
    The user will see clickable buttons in Telegram instead of having to type.

    Args:
        question: The question to display above the buttons.
        choices: List of choice strings (2-8 items). Keep each under 60 chars.
        allow_custom: If True, adds a "Type..." button so the user can type a
                      free-form response instead of picking a preset choice.

    Returns:
        Confirmation that choices were presented, or error message.
    """
    if not choices or len(choices) < 2:
        return "Error: provide at least 2 choices."
    if len(choices) > 8:
        return "Error: maximum 8 choices allowed."
    return (
        f"Choices presented to user as clickable buttons: {', '.join(choices)}. "
        "IMPORTANT: The user will see inline buttons and tap one. "
        "Their selection will arrive as a follow-up message. "
        "Do NOT ask them what they chose — just end your response here and wait."
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
