"""Webinar video → RAG knowledge base pipeline CLI.

Usage:
    PYTHONPATH=. python -m app.pipeline.cli run --video "Обзор_платформы (240p).mp4"
    PYTHONPATH=. python -m app.pipeline.cli run --all
    PYTHONPATH=. python -m app.pipeline.cli status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.pipeline.config import (
    PIPELINE_OUTPUT_DIR,
    VIDEO_NAMESPACE,
    VIDEOS_DIR,
    check_ffmpeg,
    get_output_dir,
    get_video_slug,
)
from app.pipeline.steps.clean_structure import clean_and_structure
from app.pipeline.steps.extract_audio import extract_audio
from app.pipeline.steps.extract_topics import extract_topics
from app.pipeline.steps.format_markdown import format_markdown
from app.pipeline.steps.load_rag import load_to_rag
from app.pipeline.steps.transcribe import transcribe_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def run_pipeline(video_path: Path, force: bool = False) -> dict:
    """Execute the full 6-step pipeline on a single video."""
    settings = get_settings()
    api_key = settings.openai_api_key
    slug = get_video_slug(video_path.name)
    output_dir = get_output_dir(slug)
    state_path = output_dir / "pipeline_state.json"

    logger.info("=" * 60)
    logger.info("Video: %s", video_path.name)
    logger.info("Slug: %s", slug)
    logger.info("Output: %s", output_dir)
    logger.info("=" * 60)

    if force:
        for f in output_dir.glob("*"):
            if f.is_file() and f.name != "pipeline_state.json":
                f.unlink()
        logger.info("Force mode: cleared previous outputs")

    state = {"video": video_path.name, "slug": slug, "steps": {}, "status": "running"}
    t0 = time.time()

    # Step 1: Extract audio
    logger.info("[1/6] Extracting audio...")
    wav_path = extract_audio(video_path, output_dir)
    state["steps"]["extract_audio"] = "done"
    logger.info("[1/6] Done: %s (%.1f MB)", wav_path.name, wav_path.stat().st_size / 1e6)

    # Step 2: Transcribe
    logger.info("[2/6] Transcribing...")
    raw_transcript = transcribe_audio(wav_path, output_dir, api_key)
    state["steps"]["transcribe"] = "done"
    logger.info("[2/6] Done: %d chars", len(raw_transcript))

    # Step 3: Clean & structure
    logger.info("[3/6] Cleaning & structuring...")
    structured_text = clean_and_structure(raw_transcript, output_dir, api_key)
    state["steps"]["clean_structure"] = "done"
    logger.info("[3/6] Done: %d chars", len(structured_text))

    # Step 4: Extract topics (from RAW transcript for maximum detail)
    logger.info("[4/6] Extracting topics...")
    topics = extract_topics(raw_transcript, output_dir, api_key)
    state["steps"]["extract_topics"] = "done"
    faq_count = len(topics.get("faq", []))
    obj_count = len(topics.get("objections", []))
    logger.info("[4/6] Done: %d FAQ, %d objections", faq_count, obj_count)

    # Step 5: Format markdown
    logger.info("[5/6] Formatting markdown...")
    video_title = get_video_slug(video_path.name).replace("_", " ")
    md_path = format_markdown(structured_text, topics, video_title, output_dir)
    state["steps"]["format_markdown"] = "done"
    logger.info("[5/6] Done: %s", md_path.name)

    # Step 6: Load to RAG
    logger.info("[6/6] Loading to RAG (namespace=%s)...", VIDEO_NAMESPACE)
    chunk_count = load_to_rag(
        md_path,
        namespace=VIDEO_NAMESPACE,
        api_key=api_key,
        embedding_model=settings.openai_embedding_model,
        database_url=settings.database_url,
        video_slug=slug,
    )
    state["steps"]["load_rag"] = "done"
    logger.info("[6/6] Done: %d chunks stored", chunk_count)

    elapsed = time.time() - t0
    state["status"] = "completed"
    state["chunks_loaded"] = chunk_count
    state["elapsed_seconds"] = round(elapsed, 1)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("=" * 60)
    logger.info("COMPLETED in %.1fs — %d chunks loaded", elapsed, chunk_count)
    logger.info("=" * 60)
    return state


def cmd_run(args: argparse.Namespace) -> None:
    """Run pipeline on one or all videos."""
    if not check_ffmpeg():
        print("ERROR: ffmpeg not found. Install via: brew install ffmpeg")
        sys.exit(1)

    settings = get_settings()
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)
    if not settings.database_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    if args.video:
        video_path = VIDEOS_DIR / args.video
        if not video_path.exists():
            print(f"ERROR: Video not found: {video_path}")
            sys.exit(1)
        run_pipeline(video_path, force=args.force)
    elif args.all:
        videos = sorted(VIDEOS_DIR.glob("*.mp4"))
        if not videos:
            print(f"ERROR: No MP4 files found in {VIDEOS_DIR}")
            sys.exit(1)
        print(f"Found {len(videos)} videos")
        for i, vp in enumerate(videos, 1):
            print(f"\n--- [{i}/{len(videos)}] {vp.name} ---")
            slug = get_video_slug(vp.name)
            state_path = get_output_dir(slug) / "pipeline_state.json"
            if state_path.exists() and not args.force:
                state = json.loads(state_path.read_text())
                if state.get("status") == "completed":
                    print(f"  Already completed, skipping (use --force to rerun)")
                    continue
            run_pipeline(vp, force=args.force)
    else:
        print("ERROR: Specify --video <filename> or --all")
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    """Show pipeline status for all processed videos."""
    if not PIPELINE_OUTPUT_DIR.exists():
        print("No pipeline output yet.")
        return

    dirs = sorted(d for d in PIPELINE_OUTPUT_DIR.iterdir() if d.is_dir())
    if not dirs:
        print("No pipeline output yet.")
        return

    for d in dirs:
        state_path = d / "pipeline_state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            status = state.get("status", "unknown")
            chunks = state.get("chunks_loaded", "?")
            elapsed = state.get("elapsed_seconds", "?")
            print(f"  {d.name}: {status} ({chunks} chunks, {elapsed}s)")
        else:
            print(f"  {d.name}: in progress (no state file)")


def cmd_list(args: argparse.Namespace) -> None:
    """List all videos in the videos directory."""
    if not VIDEOS_DIR.exists():
        print(f"Videos directory not found: {VIDEOS_DIR}")
        return

    videos = sorted(VIDEOS_DIR.glob("*.mp4"))
    print(f"Found {len(videos)} videos in {VIDEOS_DIR}:\n")
    for v in videos:
        size_mb = v.stat().st_size / (1024 * 1024)
        print(f"  {size_mb:6.1f} MB  {v.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Webinar video → RAG pipeline")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Process video(s)")
    p_run.add_argument("--video", type=str, help="Single video filename")
    p_run.add_argument("--all", action="store_true", help="Process all videos")
    p_run.add_argument("--force", action="store_true", help="Force reprocessing")

    sub.add_parser("status", help="Show processing status")
    sub.add_parser("list", help="List available videos")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
