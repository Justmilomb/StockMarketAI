"""Design tokens for the blank desktop app.

Mirrors ``website/assets/css/theme.css`` — single source of truth for
colours, typography, spacing, and motion. The desktop QSS is generated
from these constants so the app and the marketing site share one
palette.
"""
from __future__ import annotations


# ── Surfaces ─────────────────────────────────────────────────────────

BG_0 = "#000000"  # window / page
BG_1 = "#050505"  # panel base
BG_2 = "#0a0a0a"  # panel raised (hover, header strip)
BG_3 = "#141414"  # active / pressed

# ── Foreground text opacities ────────────────────────────────────────

FG_0 = "#ffffff"
FG_1 = "rgba(255, 255, 255, 0.60)"
FG_2 = "rgba(255, 255, 255, 0.32)"
FG_3 = "rgba(255, 255, 255, 0.14)"

# Hex fallbacks for anywhere QPainter / QColor can't take rgba strings
FG_1_HEX = "#999999"
FG_2_HEX = "#525252"
FG_3_HEX = "#242424"

# ── Accents ──────────────────────────────────────────────────────────

ACCENT = "#00ff87"               # single green accent — buy, focus, CTA
ACCENT_SOFT = "rgba(0, 255, 135, 0.55)"
ACCENT_DIM = "rgba(0, 255, 135, 0.08)"
ACCENT_BORDER = "rgba(0, 255, 135, 0.25)"
ACCENT_HEX = "#00ff87"

WARN = "#ffb020"                 # amber, used for cautions/pending
ALERT = "#ff3b3b"                # red, used for sells / errors
ALERT_DIM = "rgba(255, 59, 59, 0.10)"

# ── Borders ──────────────────────────────────────────────────────────

BORDER_0 = "rgba(255, 255, 255, 0.08)"   # hairline
BORDER_1 = "rgba(255, 255, 255, 0.16)"   # stronger hairline (hover/focus)
BORDER_0_HEX = "#141414"
BORDER_1_HEX = "#292929"

# ── Typography ───────────────────────────────────────────────────────

FONT_SANS = "'Outfit', 'Inter', 'Segoe UI', system-ui, sans-serif"
FONT_MONO = "'JetBrains Mono', 'IBM Plex Mono', 'Consolas', 'Cascadia Mono', monospace"

FONT_SANS_FAMILY = "Outfit"   # for QFont()
FONT_MONO_FAMILY = "JetBrains Mono"

# Size scale (px — QSS prefers px for pixel-perfect control)
STEP_0 = "10px"     # small caption / mono metadata
STEP_1 = "11px"     # kicker, dock titles
STEP_2 = "12px"     # default body
STEP_3 = "13px"     # table cell, chat body
STEP_4 = "14px"     # input, primary button
STEP_5 = "16px"     # emphasised body
STEP_6 = "20px"     # card title
STEP_7 = "28px"     # section heading
STEP_8 = "44px"     # hero wordmark

# Letter spacing for the tracked-out mono kicker style
TRACK_KICKER = "0.2em"
TRACK_WIDE = "0.28em"
TRACK_EXTRA = "0.32em"

# ── Motion ───────────────────────────────────────────────────────────

EASE_OUT = (0.16, 1.0, 0.3, 1.0)   # cubic-bezier
DUR_FAST = 140   # hover / focus
DUR_MED = 280    # dialog open
DUR_SLOW = 520   # banner slide


# ── Back-compat aliases ──────────────────────────────────────────────
# Panels still import these names from ``desktop.design`` — that file
# now re-exports from this one. Listed here for discoverability.

BG = BG_0
SURFACE = BG_2
TEXT = FG_0
TEXT_MID = FG_1
TEXT_DIM = FG_2
TEXT_FAINT = FG_3
GLOW = ACCENT
GLOW_SOFT = ACCENT_SOFT
GLOW_DIM = ACCENT_DIM
GLOW_BORDER = ACCENT_BORDER
RED = ALERT
AMBER = WARN
BORDER = BORDER_0
BORDER_HOVER = BORDER_1
