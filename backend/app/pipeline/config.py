"""Pipeline configuration: paths, constants, helpers."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Paths -------------------------------------------------------------------

_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # eurika/backend/
_PROJECT_ROOT = _BACKEND_ROOT.parents[1]  # eurika/../

VIDEOS_DIR = _PROJECT_ROOT / "eurika" / "webinars" / "videos"
PIPELINE_OUTPUT_DIR = _BACKEND_ROOT / "pipeline_output"

# --- Audio -------------------------------------------------------------------

AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB OpenAI limit
CHUNK_DURATION_SECONDS = 300  # 5 minutes — smaller chunks avoid OpenAI 500 errors

# --- Models ------------------------------------------------------------------

TRANSCRIBE_MODEL = "gpt-4o-transcribe"
STRUCTURE_MODEL = "gpt-4o"
EXTRACT_MODEL = "gpt-4o"
VIDEO_NAMESPACE = "sales"

# --- Helpers -----------------------------------------------------------------


def get_video_slug(filename: str) -> str:
    """Convert video filename to a safe directory slug."""
    name = re.sub(r"\s*\(\d+p\)\.mp4$", "", filename)  # strip " (240p).mp4"
    name = name.strip().replace(" ", "_")
    # keep cyrillic and basic chars
    name = re.sub(r"[^\w\-]", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def get_output_dir(video_slug: str) -> Path:
    """Return (and create) output directory for a video."""
    out = PIPELINE_OUTPUT_DIR / video_slug
    out.mkdir(parents=True, exist_ok=True)
    return out


def check_ffmpeg() -> bool:
    """Check that ffmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
