"""MiroFish — Multi-agent market simulation for emergent price prediction.

Simulates ~1000 heterogeneous AI agents (momentum traders, mean reverters,
sentiment followers, contrarians, noise traders, etc.) that interact and
form beliefs about market direction.  Price signals emerge from agent
behaviour rather than from direct statistical prediction.

Public API:
    MiroFishOrchestrator  — top-level entry point (run simulations)
    extract_signals        — convert simulation results → ModelSignal list
"""

from mirofish.orchestrator import MiroFishOrchestrator
from mirofish.signals import extract_signal_from_aggregate, mirofish_signals_to_model_signals
from mirofish.types import MiroFishSignal, SimulationConfig

__all__ = [
    "MiroFishOrchestrator",
    "extract_signal_from_aggregate",
    "mirofish_signals_to_model_signals",
    "MiroFishSignal",
    "SimulationConfig",
]
