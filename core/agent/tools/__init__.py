"""Tool bus — stateless, typed wrappers around existing modules.

Each tool module exposes a handful of functions that the agent can call
via MCP. Wrappers do no state caching; every read is fresh from the
underlying source (broker, yfinance, scraper db, etc).
"""
