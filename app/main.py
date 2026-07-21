"""Bot bootstrap: dispatcher, middleware, polling loop."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.db.session import dispose_db, init_db
from app.handlers.router import build_root_router
from app.middlewares.db import DbSessionMiddleware
from app.middlewares.services import ServicesMiddleware
from app.services.lobby import LobbyService
from app.services.timer import TimerManager

logger = logging.getLogger(__name__)


async def main() -> None:
    """Wire everything up and start long-polling."""
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

    # Middleware order: services first (so `data["games"]` is available
    # downstream), then the DB session.
    dp.update.outer_middleware(ServicesMiddleware(games, timers))
    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(build_root_router())

    await init_db()
    logger.info("Starting bot polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        timers.cancel_all()
        await dispose_db()
        await bot.session.close()
