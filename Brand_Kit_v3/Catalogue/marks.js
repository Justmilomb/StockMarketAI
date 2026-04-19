/* marks.js — brand-faithful marks.
   Typography: Syne 800 display, Outfit body, JetBrains Mono mono, Instrument Serif italic editorial accent.
   Rule: the badge sits in its own column. Never overlaps wordmark.
   Rule: sharp corners. Radius 0 by default, 4px on favicon tile.
   Domains: certifiedrandom.studios • useblank.ai
*/
window.Marks = (() => {
    let _id = 0;
    const uid = () => 'm' + (++_id);
    const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // Shared badge group, positioned inside a parent SVG at (cx, cy) with radius R.
    function crBadgeGroup(cx, cy, R) {
        const id = uid();
        const rDash = R;
        const rInner = R * 0.885;
        const rText = R * 0.82;
        const crSize = R * 0.30;
        const crY = cy - R * 0.05;
        const lineY = cy + R * 0.18;
        const lineHalf = R * 0.28;
        const studiosY = cy + R * 0.48;
        const studiosSize = R * 0.085;
        const ringStroke = Math.max(R * 0.008, 0.75);
        const ringStrokeFaint = Math.max(R * 0.0055, 0.5);
        const dashText = R * 0.105;
        return `<defs><path id="${id}" d="M ${cx},${cy} m -${rText},0 a ${rText},${rText} 0 1,1 ${rText*2},0 a ${rText},${rText} 0 1,1 -${rText*2},0"/></defs>
  <circle cx="${cx}" cy="${cy}" r="${rDash}" fill="none" stroke="#c4ff3c" stroke-width="${ringStroke}" stroke-dasharray="${R*0.028} ${R*0.02}" opacity="0.5"/>
  <circle cx="${cx}" cy="${cy}" r="${rInner}" fill="none" stroke="#c4ff3c" stroke-width="${ringStrokeFaint}" opacity="0.3"/>
  <text font-family="'JetBrains Mono', monospace" font-weight="400" font-size="${dashText}" fill="#c4ff3c" letter-spacing="${R*0.028}"><textPath href="#${id}">CERTIFIED RANDOM STUDIOS • EST. 2026 • </textPath></text>
  <text x="${cx}" y="${crY}" text-anchor="middle" font-family="'Syne', sans-serif" font-size="${crSize}" font-weight="800" fill="#c4ff3c">CR</text>
  <line x1="${cx-lineHalf}" y1="${lineY}" x2="${cx+lineHalf}" y2="${lineY}" stroke="#c4ff3c" stroke-width="${ringStroke}" opacity="0.4"/>
  <text x="${cx}" y="${studiosY}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-weight="400" font-size="${studiosSize}" letter-spacing="${R*0.04}" fill="#c4ff3c" opacity="0.55">STUDIOS</text>`;
    }

    // ═══ CR ══════════════════════════════
    // Hero badge — round, standalone
    function crBadge({ spin = false, bg = '#07070f' } = {}) {
        const animate = spin
            ? `<animateTransform attributeName="transform" type="rotate" from="0 120 120" to="360 120 120" dur="32s" repeatCount="indefinite"/>`
            : '';
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  ${bg === 'transparent' ? '' : `<rect width="240" height="240" fill="${bg}"/>`}
  <g>${animate}${crBadgeGroup(120, 120, 100)}</g>
</svg>`;
    }

    // Wordmark — type only. Nav bars, UI chrome, video end-cards.
    function crWordmark({ bg = '#07070f' } = {}) {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2500 480" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  ${bg === 'transparent' ? '' : `<rect width="2500" height="480" fill="${bg}"/>`}
  <text x="60" y="340" font-family="'Syne', sans-serif" font-size="220" font-weight="800" fill="#edeae4" letter-spacing="-8">certified <tspan font-family="'Instrument Serif', serif" font-weight="400" font-style="italic" fill="#c4ff3c" letter-spacing="0" font-size="260" dx="30">random</tspan></text>
</svg>`;
    }

    // Lockup — wordmark + seal + strapline + domain. The formal sign-off: decks, press kits, about pages.
    function crLockup({ bg = '#07070f' } = {}) {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2500 1100" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  ${bg === 'transparent' ? '' : `<rect width="2500" height="1100" fill="${bg}"/>`}
  <text x="60" y="82" font-family="'JetBrains Mono', monospace" font-size="30" letter-spacing="7" fill="#c4ff3c">— STUDIO / EST. 2026 / LONDON</text>
  <text x="60" y="390" font-family="'Syne', sans-serif" font-size="220" font-weight="800" fill="#edeae4" letter-spacing="-8">certified <tspan font-family="'Instrument Serif', serif" font-weight="400" font-style="italic" fill="#c4ff3c" letter-spacing="0" font-size="260" dx="30">random</tspan></text>
  <text x="60" y="510" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="64" fill="#c4ff3c">we build software.</text>
  <text x="690" y="510" font-family="'Outfit', sans-serif" font-size="44" font-weight="300" fill="#8a8a9e">quietly, quickly, well.</text>
  <line x1="60" y1="620" x2="2440" y2="620" stroke="rgba(255,255,255,0.1)" stroke-width="2"/>
  ${crBadgeGroup(240, 860, 180)}
  <text x="500" y="830" font-family="'JetBrains Mono', monospace" font-size="30" letter-spacing="6" fill="#edeae4">CERTIFIEDRANDOM.STUDIOS</text>
  <text x="500" y="880" font-family="'JetBrains Mono', monospace" font-size="22" letter-spacing="5" fill="#48485c">AI / WEB / DESKTOP &#160;·&#160; LONDON, UK</text>
  <text x="500" y="922" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="28" fill="#c4ff3c">est. 2026</text>
</svg>`;
    }

    // Logomark — sharp corners (brand rule: no rounded logo tiles)
    function crLogomark() {
        const vb = 100;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb} ${vb}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${vb}" height="${vb}" fill="#c4ff3c"/>
  <text x="${vb/2}" y="64" text-anchor="middle" font-family="'Syne', sans-serif" font-size="30" font-weight="800" fill="#07070f" letter-spacing="-1">CR</text>
</svg>`;
    }

    // App icon — iOS mask applies; keeping the source sharp-cornered is fine.
    function crAppIcon() {
        const vb = 1024;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb} ${vb}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${vb}" height="${vb}" fill="#07070f"/>
  <g>${crBadgeGroup(vb/2, vb/2, vb*0.36)}</g>
</svg>`;
    }

    // Favicon — 4px radius is the one permitted radius
    function crFavicon() {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="32" height="32" rx="4" fill="#07070f"/>
  <text x="16" y="22" text-anchor="middle" font-family="'Syne', sans-serif" font-weight="800" font-size="12" fill="#c4ff3c" letter-spacing="-0.5">CR</text>
</svg>`;
    }

    // Avatar — badge full-bleed on dark
    function crAvatar() {
        const vb = 400;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb} ${vb}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${vb}" height="${vb}" fill="#07070f"/>
  ${crBadgeGroup(vb/2, vb/2, vb*0.42)}
</svg>`;
    }

    // OG / Twitter card 1200×630 — type column (x 72..760) + badge column (x 900..1128)
    function crOg() {
        const w=1200, h=630;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  <text x="72" y="92" font-family="'JetBrains Mono', monospace" font-size="14" letter-spacing="3" fill="#c4ff3c">— STUDIO / EST. 2026</text>
  <text x="72" y="268" font-family="'Syne', sans-serif" font-size="118" font-weight="800" fill="#edeae4" letter-spacing="-4">certified</text>
  <text x="72" y="398" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="142" fill="#c4ff3c" letter-spacing="-1">random</text>
  <text x="72" y="458" font-family="'Outfit', sans-serif" font-size="22" font-weight="300" fill="#8a8a9e">we build software. quietly, quickly, well.</text>
  <line x1="72" y1="540" x2="1128" y2="540" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>
  <text x="72" y="578" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#48485c">CERTIFIEDRANDOM.STUDIOS &#160;•&#160; LONDON &#160;•&#160; AI / WEB / DESKTOP</text>
  ${crBadgeGroup(1010, 310, 118)}
</svg>`;
    }

    // Twitter banner 1500×500 — type column (x 64..950) + badge column (x 1100..1440)
    // 'we build software' at Syne 800 72 ≈ 720 wide → ends ~780
    function crTwitterBanner() {
        const w=1500, h=500;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  <text x="64" y="92" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#c4ff3c">— STUDIO / EST. 2026 / LONDON</text>
  <text x="64" y="230" font-family="'Syne', sans-serif" font-size="76" font-weight="800" fill="#edeae4" letter-spacing="-2.5">we build software</text>
  <text x="64" y="322" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="96" fill="#c4ff3c" letter-spacing="-1">quietly, well</text>
  <text x="64" y="420" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#48485c">certifiedrandom.studios &#160;•&#160; ai / web / desktop</text>
  ${crBadgeGroup(1260, 250, 150)}
</svg>`;
    }

    // LinkedIn banner 1584×396 — LinkedIn circle-crops a 256px region centered ~152px from left at bottom.
    // Keep badge far right so avatar crop doesn't kill it.
    function crLinkedInBanner() {
        const w=1584, h=396;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  <text x="64" y="72" font-family="'JetBrains Mono', monospace" font-size="12" letter-spacing="3" fill="#c4ff3c">— STUDIO / EST. 2026</text>
  <text x="64" y="200" font-family="'Syne', sans-serif" font-size="86" font-weight="800" fill="#edeae4" letter-spacing="-2.8">we build</text>
  <text x="64" y="296" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="102" fill="#c4ff3c" letter-spacing="-1">software</text>
  <text x="64" y="352" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#48485c">certifiedrandom.studios &#160;•&#160; ai / web / desktop</text>
  ${crBadgeGroup(1420, 198, 130)}
</svg>`;
    }

    // YouTube banner 2560×1440 — safe area is center 1546x423. Use that band only.
    // Badge sits inside safe area, right of type. Type is left-anchored.
    function crYoutubeBanner() {
        const w=2560, h=1440;
        const safeL = w/2 - 773;        // 507
        const safeR = w/2 + 773;        // 2053
        const safeT = h/2 - 211.5;      // 508.5
        // Badge right inside safe area at center-right
        const badgeCx = safeR - 220;
        const badgeCy = h/2;
        const badgeR = 180;
        // Type left inside safe area
        const typeX = safeL + 40;       // 547
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  <text x="${typeX}" y="${safeT+70}" font-family="'JetBrains Mono', monospace" font-size="22" letter-spacing="5.5" fill="#c4ff3c">— STUDIO / EST. 2026 / LONDON</text>
  <text x="${typeX}" y="${safeT+210}" font-family="'Syne', sans-serif" font-size="112" font-weight="800" fill="#edeae4" letter-spacing="-4">certified</text>
  <text x="${typeX}" y="${safeT+338}" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="140" fill="#c4ff3c" letter-spacing="-1">random</text>
  <text x="${typeX}" y="${safeT+400}" font-family="'Outfit', sans-serif" font-size="22" font-weight="300" fill="#8a8a9e">we build software. quietly, quickly, well.</text>
  ${crBadgeGroup(badgeCx, badgeCy, badgeR)}
</svg>`;
    }

    // YT thumb 1280×720 — badge top-right. Make badge smaller so it reads at 168×94 inbox size.
    function crYtThumb({ kicker='SHIPPING NOTES', title='how we built', tail='blank' } = {}) {
        const w=1280, h=720;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  <text x="60" y="90" font-family="'JetBrains Mono', monospace" font-size="18" letter-spacing="5" fill="#c4ff3c">— ${esc(kicker)}</text>
  <text x="60" y="370" font-family="'Syne', sans-serif" font-size="108" font-weight="800" fill="#edeae4" letter-spacing="-3">${esc(title)}</text>
  <text x="60" y="500" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="130" fill="#c4ff3c" letter-spacing="-1">${esc(tail)}</text>
  <line x1="60" y1="640" x2="1220" y2="640" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>
  <text x="60" y="685" font-family="'JetBrains Mono', monospace" font-size="16" letter-spacing="4" fill="#48485c">certifiedrandom.studios</text>
  ${crBadgeGroup(1140, 130, 90)}
</svg>`;
    }

    // Business card 1050×600 — two-column, type left + badge right column
    function crBusinessCard() {
        const w=1050, h=600;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  <text x="56" y="88" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#c4ff3c">— STUDIO / EST. 2026</text>
  <text x="56" y="320" font-family="'Syne', sans-serif" font-size="96" font-weight="800" fill="#edeae4" letter-spacing="-3.5">certified</text>
  <text x="56" y="424" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="116" fill="#c4ff3c" letter-spacing="-1">random</text>
  <line x1="56" y1="488" x2="${w-56}" y2="488" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>
  <text x="56" y="530" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#48485c">CERTIFIEDRANDOM.STUDIOS</text>
  <text x="${w-56}" y="530" text-anchor="end" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#48485c">LONDON / UK</text>
  ${crBadgeGroup(w-130, 150, 82)}
</svg>`;
    }

    // Email signature 600×140 — tiny badge left, info right
    function crEmailSig() {
        const w=600, h=140;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#07070f"/>
  ${crBadgeGroup(68, 70, 54)}
  <line x1="140" y1="30" x2="140" y2="110" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>
  <text x="158" y="58" font-family="'Outfit', sans-serif" font-size="22" font-weight="500" fill="#edeae4">Jane Doe</text>
  <text x="158" y="80" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="17" fill="#c4ff3c">founder,</text>
  <text x="225" y="80" font-family="'Outfit', sans-serif" font-size="14" font-weight="300" fill="#8a8a9e">certified random</text>
  <line x1="158" y1="92" x2="440" y2="92" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="158" y="114" font-family="'JetBrains Mono', monospace" font-size="11" letter-spacing="2.4" fill="#48485c">CERTIFIEDRANDOM.STUDIOS / LONDON</text>
</svg>`;
    }

    // ═══ BLANK ══════════════════════════════
    // Underline rule — brand-wide constant.
    // gap = distance from text BASELINE to TOP of line = 0.12 × fontSize
    // thickness = 0.04 × fontSize
    // width = widthRatio × fontSize (defaults tuned to "blank" in Outfit 700 with letter-spacing ≈ -0.035em)
    function blankRule({ baselineY, fontSize, anchor = 'start', anchorX, widthRatio = 2.05 }) {
        const gap = fontSize * 0.12;
        const thickness = Math.max(fontSize * 0.04, 2);
        const width = fontSize * widthRatio;
        let x;
        if (anchor === 'middle') x = anchorX - width / 2;
        else if (anchor === 'end') x = anchorX - width;
        else x = anchorX;
        return `<rect x="${x.toFixed(2)}" y="${(baselineY + gap).toFixed(2)}" width="${width.toFixed(2)}" height="${thickness.toFixed(2)}" fill="#00ff87"/>`;
    }

    function blankWordmark({ bg = '#000000', fg = '#ffffff' } = {}) {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 140" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  ${bg === 'transparent' ? '' : `<rect width="400" height="140" fill="${bg}"/>`}
  <text x="200" y="100" text-anchor="middle" font-family="'Outfit', sans-serif" font-size="108" font-weight="700" fill="${fg}" letter-spacing="-4">blank</text>
</svg>`;
    }

    function blankLockup() {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="400" height="200" fill="#000000"/>
  <text x="200" y="120" text-anchor="middle" font-family="'Outfit', sans-serif" font-size="100" font-weight="700" fill="#ffffff" letter-spacing="-3.5">blank</text>
  ${blankRule({ baselineY: 120, fontSize: 100, anchor: 'middle', anchorX: 200 })}
  <text x="200" y="176" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="11" letter-spacing="3" fill="#00ff87">AI TRADING TERMINAL</text>
</svg>`;
    }

    function blankLogomark() {
        const vb = 100;
        const fontSize = vb * 0.82;
        const baselineY = vb * 0.74;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb} ${vb}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${vb}" height="${vb}" fill="#000000"/>
  <text x="${vb/2}" y="${baselineY}" text-anchor="middle" font-family="'Outfit', sans-serif" font-size="${fontSize}" font-weight="700" fill="#ffffff" letter-spacing="-3">b</text>
  ${blankRule({ baselineY, fontSize, anchor: 'middle', anchorX: vb/2, widthRatio: 0.75 })}
</svg>`;
    }

    function blankAppIcon() {
        const vb = 1024;
        const fontSize = 340;
        // dominant-baseline:middle → visual baseline is text y + fontSize*0.32
        const textY = vb * 0.52;
        const baselineY = textY + fontSize * 0.32;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb} ${vb}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${vb}" height="${vb}" fill="#000000"/>
  <text x="${vb/2}" y="${textY}" text-anchor="middle" dominant-baseline="middle" font-family="'Outfit', sans-serif" font-size="${fontSize}" font-weight="700" fill="#ffffff" letter-spacing="-12">blank</text>
  ${blankRule({ baselineY, fontSize, anchor: 'middle', anchorX: vb/2 })}
</svg>`;
    }

    function blankFavicon() {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="32" height="32" rx="4" fill="#000000"/>
  <text x="16" y="25" text-anchor="middle" font-family="'Outfit', sans-serif" font-weight="700" font-size="26" fill="#ffffff" letter-spacing="-1">b</text>
</svg>`;
    }

    function blankAvatar() {
        const vb = 400;
        const fontSize = 140;
        const textY = vb * 0.50;
        const baselineY = textY + fontSize * 0.32;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb} ${vb}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${vb}" height="${vb}" fill="#000000"/>
  <text x="${vb/2}" y="${textY}" text-anchor="middle" dominant-baseline="middle" font-family="'Outfit', sans-serif" font-size="${fontSize}" font-weight="700" fill="#ffffff" letter-spacing="-5">blank</text>
  ${blankRule({ baselineY, fontSize, anchor: 'middle', anchorX: vb/2 })}
</svg>`;
    }

    function blankOg() {
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="1200" height="630" fill="#000000"/>
  <text x="72" y="92" font-family="'JetBrains Mono', monospace" font-size="14" letter-spacing="3" fill="#00ff87">— AI TRADING TERMINAL</text>
  <text x="72" y="360" font-family="'Outfit', sans-serif" font-size="280" font-weight="700" fill="#ffffff" letter-spacing="-10">blank</text>
  ${blankRule({ baselineY: 360, fontSize: 280, anchor: 'start', anchorX: 72 })}
  <text x="72" y="468" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="28" fill="rgba(255,255,255,0.85)">never look up.</text>
  <text x="270" y="468" font-family="'Outfit', sans-serif" font-size="22" font-weight="300" fill="rgba(255,255,255,0.6)">place the trade.</text>
  <line x1="72" y1="540" x2="1128" y2="540" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="72" y="578" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="rgba(255,255,255,0.32)">USEBLANK.AI &#160;•&#160; A PRODUCT OF CERTIFIED RANDOM &#160;•&#160; EST. 2026</text>
  <g transform="translate(820 150)" font-family="'JetBrains Mono', monospace" font-size="15" letter-spacing="1.5">
    <text y="0" fill="rgba(255,255,255,0.32)">AAPL    +2.14%</text>
    <text y="30" fill="#00ff87">NVDA    +6.88%</text>
    <text y="60" fill="rgba(255,255,255,0.32)">MSFT    +0.92%</text>
    <text y="90" fill="rgba(255,255,255,0.32)">TSLA    -1.05%</text>
    <text y="120" fill="rgba(255,255,255,0.32)">GOOG    +1.71%</text>
    <text y="150" fill="#00ff87">QQQ     +3.41%</text>
  </g>
</svg>`;
    }

    function blankTwitterBanner() {
        const w=1500, h=500;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#000000"/>
  <text x="60" y="72" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#00ff87">— AI TRADING TERMINAL / NEVER LOOK UP</text>
  <text x="60" y="330" font-family="'Outfit', sans-serif" font-size="300" font-weight="700" fill="#ffffff" letter-spacing="-12">blank</text>
  ${blankRule({ baselineY: 330, fontSize: 300, anchor: 'start', anchorX: 60 })}
  <text x="60" y="438" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="26" fill="rgba(255,255,255,0.85)">place the trade.</text>
  <text x="240" y="438" font-family="'Outfit', sans-serif" font-size="18" font-weight="300" fill="rgba(255,255,255,0.6)">useblank.ai &#160;•&#160; watch the tape.</text>
  <g transform="translate(1080 130)" font-family="'JetBrains Mono', monospace" font-size="15" letter-spacing="1.5">
    <text y="0" fill="rgba(255,255,255,0.32)">AAPL    +2.14%</text>
    <text y="34" fill="#00ff87">NVDA    +6.88%</text>
    <text y="68" fill="rgba(255,255,255,0.32)">MSFT    +0.92%</text>
    <text y="102" fill="rgba(255,255,255,0.32)">TSLA    -1.05%</text>
    <text y="136" fill="#00ff87">QQQ     +3.41%</text>
    <text y="170" fill="rgba(255,255,255,0.32)">SPY     +1.02%</text>
    <text y="204" fill="rgba(255,255,255,0.32)">GOOG    +1.71%</text>
    <text y="238" fill="#00ff87">BTC     +4.22%</text>
  </g>
</svg>`;
    }

    function blankLinkedInBanner() {
        const w=1584, h=396;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#000000"/>
  <text x="64" y="72" font-family="'JetBrains Mono', monospace" font-size="12" letter-spacing="3" fill="#00ff87">— AI TRADING TERMINAL</text>
  <text x="64" y="280" font-family="'Outfit', sans-serif" font-size="230" font-weight="700" fill="#ffffff" letter-spacing="-9">blank</text>
  ${blankRule({ baselineY: 280, fontSize: 230, anchor: 'start', anchorX: 64 })}
  <text x="64" y="368" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="22" fill="rgba(255,255,255,0.85)">a product of certified random.</text>
  <text x="420" y="368" font-family="'JetBrains Mono', monospace" font-size="12" letter-spacing="2.5" fill="rgba(255,255,255,0.4)">useblank.ai</text>
</svg>`;
    }

    function blankYoutubeBanner() {
        const w=2560, h=1440;
        // safe area (center 1546x423) top = (1440-423)/2 = 508.5
        const safeT = h/2 - 211.5;      // 508.5
        // Stack inside safe area:
        // kicker baseline at safeT + 40   → top ~safeT+22
        // wordmark baseline at safeT + 340 (fontSize 300, caps ~220 high → top ~safeT+120, well below kicker)
        // rule 0.12*300 = 36 → y = safeT+376
        // strapline at safeT + 432
        const kickerY = safeT + 40;
        const wordFont = 300;
        const wordBaseline = safeT + 340;
        const strapY = safeT + 432;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#000000"/>
  <text x="${w/2}" y="${kickerY}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="24" letter-spacing="6" fill="#00ff87">— AI TRADING TERMINAL</text>
  <text x="${w/2}" y="${wordBaseline}" text-anchor="middle" font-family="'Outfit', sans-serif" font-size="${wordFont}" font-weight="700" fill="#ffffff" letter-spacing="-13">blank</text>
  ${blankRule({ baselineY: wordBaseline, fontSize: wordFont, anchor: 'middle', anchorX: w/2 })}
  <text x="${w/2}" y="${strapY}" text-anchor="middle" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="32" fill="rgba(255,255,255,0.85)">never look up. place the trade.</text>
</svg>`;
    }

    function blankYtThumb({ kicker='TAPE READ', title='NVDA', tail='+6.88%' } = {}) {
        const w=1280, h=720;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#000000"/>
  <text x="60" y="90" font-family="'JetBrains Mono', monospace" font-size="18" letter-spacing="5" fill="#00ff87">— ${esc(kicker)}</text>
  <text x="60" y="360" font-family="'Outfit', sans-serif" font-size="220" font-weight="700" fill="#ffffff" letter-spacing="-9">${esc(title)}</text>
  <text x="60" y="520" font-family="'Outfit', sans-serif" font-size="140" font-weight="500" fill="#00ff87" letter-spacing="-5">${esc(tail)}</text>
  <line x1="60" y1="640" x2="1220" y2="640" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="60" y="685" font-family="'JetBrains Mono', monospace" font-size="16" letter-spacing="4" fill="rgba(255,255,255,0.32)">useblank.ai &#160;•&#160; a product of certified random</text>
</svg>`;
    }

    function blankBusinessCard() {
        const w=1050, h=600;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#000000"/>
  <text x="56" y="88" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="#00ff87">— AI TRADING TERMINAL</text>
  <text x="56" y="320" font-family="'Outfit', sans-serif" font-size="190" font-weight="700" fill="#ffffff" letter-spacing="-7">blank</text>
  ${blankRule({ baselineY: 320, fontSize: 190, anchor: 'start', anchorX: 56 })}
  <text x="56" y="400" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="24" fill="rgba(255,255,255,0.85)">place the trade. watch the tape.</text>
  <line x1="56" y1="488" x2="${w-56}" y2="488" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="56" y="530" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="rgba(255,255,255,0.32)">USEBLANK.AI / A PRODUCT OF CERTIFIED RANDOM</text>
  <text x="${w-56}" y="530" text-anchor="end" font-family="'JetBrains Mono', monospace" font-size="13" letter-spacing="3" fill="rgba(255,255,255,0.32)">LONDON / UK</text>
</svg>`;
    }

    function blankEmailSig() {
        const w=600, h=140;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
  <rect width="${w}" height="${h}" fill="#000000"/>
  <text x="24" y="74" font-family="'Outfit', sans-serif" font-size="52" font-weight="700" fill="#ffffff" letter-spacing="-2">blank</text>
  ${blankRule({ baselineY: 74, fontSize: 52, anchor: 'start', anchorX: 24 })}
  <line x1="200" y1="30" x2="200" y2="110" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>
  <text x="224" y="55" font-family="'Outfit', sans-serif" font-size="20" font-weight="500" fill="#ffffff">Jane Doe</text>
  <text x="224" y="78" font-family="'Instrument Serif', serif" font-style="italic" font-weight="400" font-size="17" fill="rgba(255,255,255,0.9)">trader</text>
  <text x="278" y="78" font-family="'Outfit', sans-serif" font-size="13" font-weight="300" fill="rgba(255,255,255,0.6)">in residence</text>
  <text x="224" y="108" font-family="'JetBrains Mono', monospace" font-size="11" letter-spacing="2.4" fill="rgba(255,255,255,0.32)">USEBLANK.AI / NEVER LOOK UP</text>
</svg>`;
    }

    return {
        crBadge, crLockup, crWordmark, crLogomark, crAppIcon, crFavicon, crAvatar,
        crOg, crTwitterBanner, crLinkedInBanner, crYoutubeBanner, crYtThumb,
        crBusinessCard, crEmailSig,
        blankWordmark, blankLockup, blankLogomark, blankAppIcon, blankFavicon, blankAvatar,
        blankOg, blankTwitterBanner, blankLinkedInBanner, blankYoutubeBanner, blankYtThumb,
        blankBusinessCard, blankEmailSig,
    };
})();
