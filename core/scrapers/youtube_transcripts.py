"""YouTube transcript scraper — captions from the @markets channel + 24/7 stream.

Complements ``youtube.py`` (which only reads RSS titles). This scraper
pulls the actual spoken captions from two sources:

1. The five most recent uploads on the @markets channel — one
   summarised ScrapedItem per new video.
2. The 24/7 live stream (video id ``iEpJwprxDdk``) — captions are
   published on a short delay once the broadcaster's auto-captions
   catch up, so we emit a rolling snapshot every cycle.

``youtube-transcript-api`` is the only runtime dep beyond what the
other scrapers already need — no API key, no ffmpeg, no yt-dlp. If
the dep is missing we log once and skip (never raise).

The Haiku summariser is called once per new video; results are cached
in-process by video_id so a runner restart doesn't re-bill the same
video on the first cycle back.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.scrapers._transcript_summariser import summarise_transcript
from core.scrapers.base import ScrapedItem, ScraperBase

logger = logging.getLogger(__name__)

#: @markets channel id (Bloomberg Television).
_MARKETS_CHANNEL_ID: str = "UCIALMKvObZNtJ6AmdCLP7Lg"

#: 24/7 live stream video id.
_LIVE_STREAM_VIDEO_ID: str = "iEpJwprxDdk"

_FEED_TEMPLATE: str = "https://www.youtube.com/feeds/videos.xml?channel_id={id}"
_WATCH_URL_TEMPLATE: str = "https://www.youtube.com/watch?v={vid}"
_CHANNEL_LABEL: str = "Bloomberg Television"


def _load_transcript_api() -> Optional[object]:
    """Return YouTubeTranscriptApi if the dep is installed, else None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        return YouTubeTranscriptApi
    except ImportError:
        logger.warning(
            "[youtube_transcripts] youtube-transcript-api not installed — "
            "scraper disabled. Run: pip install youtube-transcript-api"
        )
        return None


class YouTubeTranscriptsScraper(ScraperBase):
    """Two-source transcript scraper: recent uploads + 24/7 live stream."""

    name = "youtube_transcripts"
    kind = "news"

    #: How many recent uploads to pull captions for per cycle.
    MAX_VIDEOS: int = 5

    #: Rolling window of live-stream captions (seconds). Only the last
    #: N seconds of captions get summarised each cycle so the runner
    #: sees what was being said ~10 minutes ago, not the whole day.
    LIVE_WINDOW_SECONDS: int = 600

    def __init__(self) -> None:
        super().__init__()
        # video_id → summary — prevents re-summarising between cycles.
        self._summary_cache: Dict[str, str] = {}

    # ── ScraperBase API ─────────────────────────────────────────────

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        api = _load_transcript_api()
        if api is None:
            return []

        items: List[ScrapedItem] = []
        items.extend(self._fetch_recent_videos(api))
        live_item = self._fetch_live_snapshot(api)
        if live_item is not None:
            items.append(live_item)
        return items

    # ── Recent-video path ───────────────────────────────────────────

    def _fetch_recent_videos(self, api: object) -> List[ScrapedItem]:
        """Summarise the MAX_VIDEOS most recent uploads on @markets."""
        feed_url = _FEED_TEMPLATE.format(id=_MARKETS_CHANNEL_ID)
        entries = self.fetch_rss(feed_url)
        items: List[ScrapedItem] = []

        for entry in entries[: self.MAX_VIDEOS]:
            vid = self._extract_video_id(entry)
            if not vid:
                continue
            title = (entry.get("title") or "").strip()
            if not title:
                continue

            summary = self._summary_cache.get(vid)
            if summary is None:
                transcript = self._get_transcript(api, vid)
                if not transcript:
                    continue
                summary = summarise_transcript(transcript)
                if summary:
                    self._summary_cache[vid] = summary

            if not summary:
                continue

            items.append(ScrapedItem(
                source=self.name,
                kind=self.kind,
                title=title,
                url=_WATCH_URL_TEMPLATE.format(vid=vid),
                ticker=None,
                ts=self.parse_rss_date(entry),
                summary=summary,
                meta={
                    "channel": _CHANNEL_LABEL,
                    "source_type": "transcript",
                    "video_id": vid,
                },
            ))
        return items

    # ── Live-stream path ────────────────────────────────────────────

    def _fetch_live_snapshot(self, api: object) -> Optional[ScrapedItem]:
        """Summarise the last LIVE_WINDOW_SECONDS of the 24/7 stream.

        Live captions land with a delay, so on fresh starts this often
        yields nothing — that's fine, the next cycle picks it up.
        """
        transcript = self._get_transcript(api, _LIVE_STREAM_VIDEO_ID, live=True)
        if not transcript:
            return None

        summary = summarise_transcript(transcript)
        if not summary:
            return None

        now = datetime.now(timezone.utc)
        title = f"{_CHANNEL_LABEL} — live market commentary ({now:%H:%M UTC})"

        return ScrapedItem(
            source=self.name,
            kind=self.kind,
            title=title,
            url=_WATCH_URL_TEMPLATE.format(vid=_LIVE_STREAM_VIDEO_ID),
            ticker=None,
            ts=now,
            summary=summary,
            meta={
                "channel": _CHANNEL_LABEL,
                "source_type": "live_transcript",
                "video_id": _LIVE_STREAM_VIDEO_ID,
                "window_seconds": self.LIVE_WINDOW_SECONDS,
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────

    def _get_transcript(
        self,
        api: object,
        video_id: str,
        live: bool = False,
    ) -> str:
        """Fetch captions for *video_id* and return the joined text.

        Returns '' if the video has no captions, the API call fails,
        or (for live) no captions are available yet. Handles both the
        v0.6 (`YouTubeTranscriptApi.get_transcript`) and v1+ (instance
        `.fetch()`) signatures.
        """
        langs = ["en", "en-GB", "en-US"]
        try:
            if hasattr(api, "get_transcript"):
                raw = api.get_transcript(video_id, languages=langs)  # type: ignore[attr-defined]
            else:
                raw = api().fetch(video_id, languages=langs)  # type: ignore[operator]
                raw = [
                    {"start": s.start, "duration": s.duration, "text": s.text}
                    for s in raw
                ]
        except Exception as exc:
            logger.debug("[%s] transcript fetch failed for %s: %s", self.name, video_id, exc)
            return ""

        if not raw:
            return ""

        if live:
            cutoff = max(0.0, max(entry.get("start", 0.0) for entry in raw) - self.LIVE_WINDOW_SECONDS)
            raw = [entry for entry in raw if entry.get("start", 0.0) >= cutoff]

        return " ".join(entry.get("text", "").strip() for entry in raw if entry.get("text"))

    @staticmethod
    def _extract_video_id(entry: Dict[str, object]) -> Optional[str]:
        """Pull the 11-char YouTube video id out of an RSS entry."""
        raw_id = entry.get("yt_videoid") or entry.get("id") or ""
        raw_id = str(raw_id)
        if ":" in raw_id:
            raw_id = raw_id.rsplit(":", 1)[-1]
        if len(raw_id) == 11:
            return raw_id
        link = str(entry.get("link") or "")
        if "watch?v=" in link:
            tail = link.split("watch?v=", 1)[-1]
            return tail[:11] or None
        return None
