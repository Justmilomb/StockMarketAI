# Brand Guidelines

Single reference for the two brands: **blank** and **certified random**. One voice, two marks, one aesthetic.

---

## Voice

Quiet, confident, editorial. Lowercase names. No exclamation marks. No emoji. Full sentences are fine; fragments are fine. Marketing copy reads like a note from a smart friend, not a pitch deck.

Short straplines in **Instrument Serif italic** are the signature flourish:

- certified random → *"we build software."* ⟶ quietly, quickly, well.
- blank → *"never look up."* ⟶ place the trade.

The italic fragment is always the poetic half. The sans fragment is the operational half.

---

## Logo — certified random

The mark is a circular **seal**: "CR" in Syne 800 centred, a dashed outer ring with "CERTIFIED RANDOM STUDIOS • EST. 2026 •" rotating around it, a short rule, and "STUDIOS" mono below.

| Variant | Purpose |
|---|---|
| **cr-badge.svg** | Default. Use wherever one mark is needed. |
| **cr-wordmark.svg** | Type-only. Nav bars, UI chrome, video end-cards. |
| **cr-lockup.svg** | Formal sign-off. Wordmark + seal + strapline + domain. Decks, press kits, about pages. |
| **cr-logomark.svg** | Lime tile with "CR" for sub-64px contexts where the seal loses legibility. |
| **cr-avatar.svg** | Social avatars. Seal on deep dark, circular-safe. |

### Wordmark treatment

"certified" in Syne 800, white. "random" in **Instrument Serif 400 italic**, lime. The italic word is the poetic accent. Never italicise "certified". Never set "random" in sans.

### Don'ts

- Don't rotate the seal except in the provided "spinning" variant.
- Don't recolour the seal. It's always lime on deep dark.
- Don't put the seal on pure black — it must read on `#07070f`.
- Don't add a badge to blank (blank is wordmark-only).

---

## Logo — blank

The mark is the wordmark: **"blank"** in Outfit 700 with a neon green rule beneath. That's the whole system. No badge, no shield, no icon.

| Variant | Purpose |
|---|---|
| **blank-wordmark.svg** | Default. Wordmark only, transparent. |
| **blank-wordmark-on-black.svg** | Wordmark on `#000000`. |
| **blank-wordmark-on-white.svg** | Inverse — black wordmark on white. |
| **blank-lockup.svg** | Wordmark + "AI TRADING TERMINAL" mono strapline. |
| **blank-logomark.svg** | Lowercase "b" with rule. Sub-64px contexts. |
| **blank-app-icon.svg** | Wordmark fills a square tile. |

### The green rule

Every use of the rule follows one formula:

```
gap       = 0.12 × font-size   (distance from text baseline to top of rule)
thickness = 0.04 × font-size
width     = 2.05 × font-size   (for "blank"; 0.75 × font-size for "b")
```

It is centred under the word when the word is centred; left-aligned with the word when the word is left-aligned. This is non-negotiable — the rule defines blank's proportion.

### Don'ts

- Don't change the rule colour, thickness, or spacing.
- Don't set "blank" in Syne or any serif.
- Don't capitalise "blank". Ever.
- Don't put blank on anything other than pure black or pure white.

---

## Colour

Dark-first. Neither brand has a light mode. The accent is never used as a large fill — always on type, rules, and thin graphic elements.

### certified random
- background `#07070f` (deep dark, slight warm cast)
- accent `#c4ff3c` (lime)
- text `#edeae4` (warm white)

### blank
- background `#000000` (pure black)
- accent `#00ff87` (neon green)
- text `#ffffff` (pure white)

See `COLOUR_PALETTE.md` for the full scale.

---

## Typography

See `TYPOGRAPHY.md` for the full spec. Summary:

| Role | CR | Blank |
|---|---|---|
| Display | Syne 800 | Outfit 700 |
| Body | Outfit 300–500 | Outfit 300–500 |
| Mono / labels | JetBrains Mono 400 | JetBrains Mono 400 |
| Editorial italic | Instrument Serif 400 italic | Instrument Serif 400 italic |

The italic is shared across both brands. It's the connective tissue — the thing that makes the two feel like one studio.

---

## Spacing + corners

- **Corners:** 0 by default. The favicon tile is the one exception (4px) to survive browser-chrome rendering. No rounded cards, no rounded buttons in marketing.
- **Safe area for every mark:** padding equal to 1× the mark's "x-height" on all four sides. Don't crowd.
- **Badge collision rule:** on any composite asset, the CR seal sits in its own column. Wordmark and seal never overlap.

---

## Imagery

Placeholder only. If you need a photograph, use a high-contrast monochrome image with a single accent pull. If you need iconography, don't — use type.

---

2026.04 · London
