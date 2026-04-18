"""AI-driven agent package.

This package replaces the old 6-stage ML pipeline. The agent is an AI
subprocess (via the agent SDK) that calls tools from the bus in
`core.agent.tools` to decide what to trade, when, and why.

The very first import in this package must be ``subprocess_patch``: it
monkey-patches ``anyio.open_process`` and ``subprocess.Popen.__init__``
on Windows to hide console windows. The patch must be in place *before*
the agent SDK is imported by any submodule, otherwise the SDK binds to
the unpatched launchers and pops black terminals on every spawn.
"""
from . import subprocess_patch  # noqa: F401  — must come first
