"""Step 1: Extract audio from MP4 video using FFmpeg."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.pipeline.config import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, CHUNK_DURATION_SECONDS, MAX_UPLOAD_BYTES

logger = logging.getLogger(__name__)


def extract_audio(video_path: Path, output_dir: Path) -> Path:
    """Extract audio track from MP4 to WAV 16kHz mono."""
    wav_path = output_dir / "audio.wav"
    if wav_path.exists():
        logger.info("audio.wav already exists, skipping extraction")
        return wav_path

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(AUDIO_SAMPLE_RATE),
        "-ac", str(AUDIO_CHANNELS),
        "-y",
        str(wav_path),
    ]
    logger.info("Extracting audio: %s", video_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-500:]}")

    size_mb = wav_path.stat().st_size / (1024 * 1024)
    logger.info("Audio extracted: %.1f MB", size_mb)
    return wav_path


def split_audio(wav_path: Path, output_dir: Path) -> list[Path]:
    """Split WAV into chunks if it exceeds the 25MB upload limit."""
    if wav_path.stat().st_size <= MAX_UPLOAD_BYTES:
        return [wav_path]

    chunks_dir = output_dir / "audio_chunks"
    chunks_dir.mkdir(exist_ok=True)

    cmd = [
        "ffmpeg", "-i", str(wav_path),
        "-f", "segment",
        "-segment_time", str(CHUNK_DURATION_SECONDS),
        "-c", "copy",
        "-y",
        str(chunks_dir / "chunk_%03d.wav"),
    ]
    logger.info("Splitting audio into %ds chunks", CHUNK_DURATION_SECONDS)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg split failed: {result.stderr[-500:]}")

    chunks = sorted(chunks_dir.glob("chunk_*.wav"))
    logger.info("Split into %d chunks", len(chunks))
    return chunks
