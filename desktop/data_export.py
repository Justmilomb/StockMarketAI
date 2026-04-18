"""One-shot export of the client's local state for future training use.

The desktop app persists every agent decision, tool call, scraper item,
research finding and chat turn into ``%LOCALAPPDATA%\\blank\\data\\*.db``
— that is the training corpus. This module bundles that corpus into a
single timestamped ``.zip`` the user can hand back to us for supervised
fine-tuning.

What goes in
    * Every ``*.db`` under the user-data ``data/`` subtree (live DB,
      paper DB, paper-chat DB).
    * A sanitised copy of ``config.json`` — secrets (licence key, broker
      token, API keys) are stripped before it's added.
    * ``export_manifest.json`` — app version, export time, schema
      hints, and a per-table row count per database. Lets us verify the
      bundle on our end without opening the raw ``.db`` files.

What's excluded
    * ``.env`` (secrets).
    * ``bin/ffmpeg.exe`` (large binary, already downloadable).
    * Lock files, temporary files.

Nothing is ever deleted or mutated — the export is read-only.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from desktop.paths import config_path, user_data_dir

logger = logging.getLogger(__name__)

_SENSITIVE_CONFIG_KEYS = {
    "license_key",
    "licence_key",
    "trading212_api_key",
    "t212_api_key",
    "broker_api_key",
    "resend_api_key",
    "admin_key",
    "anthropic_api_key",
    "openai_api_key",
}


@dataclass
class DatabaseStats:
    path: str
    bytes: int
    tables: Dict[str, int] = field(default_factory=dict)


@dataclass
class ExportSummary:
    """Result of :func:`export_user_data`.

    Returned to the UI so the caller can surface a useful confirmation
    dialog ("exported 12,345 agent-journal rows — 4.2 MB zip").
    """
    zip_path: Path
    total_bytes: int
    databases: List[DatabaseStats] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    def total_rows(self) -> int:
        return sum(
            count
            for db in self.databases
            for count in db.tables.values()
        )

    def headline(self) -> str:
        kb = self.total_bytes / 1024
        size_s = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
        return (
            f"{len(self.databases)} database(s), "
            f"{self.total_rows():,} rows, {size_s}"
        )


def _collect_database_stats(db_file: Path) -> DatabaseStats:
    """Return table names + row counts for one SQLite file.

    Best-effort — a corrupt DB or one locked by another process is
    reported with empty ``tables`` rather than raising. We still ship
    the raw file so we can recover offline.
    """
    stats = DatabaseStats(path=str(db_file), bytes=db_file.stat().st_size)
    try:
        with sqlite3.connect(f"file:{db_file}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name",
            ).fetchall()
            for (name,) in rows:
                try:
                    (n,) = conn.execute(
                        f"SELECT COUNT(*) FROM \"{name}\"",
                    ).fetchone()
                    stats.tables[name] = int(n)
                except sqlite3.DatabaseError:
                    stats.tables[name] = -1
    except sqlite3.DatabaseError as e:
        logger.warning("could not read %s: %s", db_file, e)
    return stats


def _sanitise_config(raw: str) -> str:
    """Strip secrets from a ``config.json`` string.

    Leaves all behavioural config intact — model choice, cadence,
    scraper toggles — so we can reproduce the decisions the agent
    made. Only API keys and the licence key are removed.
    """
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        return raw  # not JSON; keep it verbatim rather than silently drop

    def scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: ("***redacted***" if k.lower() in _SENSITIVE_CONFIG_KEYS
                    else scrub(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [scrub(v) for v in obj]
        return obj

    return json.dumps(scrub(cfg), indent=2)


def export_user_data(
    zip_path: Path,
    *,
    app_version: Optional[str] = None,
) -> ExportSummary:
    """Collect every database + sanitised config into one ``.zip``.

    Args:
        zip_path: Destination file. Parent directory is created on miss.
            Any existing file is overwritten.
        app_version: Optional app version string for the manifest. Kept
            optional so the caller (desktop app) can plug whatever
            version scheme it already tracks.

    Returns:
        :class:`ExportSummary` — use :meth:`~ExportSummary.headline`
        for a one-line confirmation.
    """
    base = user_data_dir()
    data_dir = base / "data"

    summary = ExportSummary(zip_path=zip_path, total_bytes=0)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    # Find every .db in data/. Glob over the data dir only so we never
    # pick up the ffmpeg binary or anything under bin/.
    db_files: List[Path] = []
    if data_dir.exists():
        db_files = sorted(p for p in data_dir.glob("*.db") if p.is_file())

    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
    ) as zf:
        for db_file in db_files:
            stats = _collect_database_stats(db_file)
            summary.databases.append(stats)
            arcname = f"data/{db_file.name}"
            zf.write(db_file, arcname=arcname)
            summary.files.append(arcname)

        # Sanitised config.json — optional (dev runs without one still
        # produce a valid export).
        cfg = config_path()
        if cfg.exists():
            try:
                raw = cfg.read_text(encoding="utf-8")
                zf.writestr("config.sanitised.json", _sanitise_config(raw))
                summary.files.append("config.sanitised.json")
            except OSError as e:
                logger.warning("skipped config.json: %s", e)

        # Manifest — always last so it reflects the final database list.
        manifest: Dict[str, Any] = {
            "schema_version": 1,
            "app_version": app_version or "unknown",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_user_data_dir": str(base),
            "databases": [
                {
                    "path": f"data/{Path(db.path).name}",
                    "bytes": db.bytes,
                    "tables": db.tables,
                }
                for db in summary.databases
            ],
            "files": summary.files + ["export_manifest.json"],
        }
        zf.writestr("export_manifest.json", json.dumps(manifest, indent=2))
        summary.files.append("export_manifest.json")

    summary.total_bytes = zip_path.stat().st_size
    return summary


def default_export_filename() -> str:
    """Suggest a timestamped filename for the save dialog."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"blank-data-{stamp}.zip"
