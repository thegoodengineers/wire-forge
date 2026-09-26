"""Cooperative cancellation for the one live run.

The server runs one forge at a time (its lock guarantees it), so a single event suffices.
Agents check it between turns; a cancelled run stops cleanly and is recorded as cancelled,
never silently dropped.
"""

from __future__ import annotations

import threading

_EVENT = threading.Event()


def request() -> None:
    _EVENT.set()


def clear() -> None:
    _EVENT.clear()


def requested() -> bool:
    return _EVENT.is_set()
