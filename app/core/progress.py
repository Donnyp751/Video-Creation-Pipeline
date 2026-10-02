"""Progress reporting from deep inside providers/services to whatever job is running them."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

Reporter = Callable[[str, str | None], None]

_reporter: ContextVar[Reporter | None] = ContextVar("kidsvideo_reporter", default=None)


def set_reporter(reporter: Reporter | None):
    return _reporter.set(reporter)


def reset_reporter(token) -> None:
    _reporter.reset(token)


def report(status: str, message: str | None = None) -> None:
    """Report a job phase such as GENERATING / DOWNLOADING / REVIEWING. No-op outside jobs."""
    reporter = _reporter.get()
    if reporter is not None:
        reporter(status, message)
