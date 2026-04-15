"""Hide subprocess console windows on Windows.

The Claude Agent SDK launches the AI engine via ``anyio.open_process``
which on Windows pops a black console window for every spawn. This is
visible to the user as flashing terminals every time the supervisor
wakes or the chat worker sends a message.

The fix: monkey-patch both ``anyio.open_process`` and
``subprocess.Popen.__init__`` to inject ``CREATE_NO_WINDOW`` into the
subprocess creation flags whenever the caller didn't set one.

This module must be imported *before* ``claude_agent_sdk`` so the
patched launchers are in place by the time the SDK opens its first
subprocess. Importing it on non-Windows is a no-op.
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    import subprocess

    import anyio

    _CREATE_NO_WINDOW = 0x08000000

    _orig_open_process = anyio.open_process

    async def _patched_open_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
        return await _orig_open_process(*args, **kwargs)

    anyio.open_process = _patched_open_process  # type: ignore[assignment]

    _orig_popen_init = subprocess.Popen.__init__

    def _patched_popen_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
        _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_popen_init  # type: ignore[method-assign]
