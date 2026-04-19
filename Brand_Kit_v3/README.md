# Brand Kit — v3

Central asset library for **certified random** and **blank**.

Two brands, one voice. Dark-first. One neon accent each. Sharp corners. Lowercase names. Quiet.

---

## Structure

```
Brand_Kit/
├── Logos/
│   ├── cr/                    certified random marks (SVG)
│   └── blank/                 blank marks (SVG)
├── Social/
│   ├── cr/                    og, twitter, linkedin, youtube, thumbs
│   └── blank/                 og, twitter, linkedin, youtube, thumbs
├── Stationery/
│   ├── cr/                    business card, email signature
│   └── blank/                 business card, email signature
├── Fonts/
│   ├── Outfit/                blank display + universal body
│   ├── Syne/                  certified random display
│   ├── JetBrainsMono/         shared mono
│   ├── InstrumentSerif/       editorial italic accent
│   └── Geist/                 legacy / internal UI
├── Catalogue/
│   ├── index.html             landing page linking both brands
│   ├── certified-random.html  full interactive asset catalogue
│   ├── blank.html             full interactive asset catalogue
│   ├── styles.css
│   ├── marks.js               source for every SVG (programmatic)
│   └── assets/                fonts + base logos referenced by catalogue
├── Brand_Guidelines.md
├── COLOUR_PALETTE.md
└── TYPOGRAPHY.md
```

---

## How to use this kit

1. **Need an asset right now?** Grab the SVG from `Logos/`, `Social/`, or `Stationery/`.
2. **Exploring the system?** Open `Catalogue/index.html` in a browser — interactive catalogue of every mark at every size, on the correct backgrounds.
3. **Adding a new format?** Edit `Catalogue/marks.js`, re-run the export script, and commit. Never hand-draw SVG paths — everything flows from `marks.js`.

---

## Brand summary

| | **certified random** | **blank** |
|---|---|---|
| what | studio / holding brand | first product: AI trading terminal |
| domain | certifiedrandom.studios | useblank.ai |
| mark | round seal ("CR" + ring text) | wordmark + 0.04em green rule |
| display type | Syne 800 | Outfit 700 |
| accent | `#c4ff3c` lime | `#00ff87` neon green |
| background | `#07070f` deep dark | `#000000` pure black |
| signature | Instrument Serif italic in lime ("random", "well") | Instrument Serif italic ("place the trade.") |

One voice across both: confident, quiet, editorial. No emoji. Lowercase names. Sharp corners (only the favicon tile gets a 4px radius).

---

## What changed in v3

- **Italic accent introduced.** Instrument Serif italic, in the accent colour, is now the signature editorial flourish ("random" in CR wordmark; straplines on blank banners).
- **CR wordmark and lockup are distinct.** Wordmark = type only, for UI chrome. Lockup = wordmark + seal + strapline + domain, for formal sign-offs.
- **Blank green rule is brand-consistent.** Every rule now sits at `baseline + 0.12 × font-size`, thickness `0.04 × font-size`, width `2.05 × font-size`. Never hand-placed.
- **Badge never collides with wordmark.** Every composite asset reserves a dedicated column for the seal.
- **AI TRADING TERMINAL kicker** no longer clashes with the wordmark on YouTube channel art.

---

2026.04 · London
