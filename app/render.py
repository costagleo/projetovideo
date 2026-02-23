"""
Render engine — executed by the RQ worker.
Orchestrates FFmpeg to produce video from audio + images.
"""
import os
import subprocess
import time
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload

from app.config import get_settings
from app.models import Job, Project, Track, Image

settings = get_settings()

# The worker runs in its own process, so we create a separate DB session
_engine = create_engine(
    f"sqlite:///{settings.DB_PATH}",
    connect_args={"check_same_thread": False},
)
_Session = sessionmaker(bind=_engine)


def _update_job(job_id: str, **kwargs):
    """Update job fields in the database."""
    db = _Session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            db.commit()
    finally:
        db.close()


def _probe_duration_ms(audio_path: str) -> int | None:
    """Probe actual audio duration using ffprobe at render time."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                audio_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        seconds = float(result.stdout.strip())
        return int(seconds * 1000)
    except Exception:
        return None


def _get_resolution(fmt: str) -> tuple[int, int]:
    if fmt == "vertical":
        return 1080, 1920
    return 1920, 1080  # landscape default


def _preprocess_image(img_path: str, out_path: str, fit_mode: str, width: int, height: int):
    """Pre-process a single image to target resolution with fit mode applied.
    This produces a single frame at the exact output resolution, so the main
    encode loop doesn't need any expensive per-frame filtering."""

    if fit_mode == "smart_background":
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:5[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg];"
            f"[bg][fg]overlay=0:0[out]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", img_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-frames:v", "1",
            out_path,
        ]
    elif fit_mode == "contain_pad":
        cmd = [
            "ffmpeg", "-y", "-i", img_path,
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-frames:v", "1",
            out_path,
        ]
    elif fit_mode == "cover_crop":
        cmd = [
            "ffmpeg", "-y", "-i", img_path,
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            ),
            "-frames:v", "1",
            out_path,
        ]
    else:
        # Default to smart_background
        return _preprocess_image(img_path, out_path, "smart_background", width, height)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Image preprocessing failed for {img_path}: {result.stderr[-300:]}")


def _render_track(
    track: Track,
    images: list[Image],
    project: Project,
    output_path: str,
    log_path: str,
    job_id: str,
):
    """Render a single track (audio + images) to video.

    Uses the FFmpeg concat demuxer instead of -loop 1 + concat filter.
    This avoids:
      - Huge dup_frames from mismatched input/output framerates
      - Long stalls at startup (N/A progress for many seconds)
      - Stalls at image transition points (concat filter bottleneck)
      - Slow encoding speed from repeatedly decoding looped images
    """
    width, height = _get_resolution(project.format)
    fps = project.fps
    n_images = len(images)

    if n_images == 0 or not track.audio_path:
        raise ValueError("Track must have audio and at least one image")

    # Probe actual audio duration at render time (don't trust stored value)
    probed_ms = _probe_duration_ms(track.audio_path)
    duration_ms = probed_ms or track.duration_ms or 180_000  # fallback 3 min
    logger.info(
        "Track %s: stored_ms=%s, probed_ms=%s, using=%s",
        track.order_index, track.duration_ms, probed_ms, duration_ms,
    )
    total_s = duration_ms / 1000.0
    per_image_s = total_s / n_images

    # Pre-process images to target resolution (fast, done once per image)
    project_dir = os.path.dirname(os.path.dirname(output_path))
    tmp_dir = os.path.join(project_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    preprocessed = []
    for idx, img in enumerate(images):
        pp_path = os.path.join(tmp_dir, f"pp_{track.order_index}_{idx}.png")
        _preprocess_image(img.path, pp_path, project.fit_mode, width, height)
        preprocessed.append(pp_path)

    # Calculate frames per image to avoid fractional durations
    frames_per_image = max(1, round(per_image_s * fps))

    # Build concat demuxer input file listing each image with its duration
    concat_list_path = os.path.join(tmp_dir, f"concat_{track.order_index}.txt")
    with open(concat_list_path, "w") as f:
        for pp_path in preprocessed:
            # Use forward slashes for FFmpeg compatibility
            safe_path = pp_path.replace("\\", "/")
            f.write(f"file '{safe_path}'\n")
            f.write(f"duration {frames_per_image / fps:.6f}\n")
        # Repeat last entry so the final image displays correctly
        safe_path = preprocessed[-1].replace("\\", "/")
        f.write(f"file '{safe_path}'\n")

    # Build FFmpeg command using concat demuxer (much faster than -loop 1)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-i", track.audio_path,
        "-map", "0:v",
        "-map", "1:a",
    ]

    # Output settings
    preset_map = {
        "fast": "ultrafast",
        "balanced": "medium",
        "quality": "slow",
    }
    ffmpeg_preset = preset_map.get(project.preset, "medium")

    cmd.extend([
        "-c:v", "libx264",
        "-preset", ffmpeg_preset,
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", str(fps),
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-progress", "pipe:1",
        output_path,
    ])

    # Execute FFmpeg with progress parsing
    start_time = time.time()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    log_file = open(log_path, "w")
    log_file.write(f"Command: {' '.join(cmd)}\n")
    log_file.write(
        f"Images: {n_images}, Per-image: {per_image_s:.3f}s "
        f"({frames_per_image} frames @ {fps}fps), Total: {total_s:.3f}s\n\n"
    )

    duration_us = duration_ms * 1000  # microseconds
    last_progress_update = 0.0

    for line in process.stdout:
        log_file.write(line)

        # Parse progress from FFmpeg's -progress output
        if line.startswith("out_time_us="):
            raw_value = line.split("=", 1)[1].strip()
            # Skip N/A values that occur during initialization
            if raw_value == "N/A":
                continue
            try:
                out_time_us = int(raw_value)
                if out_time_us < 0:
                    continue
                if duration_us > 0:
                    progress = min(out_time_us / duration_us, 1.0)
                    # Throttle DB updates: only write when progress changes
                    # by at least 0.5% to reduce DB pressure
                    if progress - last_progress_update >= 0.005 or progress >= 1.0:
                        elapsed = time.time() - start_time
                        eta = (elapsed / progress - elapsed) if progress > 0.01 else None
                        _update_job(
                            job_id,
                            progress=round(progress, 4),
                            eta_s=round(eta, 1) if eta else None,
                        )
                        last_progress_update = progress
            except (ValueError, ZeroDivisionError):
                pass

    process.wait()
    stderr_output = process.stderr.read()
    log_file.write(f"\nSTDERR:\n{stderr_output}\n")
    log_file.write(f"\nReturn code: {process.returncode}\n")
    log_file.close()

    # Cleanup preprocessed images and concat list
    for pp_path in preprocessed:
        try:
            os.remove(pp_path)
        except OSError:
            pass
    try:
        os.remove(concat_list_path)
    except OSError:
        pass
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (code {process.returncode}): {stderr_output[-500:]}")


def execute_render(job_id: str):
    """Main entry point called by the RQ worker."""
    db = _Session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        project = db.query(Project).filter(Project.id == job.project_id).first()
        if not project:
            _update_job(job_id, status="error", error_msg="Projeto não encontrado")
            return

        # Eager-load tracks AND their images to avoid lazy loading issues
        tracks = (
            db.query(Track)
            .options(joinedload(Track.images))
            .filter(Track.project_id == project.id)
            .order_by(Track.order_index)
            .all()
        )

        # Mark as running
        _update_job(
            job_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            progress=0.0,
        )

        project_dir = os.path.join(settings.CURRENT_SECTION_PATH, "projects", project.id)
        output_dir = os.path.join(project_dir, "output")
        logs_dir = os.path.join(project_dir, "logs")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)

        log_path = os.path.join(logs_dir, f"job_{job_id}.log")
        _update_job(job_id, log_path=log_path)

        for track in tracks:
            # Sort images explicitly from the eager-loaded list
            track_images = sorted(track.images, key=lambda x: x.order_index)

            output_filename = f"{project.name}_track{track.order_index}.mp4"
            output_path = os.path.join(output_dir, output_filename)

            _render_track(
                track=track,
                images=track_images,
                project=project,
                output_path=output_path,
                log_path=log_path,
                job_id=job_id,
            )

        # Mark as done
        _update_job(
            job_id,
            status="done",
            progress=1.0,
            eta_s=0,
            finished_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        _update_job(
            job_id,
            status="error",
            error_msg=str(e)[:1000],
            finished_at=datetime.now(timezone.utc),
        )
        raise
    finally:
        db.close()
