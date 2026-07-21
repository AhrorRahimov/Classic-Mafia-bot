"""Aggregates all handler routers into one, in priority order."""
from __future__ import annotations

from aiogram import Router

from app.handlers import basic, day, lobby, night


def build_root_router() -> Router:
    """Return the root router with all sub-routers included.

    Order matters: more specific routers (lobby, night, day) come
    before the generic ``basic`` router so that callback actions are
    not shadowed by catch-all handlers.
    """
    root = Router(name="root")
    root.include_router(basic.router)
    root.include_router(lobby.router)
    root.include_router(night.router)
    root.include_router(day.router)
    return root
