# Changelog

## v3 — 2026.04

**New**
- Instrument Serif italic accent introduced as the shared editorial voice across both brands.
- "certified random" wordmark now sets "random" in Instrument Serif italic lime.
- Blank banners now set straplines ("never look up.", "place the trade.") in Instrument Serif italic.
- `Catalogue/` — interactive HTML catalogue of every asset at every size.

**Fixed**
- **CR lockup** — seal now sits below the wordmark on its own row, ending the collision between the "random" tail and the seal on the right.
- **Blank green rule** — every instance now derives from one formula (`gap = 0.12 × fs`, `thickness = 0.04 × fs`, `width = 2.05 × fs`). Previously the rule floated at varying distances.
- **Blank YouTube channel art** — "AI TRADING TERMINAL" kicker no longer overlaps the wordmark.
- **CR wordmark vs lockup** — these were duplicates in v2. Now cleanly separated:
  - wordmark = type only, for UI chrome
  - lockup = wordmark + seal + strapline + domain, for formal sign-offs

**Changed**
- Page title on `blank.html` now uses Outfit 700 (the blank display font) instead of Syne.
- All composite assets (OG, banners, business card, email signature, YT thumbs) now reserve a dedicated badge column so the CR seal never crowds the wordmark.

## v2 — 2026.03
- Initial catalogue.
- Syne added as CR display face.

## v1 — 2026.02
- Marks only. Outfit + JetBrains Mono.
