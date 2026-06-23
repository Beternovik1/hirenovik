"""Gunicorn production configuration for the Hirenovik API.

Loads the FastAPI ASGI application through Uvicorn workers managed by
Gunicorn. The worker count scales with CPU count; ``preload_app`` shares
the NLP/ML model memory across workers, reducing per-worker load times.

Attributes:
    bind: Host and port Gunicorn listens on.
    workers: Number of worker processes (CPU * 2 + 1, fallback 4).
    worker_class: ASGI worker class for Uvicorn.
    timeout: Maximum seconds a worker can take to handle a request.
    keepalive: Seconds to wait for keep-alive connections.
    accesslog: Destination for access logs (``-`` is stdout).
    errorlog: Destination for error logs (``-`` is stderr).
    loglevel: Gunicorn log verbosity.
    graceful_timeout: Seconds to wait for workers to finish on SIGTERM.
    max_requests: Requests before a worker is recycled (limits leaks).
    max_requests_jitter: Random jitter on max_requests to avoid thundering herd.
    preload_app: Load the application before forking workers (shared model memory).
"""

import multiprocessing
import os


def _calculate_workers() -> int:
    """Return the worker count based on CPU availability.

    Uses the formula ``CPU * 2 + 1``. Falls back to 4 when the CPU count
    cannot be determined or the container restricts visibility.

    Returns:
        Number of Gunicorn workers.
    """
    try:
        cpu_count: int = multiprocessing.cpu_count()
        return cpu_count * 2 + 1
    except (NotImplementedError, OSError):
        return 4


bind: str = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers: int = _calculate_workers()
worker_class: str = "uvicorn.workers.UvicornWorker"
timeout: int = 120
keepalive: int = 5
accesslog: str = "-"
errorlog: str = "-"
loglevel: str = "info"
graceful_timeout: int = 30
max_requests: int = 1000
max_requests_jitter: int = 100
preload_app: bool = True