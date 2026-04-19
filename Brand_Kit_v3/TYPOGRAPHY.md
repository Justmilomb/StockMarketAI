# Typography

Font files live in `Fonts/`. Every family is included as TTF. All are also on Google Fonts.

---

## The system, at a glance

| Role | CR | Blank | Both |
|---|---|---|---|
| Display | **Syne 800** | **Outfit 700** | — |
| Body | — | — | **Outfit 300 / 400 / 500** |
| Mono / labels | — | — | **JetBrains Mono 400** |
| Editorial italic | — | — | **Instrument Serif 400 italic** |

The italic (Instrument Serif) is the connective tissue — it appears in both brands and is the reason they feel like one studio.

---

## certified random

### Display — Syne 800

Used for the wordmark, "CR" in the seal, and large headlines. Syne is chunky, geometric, slightly eccentric — the studio's "personality" lives here.

- letter-spacing: `-0.04em` at display sizes, `0` below 40px
- never set in Syne Regular in the kit — if you need a lighter weight, switch to Outfit

### Body — Outfit 300/400/500

Same family as blank. Keeps the studio aligned with its products. Never use Outfit 700 for CR body copy (700 is reserved for blank's display).

### Editorial italic — Instrument Serif italic

The signature accent word. Used on:
- "random" in the wordmark
- straplines like *"we build software."*
- callouts like *"est. 2026"*

Always in the accent colour (`#c4ff3c`). Always italic. Always in moderation — at most one italic phrase per composition.

### Mono — JetBrains Mono 400

Kickers, metadata, domain URLs, labels. Always `letter-spacing: 0.3em` and uppercase for kickers; `0.1em` and mixed case for inline mono.

---

## blank

### Display — Outfit 700

"blank" is always set in Outfit 700 with negative tracking (`-0.04em`). This is the wordmark.

- Outfit 700 is reserved for the wordmark and product names — don't use it for generic headings.
- Never italicise "blank".

### Body — Outfit 300/400/500

Same scale as CR.

### Editorial italic — Instrument Serif italic

Appears in straplines:
- *"never look up."*
- *"place the trade."*
- *"a product of certified random."*

Always in the accent colour. Always short — one line max.

### Mono — JetBrains Mono 400

Tickers, percentages, kickers, metadata. Tabular figures are on by default via OpenType feature `tnum`.

---

## Scale

The catalogue uses a single fluid scale driven by `clamp()`. For static assets the values land roughly at:

| Level | Size | Use |
|---|---|---|
| Display XL | 280–360px | YT banners, hero OG cards |
| Display L | 180–240px | Secondary OG, business cards |
| Display M | 100–140px | Section heads in catalogue |
| Title | 44–72px | Page titles |
| Body L | 20–28px | Intro paragraphs |
| Body | 14–16px | Running copy |
| Kicker | 11–14px | Mono labels, uppercase, tracked |

---

## The green rule (blank only)

Every time the "blank" wordmark is used, the rule beneath it follows:

```
gap       = 0.12 × font-size
thickness = 0.04 × font-size
width     = 2.05 × font-size   (0.75 × font-size for the "b" logomark)
```

If the word is centre-anchored, the rule is centred. If left, left. The rule is always the accent colour. Never a different shape. Never a gradient. Never absent.

---

## Pairings that work

- **Syne 800 + Outfit 300** — CR display + CR body. The weight contrast does the work.
- **Outfit 700 + Instrument Serif italic** — blank wordmark + strapline. The tonal contrast does the work.
- **Syne 800 + Instrument Serif italic** — "certified *random*" in the wordmark. Signature move.
- **Outfit 700 + JetBrains Mono kicker** — blank lockup. Always kicker ABOVE the wordmark, never beside it.

---

## Don'ts

- Don't mix Syne and Outfit 700 in the same composition. It muddles which brand is speaking.
- Don't use Outfit 800 or 900. We set 700 as the ceiling; anything heavier is a different design system.
- Don't italicise generic words. The italic is for accent words only — one per composition.
- Don't use Geist in marketing. It's there for legacy internal UI.

---

2026.04
