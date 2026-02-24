"""
Render engine — executed by the RQ worker.
Orchestrates FFmpeg to produce video from audio + images.

Uses a segment-based encoding strategy: instead of encoding every frame
for the full audio duration, a short (2s) video segment is created from
each static image. These segments are then tiled via the FFmpeg concat
demuxer with -c:v copy (no video re-encoding). Audio is encoded (WAV→AAC)
during the assembly step, which also enables progress tracking.
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

# Maximum time (seconds) a single track render can take before being killed
RENDER_TIMEOUT_S = 7200  # 2 hours

# Duration of each pre-encoded video segment (seconds).
# Shorter = faster segment creation, but more concat entries.
# 2 seconds at 30fps = 60 frames — very fast to encode.
SEGMENT_DURATION_S = 2.0


# ---------------------------------------------------------------------------
# Cancellation support
# ---------------------------------------------------------------------------

class RenderCancelled(Exception):
    """Raised when a job is cancelled by the user during rendering."""
    pass


def _check_cancelled(job_id: str, process=None):
    """Check if the job has been cancelled via Redis flag.
    If cancelled, kill the FFmpeg process (if any) and raise RenderCancelled.
    Uses lazy import to avoid circular dependency with app.worker."""
    from app.worker import is_cancelled, clear_cancel_flag

    if is_cancelled(job_id):
        if process is not None:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
        clear_cancel_flag(job_id)
        raise RenderCancelled(f"Job {job_id} cancelled by user")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _update_job(job_id: str, *, _db_session=None, **kwargs):
    """Update job fields in the database.
    Accepts an optional _db_session to reuse an existing session
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


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------

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
    This produces a single frame at the exact output resolution."""

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
        return _preprocess_image(img_path, out_path, "smart_background", width, height)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Image preprocessing failed for {img_path}: {result.stderr[-300:]}")


def _encode_segment(image_path: str, output_path: str, fps: int, preset: str):
    """Encode a short (2s) H.264 video segment from a single static image.

    Produces a segment with consistent codec parameters (resolution, fps,
    pix_fmt) that can be safely repeated via concat demuxer with -c:v copy.
    The -movflags faststart ensures the moov atom is at the beginning,
    which is required for proper concat demuxer seeking.
    """
    preset_map = {
        "fast": "ultrafast",
        "balanced": "medium",
        "quality": "slow",
    }
    ffmpeg_preset = preset_map.get(preset, "medium")

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", f"{SEGMENT_DURATION_S:.6f}",
        "-c:v", "libx264",
        "-preset", ffmpeg_preset,
        "-crf", "23",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-tune", "stillimage",
        "-movflags", "faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Segment encoding failed for {image_path}: {result.stderr[-300:]}")


def _build_segment_concat_list(
    segment_paths: list[str],
    image_durations: list[float],
    concat_list_path: str,
):
    """Build a concat demuxer list file that repeats segment references
    to fill the required duration for each image.

    The concat demuxer reads each 'file' entry and plays it for 'duration'
    seconds. By repeating the same segment file with duration entries, we
    tile the video without re-encoding.

    For the last entry of each image block, the duration may be less than
    SEGMENT_DURATION_S. The concat demuxer correctly reads only that many
    seconds from the segment file.
    """
    with open(concat_list_path, "w") as f:
        for seg_path, total_dur in zip(segment_paths, image_durations):
            safe_path = seg_path.replace("\\", "/")

            full_segments = int(total_dur // SEGMENT_DURATION_S)
            remainder = total_dur - (full_segments * SEGMENT_DURATION_S)

            # Write full-length segment references
            for _ in range(full_segments):
                f.write(f"file '{safe_path}'\n")
                f.write(f"duration {SEGMENT_DURATION_S:.6f}\n")

            # Write remainder segment (if any significant time left)
            if remainder > 0.001:
                f.write(f"file '{safe_path}'\n")
                f.write(f"duration {remainder:.6f}\n")

        # Trailing file entry required by concat demuxer to properly
        # read the last duration-specified segment
        safe_path = segment_paths[-1].replace("\\", "/")
        f.write(f"file '{safe_path}'\n")


def _read_stderr(pipe, output_list: list):
    """Read stderr in a background thread to prevent pipe deadlock."""
    try:
        for line in pipe:
            output_list.append(line)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Track rendering
# ---------------------------------------------------------------------------

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
    """Render a single track (audio + images) to video using segment-based
    encoding for maximum performance.

    Phase A: Preprocess images to target resolution (PNG).
    Phase B: Encode a short (2s) video segment from each image.
    Phase C: Assemble final video by tiling segments with -c:v copy + audio.

    Progress is mapped to the overall job range based on track_index/total_tracks.
    """
    width, height = _get_resolution(project.format)
    fps = project.fps
    n_images = len(images)

    if n_images == 0 or not track.audio_path:
        raise ValueError("Track must have audio and at least one image")

    if not os.path.isfile(track.audio_path):
        raise FileNotFoundError(f"Audio not found: {track.audio_path}")

    # Probe actual audio duration at render time
    probed_ms = _probe_duration_ms(track.audio_path)
    duration_ms = probed_ms or track.duration_ms or 180_000  # fallback 3 min
    logger.info(
        "Track %s: stored_ms=%s, probed_ms=%s, using=%s",
        track.order_index, track.duration_ms, probed_ms, duration_ms,
    )
    total_s = duration_ms / 1000.0

    # Progress range for this track within the overall job
    # Encoding phase uses 0-95%, final track concatenation uses 95-100%
    encode_range = 0.95
    progress_base = (track_index / total_tracks) * encode_range
    progress_span = (1.0 / total_tracks) * encode_range

    # Phase A splits: segments get 0-5%, assembly gets 5-100%
    seg_progress_span = progress_span * 0.05
    asm_progress_base = progress_base + seg_progress_span
    asm_progress_span = progress_span * 0.95

    project_dir = os.path.dirname(os.path.dirname(output_path))
    tmp_dir = os.path.join(project_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Phase A: Preprocess images to target resolution
    # ------------------------------------------------------------------
    preprocessed = []
    for idx, img in enumerate(images):
        _check_cancelled(job_id)
        pp_path = os.path.join(tmp_dir, f"pp_{track.order_index}_{idx}.png")
        _preprocess_image(img.path, pp_path, project.fit_mode, width, height)
        preprocessed.append(pp_path)

    # ------------------------------------------------------------------
    # Phase B: Encode short video segments (one per unique image)
    # ------------------------------------------------------------------
    segment_paths = []
    for idx, pp_path in enumerate(preprocessed):
        _check_cancelled(job_id)
        seg_path = os.path.join(tmp_dir, f"seg_{track.order_index}_{idx}.mp4")
        _encode_segment(pp_path, seg_path, fps, project.preset)
        segment_paths.append(seg_path)

        # Report segment encoding progress (0-5% of track range)
        seg_pct = (idx + 1) / len(preprocessed)
        _update_job(
            job_id,
            progress=round(progress_base + seg_pct * seg_progress_span, 4),
        )

    # ------------------------------------------------------------------
    # Phase C: Assemble final video (concat segments + encode audio)
    # ------------------------------------------------------------------
    _check_cancelled(job_id)

    # Calculate duration per image
    per_image_s = total_s / n_images
    image_durations = [per_image_s] * n_images

    # Build concat list that tiles segments to fill audio duration
    concat_list_path = os.path.join(tmp_dir, f"seg_concat_{track.order_index}.txt")
    _build_segment_concat_list(segment_paths, image_durations, concat_list_path)

    # Assembly command: copy video, encode audio, add progress tracking
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-i", track.audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-t", f"{total_s:.3f}",
        "-movflags", "faststart",
        "-progress", "pipe:1",
        output_path,
    ]

    # Create a dedicated DB session for progress updates
    progress_db = _Session()

    start_time = time.time()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Read stderr in background thread to prevent pipe deadlock
    stderr_lines = []
    stderr_thread = threading.Thread(
        target=_read_stderr, args=(process.stderr, stderr_lines), daemon=True
    )
    stderr_thread.start()

    with open(log_path, "a") as log_file:
        log_file.write(f"Command: {' '.join(cmd)}\n")
        log_file.write(
            f"Images: {n_images}, Segments: {len(segment_paths)}, "
            f"Total: {total_s:.3f}s\n\n"
        )

        duration_us = duration_ms * 1000  # microseconds
        last_progress_update = -1.0
        last_cancel_check = time.time()

        for line in process.stdout:
            log_file.write(line)

            now = time.time()

            # Timeout check
            if now - start_time > RENDER_TIMEOUT_S:
                process.kill()
                logger.error("Track %s render timed out after %ds", track.order_index, RENDER_TIMEOUT_S)
                break

            # Cancellation check (every ~2 seconds)
            if now - last_cancel_check >= 2.0:
                last_cancel_check = now
                try:
                    _check_cancelled(job_id, process=process)
                except RenderCancelled:
                    raise

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
                        overall_progress = asm_progress_base + track_progress * asm_progress_span
                        overall_progress = min(overall_progress, asm_progress_base + asm_progress_span)
                        if overall_progress - last_progress_update >= 0.005:
                            elapsed = now - start_time
                            if track_progress > 0.01:
                                track_remaining = elapsed * (1.0 - track_progress) / track_progress
                                estimated_track_total = elapsed / track_progress
                                remaining_tracks_time = estimated_track_total * (total_tracks - track_index - 1)
                                eta = track_remaining + remaining_tracks_time
                            else:
                                eta = None
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

        stderr_thread.join(timeout=5)
        stderr_output = "".join(stderr_lines)
        log_file.write(f"\nSTDERR:\n{stderr_output}\n")
        log_file.write(f"\nReturn code: {process.returncode}\n")

    progress_db.close()

    # Mark this track's slice as complete
    track_end_progress = progress_base + progress_span
    if process.returncode == 0 and last_progress_update < track_end_progress:
        _update_job(
            job_id,
            progress=round(track_end_progress, 4),
            eta_s=0 if track_index == total_tracks - 1 else None,
        )

    # Check for errors BEFORE cleanup (temp files aid debugging)
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (code {process.returncode}): {stderr_output[-500:]}")

    # Cleanup on success: preprocessed PNGs, segments, concat list
    for pp_path in preprocessed:
        try:
            os.remove(pp_path)
        except OSError:
            pass
    for seg_path in segment_paths:
        try:
            os.remove(seg_path)
        except OSError:
            pass
    try:
        os.remove(concat_list_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Final track concatenation
# ---------------------------------------------------------------------------

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

    with open(log_path, "a") as log_file:
        log_file.write(f"\n--- Final concatenation ---\nCommand: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    with open(log_path, "a") as log_file:
        log_file.write(f"Return code: {result.returncode}\n")
        if result.stderr:
            log_file.write(f"STDERR:\n{result.stderr[-500:]}\n")

    if result.returncode != 0:
        raise RuntimeError(f"Final concatenation failed (code {result.returncode}): {result.stderr[-500:]}")

    # Cleanup on success
    try:
        os.remove(concat_list_path)
    except OSError:
        pass
    for fpath in track_files:
        try:
            os.remove(fpath)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def execute_render(job_id: str):
    """Main entry point called by the RQ worker."""
    # Check if cancelled before starting
    _check_cancelled(job_id)

    tmp_dir = None
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

        # Initialize log file
        with open(log_path, "w") as f:
            f.write(f"Project: {project.name} ({total_tracks} tracks)\n\n")

        # Render each track to a temporary video file
        track_files = []
        for i, track in enumerate(tracks):
            track_images = sorted(track.images, key=lambda x: x.order_index)

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

    except RenderCancelled:
        logger.info("Job %s cancelled by user", job_id)
        try:
            _update_job(
                job_id,
                status="error",
                error_msg="Cancelado pelo usuario",
                finished_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass  # DB record may already be deleted
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
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
