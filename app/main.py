"""Bot bootstrap: dispatcher, middleware, polling loop.

Middleware ordering matters:

1. ``ServicesMiddleware`` (outer) — injects shared singletons
   (``games``, ``timers``).
2. ``DbSessionMiddleware`` — opens a fresh DB session per update and
   exposes it as ``data["session"]``.
3. ``I18nMiddleware`` — reads the user's language from the DB and
   exposes ``data["i18n"]``, ``data["user_lang"]``, ``data["t"]``.

On Render (and other PaaS that require binding to a port), a small
HTTP health server runs alongside the polling loop so the platform's
health check passes and the free-tier service is not put to sleep by
external cron pings.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.db.session import dispose_db, init_db
from app.handlers.router import build_root_router
from app.i18n import get_i18n
from app.i18n.middleware import I18nMiddleware
from app.middlewares.db import DbSessionMiddleware
from app.middlewares.services import ServicesMiddleware
from app.services.lobby import LobbyService
from app.services.timer import TimerManager
from app.web import start_health_server

logger = logging.getLogger(__name__)


async def main() -> None:
    """Wire everything up and start long-polling + health server."""
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # Drop pending updates so the bot doesn't replay old messages on restart.
    await bot.delete_webhook(drop_pending_updates=True)

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Shared process-wide services.
    games = LobbyService()
    timers = TimerManager()

    # Outer: shared services (no DB needed).
    dp.update.outer_middleware(ServicesMiddleware(games, timers))
    # Inner: DB session, then i18n (needs DB to look up user language).
    dp.update.middleware(DbSessionMiddleware())
    dp.update.middleware(I18nMiddleware(get_i18n()))

    dp.include_router(build_root_router())

    await init_db()

    # Start the HTTP health-check server (required by Render Web Service).
    web_runner = await start_health_server(port=settings.web_port)

    logger.info("Starting bot polling…")
    try:
        await dp.start_polling(
            bot, allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        timers.cancel_all()
        await web_runner.cleanup()
        await dispose_db()
        await bot.session.close()
