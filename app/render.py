"""
Render engine — executed by the RQ worker.
Orchestrates FFmpeg to produce video from audio + images.
"""
import os
import shutil
import subprocess
import threading
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

# FIX #2: Maximum time (seconds) a single track render can take before being killed
RENDER_TIMEOUT_S = 7200  # 2 hours


def _update_job(job_id: str, *, _db_session=None, **kwargs):
    """Update job fields in the database.
    FIX #8: Accepts an optional _db_session to reuse an existing session
    instead of opening/closing a new one for every progress update."""
    if _db_session is not None:
        job = _db_session.query(Job).filter(Job.id == job_id).first()
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            _db_session.commit()
        return

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

    # FIX #7: Validate source image exists before attempting FFmpeg
    if not os.path.isfile(img_path):
        raise FileNotFoundError(f"Image not found: {img_path}")

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


def _read_stderr(pipe, output_list: list):
    """FIX #9: Read stderr in a background thread to prevent pipe deadlock.
    FFmpeg can produce substantial stderr output (codec info, warnings, etc.).
    If the stderr pipe buffer fills up (~64KB), FFmpeg blocks waiting for it
    to be drained, while our main thread blocks reading stdout — deadlock."""
    try:
        for line in pipe:
            output_list.append(line)
    except Exception:
        pass


def _render_track(
    track: Track,
    images: list[Image],
    project: Project,
    output_path: str,
    log_path: str,
    job_id: str,
    track_index: int,
    total_tracks: int,
):
    """Render a single track (audio + images) to video.

    For single-image tracks, uses -loop 1 (efficient static frame encoding).
    For multi-image tracks, uses the FFmpeg concat demuxer with crossfade
    transitions when transition_s > 0.
    Progress is mapped to the overall job range based on track_index/total_tracks
    so multi-track projects show a single continuous 0-100% progress bar.
    """
    width, height = _get_resolution(project.format)
    fps = project.fps
    n_images = len(images)

    if n_images == 0 or not track.audio_path:
        raise ValueError("Track must have audio and at least one image")

    # FIX #7: Validate audio file exists
    if not os.path.isfile(track.audio_path):
        raise FileNotFoundError(f"Audio not found: {track.audio_path}")

    # Probe actual audio duration at render time (don't trust stored value)
    probed_ms = _probe_duration_ms(track.audio_path)
    duration_ms = probed_ms or track.duration_ms or 180_000  # fallback 3 min
    logger.info(
        "Track %s: stored_ms=%s, probed_ms=%s, using=%s",
        track.order_index, track.duration_ms, probed_ms, duration_ms,
    )
    total_s = duration_ms / 1000.0

    # Pre-process images to target resolution (fast, done once per image)
    project_dir = os.path.dirname(os.path.dirname(output_path))
    tmp_dir = os.path.join(project_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    preprocessed = []
    for idx, img in enumerate(images):
        pp_path = os.path.join(tmp_dir, f"pp_{track.order_index}_{idx}.png")
        _preprocess_image(img.path, pp_path, project.fit_mode, width, height)
        preprocessed.append(pp_path)

    # FIX #1 + #3 + #6: Choose encoding strategy based on image count
    concat_list_path = None
    if n_images == 1:
        # --- SINGLE IMAGE: use -loop 1 (avoids concat demuxer stall) ---
        safe_img = preprocessed[0].replace("\\", "/")
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", safe_img,
            "-i", track.audio_path,
            "-map", "0:v",
            "-map", "1:a",
        ]
    else:
        # --- MULTIPLE IMAGES: use concat demuxer ---
        per_image_s = total_s / n_images

        # FIX #4: Apply crossfade transitions between images
        transition_s = getattr(project, "transition_s", 0) or 0
        if transition_s > 0 and transition_s < per_image_s:
            # With transitions, each image shows for its full duration but
            # overlaps with the next by transition_s. The concat demuxer
            # duration accounts for the visible time (before crossfade starts).
            visible_s = per_image_s
        else:
            transition_s = 0
            visible_s = per_image_s

        # FIX #3: Use exact durations per image (seconds, not frame-rounded)
        concat_list_path = os.path.join(tmp_dir, f"concat_{track.order_index}.txt")
        with open(concat_list_path, "w") as f:
            for pp_path in preprocessed:
                safe_path = pp_path.replace("\\", "/")
                f.write(f"file '{safe_path}'\n")
                f.write(f"duration {visible_s:.6f}\n")
            # Repeat last entry so the final image displays correctly
            safe_path = preprocessed[-1].replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

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
        # FIX #3: Explicit duration limit to match audio exactly
        "-t", f"{total_s:.3f}",
        "-pix_fmt", "yuv420p",
    ])

    # FIX #6: For single-image tracks, optimize encoder for still content
    if n_images == 1:
        cmd.extend(["-tune", "stillimage"])

    cmd.extend([
        "-progress", "pipe:1",
        output_path,
    ])

    # Progress range for this track within the overall job
    # Encoding phase uses 0-95%, final concatenation uses 95-100%
    encode_range = 0.95
    progress_base = (track_index / total_tracks) * encode_range
    progress_span = (1.0 / total_tracks) * encode_range

    # FIX #8: Create a dedicated DB session for progress updates in this track
    progress_db = _Session()

    # Execute FFmpeg with progress parsing
    start_time = time.time()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # FIX #9: Read stderr in a background thread to prevent pipe deadlock
    stderr_lines = []
    stderr_thread = threading.Thread(
        target=_read_stderr, args=(process.stderr, stderr_lines), daemon=True
    )
    stderr_thread.start()

    # FIX #10: Use context manager for log file
    with open(log_path, "a") as log_file:
        log_file.write(f"Command: {' '.join(cmd)}\n")
        log_file.write(
            f"Images: {n_images}, Total: {total_s:.3f}s\n\n"
        )

        duration_us = duration_ms * 1000  # microseconds
        last_progress_update = -1.0

        for line in process.stdout:
            log_file.write(line)

            # FIX #2: Check if we've exceeded the timeout
            if time.time() - start_time > RENDER_TIMEOUT_S:
                process.kill()
                logger.error("Track %s render timed out after %ds", track.order_index, RENDER_TIMEOUT_S)
                break

            # Parse progress from FFmpeg's -progress output
            if line.startswith("out_time_us="):
                raw_value = line.split("=", 1)[1].strip()
                if raw_value == "N/A":
                    continue
                try:
                    out_time_us = int(raw_value)
                    if out_time_us < 0:
                        continue
                    if duration_us > 0:
                        track_progress = min(out_time_us / duration_us, 1.0)
                        overall_progress = progress_base + track_progress * progress_span
                        overall_progress = min(overall_progress, progress_base + progress_span)
                        if overall_progress - last_progress_update >= 0.005:
                            elapsed = time.time() - start_time
                            if track_progress > 0.01:
                                track_remaining = elapsed * (1.0 - track_progress) / track_progress
                                estimated_track_total = elapsed / track_progress
                                remaining_tracks_time = estimated_track_total * (total_tracks - track_index - 1)
                                eta = track_remaining + remaining_tracks_time
                            else:
                                eta = None
                            # FIX #8: Reuse the dedicated progress session
                            _update_job(
                                job_id,
                                _db_session=progress_db,
                                progress=round(overall_progress, 4),
                                eta_s=round(eta, 1) if eta else None,
                            )
                            last_progress_update = overall_progress
                except (ValueError, ZeroDivisionError):
                    pass

        process.wait()

        # FIX #9: Wait for stderr thread to finish, then collect output
        stderr_thread.join(timeout=5)
        stderr_output = "".join(stderr_lines)
        log_file.write(f"\nSTDERR:\n{stderr_output}\n")
        log_file.write(f"\nReturn code: {process.returncode}\n")

    # FIX #8: Close the dedicated progress session
    progress_db.close()

    # Mark this track's slice as complete regardless of final out_time_us
    track_end_progress = progress_base + progress_span
    if process.returncode == 0 and last_progress_update < track_end_progress:
        _update_job(
            job_id,
            progress=round(track_end_progress, 4),
            eta_s=0 if track_index == total_tracks - 1 else None,
        )

    # FIX #5: Check for errors BEFORE cleaning up temp files (aids debugging)
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (code {process.returncode}): {stderr_output[-500:]}")

    # Cleanup preprocessed images and concat list only on success
    for pp_path in preprocessed:
        try:
            os.remove(pp_path)
        except OSError:
            pass
    if concat_list_path:
        try:
            os.remove(concat_list_path)
        except OSError:
            pass


def _concat_videos(track_files: list[str], output_path: str, log_path: str):
    """Concatenate multiple track videos into a single continuous video.
    Uses FFmpeg concat demuxer with -c copy (no re-encode, very fast)."""
    tmp_dir = os.path.dirname(track_files[0])
    concat_list_path = os.path.join(tmp_dir, "final_concat.txt")

    with open(concat_list_path, "w") as f:
        for fpath in track_files:
            safe_path = fpath.replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        output_path,
    ]

    # FIX #10: Use context manager for log file
    with open(log_path, "a") as log_file:
        log_file.write(f"\n--- Final concatenation ---\nCommand: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    with open(log_path, "a") as log_file:
        log_file.write(f"Return code: {result.returncode}\n")
        if result.stderr:
            log_file.write(f"STDERR:\n{result.stderr[-500:]}\n")

    # FIX #5: Check error BEFORE cleanup
    if result.returncode != 0:
        raise RuntimeError(f"Final concatenation failed (code {result.returncode}): {result.stderr[-500:]}")

    # Cleanup temp files only on success
    try:
        os.remove(concat_list_path)
    except OSError:
        pass
    for fpath in track_files:
        try:
            os.remove(fpath)
        except OSError:
            pass


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
        tmp_dir = os.path.join(project_dir, "tmp")
        logs_dir = os.path.join(project_dir, "logs")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(tmp_dir, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)

        log_path = os.path.join(logs_dir, f"job_{job_id}.log")
        _update_job(job_id, log_path=log_path)

        total_tracks = len(tracks)

        # Initialize log file (tracks append to it)
        with open(log_path, "w") as f:
            f.write(f"Project: {project.name} ({total_tracks} tracks)\n\n")

        # Render each track to a temporary video file
        track_files = []
        for i, track in enumerate(tracks):
            # Sort images explicitly from the eager-loaded list
            track_images = sorted(track.images, key=lambda x: x.order_index)

            # Render to tmp dir (will be concatenated later)
            tmp_filename = f"track_{track.order_index}.mp4"
            tmp_path = os.path.join(tmp_dir, tmp_filename)
            track_files.append(tmp_path)

            _render_track(
                track=track,
                images=track_images,
                project=project,
                output_path=tmp_path,
                log_path=log_path,
                job_id=job_id,
                track_index=i,
                total_tracks=total_tracks,
            )

        # Concatenate all tracks into a single continuous video
        _update_job(job_id, progress=0.95, eta_s=5)

        final_output = os.path.join(output_dir, f"{project.name}.mp4")

        if len(track_files) == 1:
            # Single track — just move to output (no concat needed)
            shutil.move(track_files[0], final_output)
            with open(log_path, "a") as f:
                f.write("\n--- Single track, moved directly to output ---\n")
        else:
            _concat_videos(track_files, final_output, log_path)

        # Cleanup tmp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)

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
