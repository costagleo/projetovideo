"""
Render engine — executed by the RQ worker.
Orchestrates FFmpeg to produce video from audio + images.
"""
import os
import subprocess
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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


def _get_resolution(fmt: str) -> tuple[int, int]:
    if fmt == "vertical":
        return 1080, 1920
    return 1920, 1080  # landscape default


def _build_ffmpeg_filter(fit_mode: str, width: int, height: int) -> str:
    """Build the FFmpeg filter_complex for image fitting."""
    if fit_mode == "smart_background":
        # Background: blurred cover; Foreground: contain (fit)
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:5[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg];"
            f"[bg][fg]overlay=0:0"
        )
    elif fit_mode == "contain_pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    elif fit_mode == "cover_crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    # Default to smart_background
    return _build_ffmpeg_filter("smart_background", width, height)


def _build_slideshow_input(images: list[Image], duration_ms: int, transition_s: float) -> list[str]:
    """Build FFmpeg input arguments for a slideshow of images."""
    n_images = len(images)
    if n_images == 0:
        return []

    # Duration per image in seconds
    total_s = duration_ms / 1000.0
    per_image_s = total_s / n_images

    args = []
    for img in sorted(images, key=lambda x: x.order_index):
        args.extend(["-loop", "1", "-t", f"{per_image_s:.3f}", "-i", img.path])

    return args


def _render_track(
    track: Track,
    project: Project,
    output_path: str,
    log_path: str,
    job_id: str,
):
    """Render a single track (audio + images) to video."""
    width, height = _get_resolution(project.format)
    images = sorted(track.images, key=lambda x: x.order_index)
    n_images = len(images)

    if n_images == 0 or not track.audio_path:
        raise ValueError("Track must have audio and at least one image")

    duration_ms = track.duration_ms or 180_000  # fallback 3 min
    total_s = duration_ms / 1000.0
    per_image_s = total_s / n_images

    # Build FFmpeg command
    cmd = ["ffmpeg", "-y"]

    # Add image inputs
    for img in images:
        cmd.extend(["-loop", "1", "-t", f"{per_image_s:.3f}", "-i", img.path])

    # Add audio input
    cmd.extend(["-i", track.audio_path])

    # Build filter complex
    audio_idx = n_images  # audio is the last input

    if n_images == 1:
        if project.fit_mode == "smart_background":
            filter_complex = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},boxblur=20:5[bg];"
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg];"
                f"[bg][fg]overlay=0:0[outv]"
            )
        else:
            fit_filter = _build_ffmpeg_filter(project.fit_mode, width, height)
            filter_complex = f"[0:v]{fit_filter}[outv]"
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", f"{audio_idx}:a",
        ])
    else:
        filter_parts = []
        for i in range(n_images):
            if project.fit_mode == "smart_background":
                # For each image: create blurred bg + sharp fg overlay
                filter_parts.append(
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},boxblur=20:5[bg{i}]"
                )
                filter_parts.append(
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg{i}]"
                )
                filter_parts.append(
                    f"[bg{i}][fg{i}]overlay=0:0,setpts=PTS-STARTPTS[v{i}]"
                )
            else:
                fit_filter = _build_ffmpeg_filter(project.fit_mode, width, height)
                filter_parts.append(f"[{i}:v]{fit_filter},setpts=PTS-STARTPTS[v{i}]")

        # Concat all processed video streams
        concat_inputs = "".join(f"[v{i}]" for i in range(n_images))
        filter_parts.append(f"{concat_inputs}concat=n={n_images}:v=1:a=0[outv]")

        filter_complex = ";".join(filter_parts)
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", f"{audio_idx}:a",
        ])

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
        "-r", str(project.fps),
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
    log_file.write(f"Command: {' '.join(cmd)}\n\n")

    duration_us = duration_ms * 1000  # microseconds

    for line in process.stdout:
        log_file.write(line)

        # Parse progress from FFmpeg's -progress output
        if line.startswith("out_time_us="):
            try:
                out_time_us = int(line.split("=")[1].strip())
                if duration_us > 0:
                    progress = min(out_time_us / duration_us, 1.0)
                    elapsed = time.time() - start_time
                    eta = (elapsed / progress - elapsed) if progress > 0.01 else None
                    _update_job(
                        job_id,
                        progress=round(progress * 100, 1),
                        eta_s=round(eta, 1) if eta else None,
                    )
            except (ValueError, ZeroDivisionError):
                pass

    process.wait()
    stderr_output = process.stderr.read()
    log_file.write(f"\nSTDERR:\n{stderr_output}\n")
    log_file.write(f"\nReturn code: {process.returncode}\n")
    log_file.close()

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

        tracks = (
            db.query(Track)
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
            output_filename = f"{project.name}_track{track.order_index}.mp4"
            output_path = os.path.join(output_dir, output_filename)

            _render_track(
                track=track,
                project=project,
                output_path=output_path,
                log_path=log_path,
                job_id=job_id,
            )

        # Mark as done
        _update_job(
            job_id,
            status="done",
            progress=100.0,
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
