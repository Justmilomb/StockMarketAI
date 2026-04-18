"""Reusable UI primitives shared by panels and dialogs.

Each primitive is a thin subclass of a standard Qt widget with the
correct fonts, colours, and spacing baked in. Using these instead of
hardcoded QSS in every panel keeps the visual language consistent and
makes future restyles a single-file change.
"""
from desktop.widgets.primitives.kicker import Kicker
from desktop.widgets.primitives.card import Card
from desktop.widgets.primitives.button import PrimaryButton, SecondaryButton, GhostButton
from desktop.widgets.primitives.status_dot import StatusDot
from desktop.widgets.primitives.sentiment_bar import SentimentBar
from desktop.widgets.primitives.divider import HDivider, VDivider
from desktop.widgets.primitives.grain_overlay import GrainOverlay
from desktop.widgets.primitives.underline_input import UnderlineInput
from desktop.widgets.primitives.segmented import Segmented

__all__ = [
    "Kicker",
    "Card",
    "PrimaryButton",
    "SecondaryButton",
    "GhostButton",
    "StatusDot",
    "SentimentBar",
    "HDivider",
    "VDivider",
    "GrainOverlay",
    "UnderlineInput",
    "Segmented",
]
