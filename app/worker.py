"""
Worker module — enqueues render jobs to Redis Queue.
The actual render logic is in app.render.
"""
import redis
import rq

from app.config import get_settings

settings = get_settings()

_redis_conn = None
_queue = None

CANCEL_KEY_PREFIX = "cancel:"
CANCEL_TTL_S = 600  # 10 minutes


def _get_redis() -> redis.Redis:
    """Get or create the module-level Redis connection."""
    global _redis_conn
    if _redis_conn is None:
        _redis_conn = redis.Redis.from_url(settings.REDIS_URL)
    return _redis_conn


def _get_queue() -> rq.Queue:
    global _queue
    if _queue is None:
        _queue = rq.Queue("video_jobs", connection=_get_redis())
    return _queue


def enqueue_render(job_id: str):
    """Put a render job on the Redis queue."""
    q = _get_queue()
    q.enqueue("app.render.execute_render", job_id, job_timeout="2h")


def request_cancel(job_id: str):
    """Signal that a job should be cancelled.

    Sets a Redis key that the render loop checks periodically.
    Also attempts to cancel the RQ job if it's still queued.
    """
    r = _get_redis()
    r.setex(f"{CANCEL_KEY_PREFIX}{job_id}", CANCEL_TTL_S, "1")

    # Attempt to cancel any matching queued RQ job (best-effort)
    try:
        q = _get_queue()
        for rq_job in q.jobs:
            if rq_job.args and rq_job.args[0] == job_id:
                rq_job.cancel()
                break
    except Exception:
        pass


def is_cancelled(job_id: str) -> bool:
    """Check if a cancellation has been requested for this job."""
    try:
        r = _get_redis()
        return r.exists(f"{CANCEL_KEY_PREFIX}{job_id}") > 0
    except Exception:
        return False


def clear_cancel_flag(job_id: str):
    """Remove the cancellation flag after the job has been cleaned up."""
    try:
        r = _get_redis()
        r.delete(f"{CANCEL_KEY_PREFIX}{job_id}")
    except Exception:
        pass
