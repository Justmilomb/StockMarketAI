"""Internal bridge to the agent SDK — single import point.

Every other module in core.agent imports from here instead of
the third-party package directly, so the package name appears
in exactly one .pyc file in the shipped binary.
"""
from __future__ import annotations

# ruff: noqa: F401 — re-exports
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    query,
    tool,
)
