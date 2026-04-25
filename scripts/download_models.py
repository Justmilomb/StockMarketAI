"""Pre-build model bundler.

Run before ``pyinstaller installer/blank.spec`` to fill
``desktop/assets/models/`` with the HuggingFace artefacts the spec
includes in the build. Idempotent — if a slug's directory already
contains a config.json (the marker of a complete snapshot) the
download is skipped, so re-running the build is fast.

Resolution order for the auth token:
    1. ``HF_TOKEN_READ``
    2. legacy ``HF_TOKEN`` (back-compat)
    3. anonymous (rate-limited) — works for public models like these

Usage::

    python scripts/download_models.py            # all bundles
    python scripts/download_models.py finbert    # one slug
    python scripts/download_models.py --force    # ignore the cache marker

Models bundled (≈900 MB total):
  * kronos-tokenizer  ~25 MB    NeoQuasar/Kronos-Tokenizer-base
  * kronos-base     ~410 MB    NeoQuasar/Kronos-base (102M params)
  * finbert         ~440 MB    ProsusAI/finbert

Why Kronos-base, not -small or -mini: base is the most accurate
open-source Kronos checkpoint and still runs fine on CPU on any
modern desktop. Smaller variants are only worth picking when the
installer bundle size is a hard constraint.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("download_models")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Slug → HuggingFace repo. Update both sides if you swap a model.
# core/local_models.py and core/kronos_forecaster.py reference these
# slugs by name; renaming a slug requires updating those modules too.
BUNDLES: Dict[str, str] = {
    "kronos-tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
    "kronos-base": "NeoQuasar/Kronos-base",
    "finbert": "ProsusAI/finbert",
}

# Files we don't need to ship — keeps the bundle lean.
IGNORE_PATTERNS: List[str] = [
    "*.msgpack",  # flax weights
    "*.h5",       # tf weights — we run torch
    "*.ot",       # rust-bert
    "*.onnx",
    "tf_model*",
    "rust_model*",
    "flax_model*",
    "*.bin.index.json.bak",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _target_dir(slug: str) -> Path:
    return _repo_root() / "desktop" / "assets" / "models" / slug


def _is_complete(target: Path) -> bool:
    """A directory is "complete" if it has a config.json — the canonical marker
    of a finished HuggingFace snapshot."""
    return (target / "config.json").exists()


def _resolve_token() -> Optional[str]:
    for var in ("HF_TOKEN_READ", "HF_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return None


def download_one(slug: str, repo_id: str, force: bool = False) -> bool:
    """Snapshot ``repo_id`` into ``desktop/assets/models/<slug>/``.

    Returns True on success (or when already cached and ``force`` is
    False), False on failure. Never raises — the build script can
    decide whether to abort.
    """
    target = _target_dir(slug)
    target.mkdir(parents=True, exist_ok=True)

    if _is_complete(target) and not force:
        logger.info("[%s] already cached at %s — skip", slug, target)
        return True

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        logger.error("huggingface_hub is not installed; pip install huggingface_hub")
        return False

    token = _resolve_token()
    if not token:
        logger.warning(
            "[%s] no HF_TOKEN_READ set — falling back to anonymous "
            "(rate-limited but works for public models)", slug,
        )

    logger.info("[%s] downloading %s → %s", slug, repo_id, target)
    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(target),
            local_dir_use_symlinks=False,
            token=token,
            ignore_patterns=IGNORE_PATTERNS,
            resume_download=True,
        )
    except Exception as e:
        logger.error("[%s] download failed: %s", slug, e)
        return False

    if not _is_complete(target):
        logger.error("[%s] download finished but config.json missing — incomplete", slug)
        return False

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    logger.info("[%s] OK (%.1f MB)", slug, size / (1024 * 1024))
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "slugs", nargs="*", help="specific slugs to download (default: all)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-download even if config.json is already present",
    )
    args = parser.parse_args(argv)

    selected = list(args.slugs) if args.slugs else list(BUNDLES.keys())
    unknown = [s for s in selected if s not in BUNDLES]
    if unknown:
        logger.error("unknown slug(s): %s. Known: %s", unknown, list(BUNDLES.keys()))
        return 2

    failures: List[str] = []
    for slug in selected:
        ok = download_one(slug, BUNDLES[slug], force=args.force)
        if not ok:
            failures.append(slug)

    if failures:
        logger.error("FAILED: %s", failures)
        return 1
    logger.info("All %d bundle(s) ready under desktop/assets/models/", len(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
