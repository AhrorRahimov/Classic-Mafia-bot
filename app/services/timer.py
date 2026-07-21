"""Async timer manager for phase transitions.

Each game owns a single ``asyncio.Task`` that fires a callback once
the configured delay elapses. The manager guarantees only one task
per game is pending at any time: scheduling a new one cancels the old.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


class TimerManager:
    """Track and cancel per-game timer tasks."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def schedule(
        self,
        game_id: int,
        delay: float,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Run ``callback`` after ``delay`` seconds.

        Any previously scheduled task for the same game is cancelled.
        """
        self.cancel(game_id)

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay)
                await callback()
            except asyncio.CancelledError:
                logger.debug("Timer for game %s cancelled.", game_id)
                raise
            except Exception:  # noqa: BLE001 — log and swallow to keep loop alive
                logger.exception("Timer callback failed for game %s.", game_id)
            finally:
                self._tasks.pop(game_id, None)

        self._tasks[game_id] = asyncio.create_task(
            _runner(), name=f"mafia-timer-{game_id}"
        )

    def cancel(self, game_id: int) -> None:
        """Cancel the pending timer for ``game_id`` if any."""
        task = self._tasks.pop(game_id, None)
        if task is not None and not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        """Cancel every pending timer (used on shutdown)."""
        for game_id in list(self._tasks.keys()):
            self.cancel(game_id)
