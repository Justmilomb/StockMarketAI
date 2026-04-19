# Colour Palette

Both brands share a dark-first aesthetic with a single neon accent each. Neither brand uses light mode.

---

## certified random

| Token | Hex | Use |
|---|---|---|
| `bg` | `#07070f` | Canvas, primary background |
| `bg-raised` | `#0c0c1a` | Cards, elevated surfaces |
| `accent` | `#c4ff3c` | Seal, rules, italic accent words |
| `accent-dim` | `rgba(196, 255, 60, 0.1)` | Subtle wash behind the seal |
| `text` | `#edeae4` | Primary type (warm white, not pure) |
| `text-mid` | `#8a8a9e` | Secondary type, captions |
| `text-dim` | `#48485c` | Metadata, labels |
| `border` | `rgba(255, 255, 255, 0.08)` | Hairline rules |

The background is **not** pure black. The slight warm cast (`#07070f`) is what separates CR from blank at a glance.

---

## blank

| Token | Hex | Use |
|---|---|---|
| `bg` | `#000000` | Canvas, primary background |
| `bg-raised` | `#050505` | Cards, elevated surfaces |
| `accent` | `#00ff87` | Rules, italic accent, up-ticks |
| `accent-dim` | `rgba(0, 255, 135, 0.1)` | Wash |
| `text` | `#ffffff` | Primary type (pure white) |
| `text-mid` | `rgba(255, 255, 255, 0.6)` | Secondary |
| `text-dim` | `rgba(255, 255, 255, 0.32)` | Metadata, tickers |
| `border` | `rgba(255, 255, 255, 0.08)` | Hairline rules |

Blank is **pure** black and **pure** white. No warmth. It's a trading terminal — it should feel clinical.

---

## Usage rules

1. **The accent is a highlight, not a fill.** Never fill buttons, cards, or backgrounds with the accent. It lives on type, rules, and thin graphic elements only.
2. **No gradients.** Flat only. No accent → dark fades, no radial washes.
3. **No mixing accents.** CR green never appears in blank artwork. Blank green never appears in CR artwork.
4. **Red is for losses only.** Neither brand uses red as a primary colour. In blank, `#ff3860` may appear in ticker tape for negative percentages. Never anywhere else.

---

## Accessibility

All type/background combinations pass WCAG AA:

- blank: `#ffffff` on `#000000` → 21:1
- blank: `#00ff87` on `#000000` → 16.7:1
- CR: `#edeae4` on `#07070f` → 17.9:1
- CR: `#c4ff3c` on `#07070f` → 16.2:1

Secondary text (`text-mid` / `text-dim`) passes AA for UI elements and body copy but not AAA — reserve for metadata only.

---

2026.04
