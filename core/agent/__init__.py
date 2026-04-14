"""Claude-driven agent package.

This package replaces the old 6-stage ML pipeline. The agent is a Claude Code
subprocess (via claude-agent-sdk) that calls tools from the bus in
`core.agent.tools` to decide what to trade, when, and why.

Phase 1 skeleton: these modules exist but the agent is off by default.
"""
