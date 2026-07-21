"""Basic commands: /start /help /cancel /stats."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo import GameRepo, StatsRepo
from app.game.enums import Winner
from app.services.lobby import LobbyService
from app.services.timer import TimerManager
from app.texts import (
    HELP_TEXT,
    NO_ACTIVE_GAME,
    NOT_IN_GROUP,
    START_TEXT,
    stats_text,
)

logger = logging.getLogger(__name__)
router = Router(name="basic")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    session: AsyncSession,
) -> None:
    stats = await StatsRepo(session).get(message.from_user.id)
    await message.answer(stats_text(stats))


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
) -> None:
    """Cancel the current lobby or running game (creator only)."""
    if message.chat.type == "private":
        await message.answer(NOT_IN_GROUP)
        return

    chat_id = message.chat.id
    active = games.get(chat_id)

    # 1) Active running game — stop timers and tear down the session.
    if active is not None:
        if active.creator_id != message.from_user.id:
            await message.answer("Отменить игру может только её создатель.")
            return
        timers.cancel(active.game_id)
        games.remove(chat_id)
        game_row = await GameRepo(session).get(active.game_id)
        if game_row is not None:
            await GameRepo(session).finish(
                game_row,
                winner=Winner.NONE.value,
                rounds_played=active.round_number,
            )
        await message.answer("🛑 Игра отменена создателем.")
        return

    # 2) Otherwise try to cancel an open lobby.
    try:
        await games.cancel(session, chat_id, message.from_user.id)
    except Exception:  # noqa: BLE001 — LobbyError variants all mean "nothing to cancel"
        await message.answer(NO_ACTIVE_GAME)
        return
    await message.answer("🛑 Лобби отменено.")
