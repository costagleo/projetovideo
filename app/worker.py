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


def _get_queue() -> rq.Queue:
    global _redis_conn, _queue
    if _queue is None:
        _redis_conn = redis.Redis.from_url(settings.REDIS_URL)
        _queue = rq.Queue("video_jobs", connection=_redis_conn)
    return _queue


def enqueue_render(job_id: str):
    """Put a render job on the Redis queue."""
    q = _get_queue()
    q.enqueue("app.render.execute_render", job_id, job_timeout="2h")
