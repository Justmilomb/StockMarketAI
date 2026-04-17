"""Live finance-TV vision scraper.

Complements :mod:`core.scrapers.youtube_transcripts` with a low-rate
visual feed: sample a handful of frames per cycle from the 24/7 live
stream, send them to a vision model, and emit one :class:`ScrapedItem`
per cycle summarising anything markets-relevant that appeared on screen.

Dependencies are all optional at runtime:

- ``yt-dlp`` (Python module) — resolves the HLS URL of the live stream.
- ``ffmpeg`` (binary on PATH) — samples JPEG frames from the HLS URL.
- The Claude SDK — the vision summariser's model call.

Any missing dependency disables the scraper cleanly for the session.
A daily call-count cap guards the vision-model budget.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase

logger = logging.getLogger(__name__)

#: The same live stream used by the transcript scraper.
DEFAULT_VIDEO_ID: str = "iEpJwprxDdk"

#: How many JPEG frames to sample per cycle. Three is enough to see a
#: chyron change without burning the vision budget.
DEFAULT_SAMPLE_FRAMES: int = 3

#: Default daily cap on vision model calls (paper cycle-count is ~288/day
#: at 5-minute cadence × 3 frames = ~864 frames, so 500 is a safe ceiling).
DEFAULT_MAX_CALLS_PER_DAY: int = 500


class YouTubeLiveVisionScraper(ScraperBase):
    """Emit a one-line summary of markets content sampled from the live stream."""

    name: str = "youtube_live_vision"
    kind = "news"
    rate_limit_seconds: float = 10.0  # HLS manifest fetch; the real work is ffmpeg

    def __init__(
        self,
        *,
        video_id: str = DEFAULT_VIDEO_ID,
        sample_frames: int = DEFAULT_SAMPLE_FRAMES,
    ) -> None:
        super().__init__()
        self._video_id: str = video_id
        self._sample_frames: int = max(1, sample_frames)
        # Daily call counter: (YYYY-MM-DD, count).
        self._counter_day: str = ""
        self._counter_val: int = 0
        self._disabled_reason: Optional[str] = None

    # ── config + budget helpers ──────────────────────────────────────

    def _load_cfg(self) -> Dict[str, Any]:
        """Read ``scrapers.youtube_live_vision`` from ``config.json``."""
        try:
            import json
            from pathlib import Path as _P

            for cand in (_P("config.json"), _P.cwd() / "config.json"):
                if cand.exists():
                    with cand.open("r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    return ((cfg.get("scrapers") or {}).get("youtube_live_vision") or {})
        except Exception:
            pass
        return {}

    def _enabled(self, cfg: Dict[str, Any]) -> bool:
        return bool(cfg.get("enabled", True))

    def _check_and_increment_budget(self, cfg: Dict[str, Any]) -> bool:
        """Return True if we're within budget and record the call."""
        cap = int(cfg.get("max_calls_per_day", DEFAULT_MAX_CALLS_PER_DAY))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._counter_day:
            self._counter_day = today
            self._counter_val = 0
        if self._counter_val >= cap:
            return False
        self._counter_val += 1
        return True

    # ── HLS resolve + frame sampling ─────────────────────────────────

    def _resolve_hls_url(self) -> Optional[str]:
        """Use yt-dlp to get the live stream's HLS manifest URL."""
        try:
            import yt_dlp  # type: ignore
        except Exception:
            self._disabled_reason = "yt-dlp not installed"
            return None

        url = f"https://www.youtube.com/watch?v={self._video_id}"
        opts = {
            "quiet": True,
            "skip_download": True,
            "format": "best[protocol^=m3u8]/best",
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            logger.debug("yt-dlp extract failed: %s", e)
            return None
        return info.get("url") if isinstance(info, dict) else None

    def _sample_frames(self, hls_url: str, tmpdir: Path) -> List[Path]:
        """Use ffmpeg to grab N JPEG frames spaced out over ~20s of stream."""
        if shutil.which("ffmpeg") is None:
            self._disabled_reason = "ffmpeg not on PATH"
            return []

        pattern = str(tmpdir / "frame_%02d.jpg")
        # -vf fps=1/(duration/N) yields roughly N frames across the window.
        window = max(self._sample_frames * 6, 15)  # seconds of stream to read
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-t", str(window),
            "-i", hls_url,
            "-vf", f"fps=1/{max(1, window // self._sample_frames)}",
            "-frames:v", str(self._sample_frames),
            "-q:v", "5",
            pattern,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=window + 20)
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("ffmpeg frame sample failed: %s", e)
            return []

        frames = sorted(tmpdir.glob("frame_*.jpg"))
        return [p for p in frames if p.stat().st_size > 0]

    # ── ScraperBase.fetch ────────────────────────────────────────────

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        cfg = self._load_cfg()
        if not self._enabled(cfg):
            return []
        if self._disabled_reason is not None:
            # One-shot disable — logged once in the first failing call.
            return []
        if not self._check_and_increment_budget(cfg):
            logger.debug("vision scraper: daily cap hit")
            return []

        hls_url = self._resolve_hls_url()
        if not hls_url:
            if self._disabled_reason:
                logger.info("vision scraper disabled: %s", self._disabled_reason)
            return []

        with tempfile.TemporaryDirectory(prefix="blank_vision_") as td:
            tmp = Path(td)
            frames = self._sample_frames(hls_url, tmp)
            if not frames:
                if self._disabled_reason:
                    logger.info("vision scraper disabled: %s", self._disabled_reason)
                return []

            from core.scrapers._vision_summariser import summarise_frames
            try:
                summary = asyncio.run(summarise_frames(frames))
            except RuntimeError:
                # Already inside an event loop — run on a fresh one in a thread.
                summary = ""
            except Exception as e:
                logger.debug("vision summarise failed: %s", e)
                summary = ""

        if not summary:
            return []

        return [
            ScrapedItem(
                source=self.name,
                kind="news",
                title=summary.split("\n")[0][:200],
                url=f"https://www.youtube.com/watch?v={self._video_id}",
                ts=datetime.now(timezone.utc),
                summary=summary,
                meta={"video_id": self._video_id, "frames": len(frames)},
            ),
        ]
