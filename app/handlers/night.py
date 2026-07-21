"""Night-action callbacks (private chat).

Each active role gets a private message with targets during the night.
Selecting a target triggers the corresponding callback here. The
callback resolves the right ``GameSession`` regardless of which chat
the update came from — we look it up by the acting user.

Note: we cannot use ``chat_id`` filters because these callbacks arrive
in the bot's private chat, not the group. Instead we search the
``LobbyService`` registry for any session containing the user as an
alive role-bearer.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.game.exceptions import GameError
from app.keyboards.callbacks import CallbackAction, parse_callback
from app.services.lobby import LobbyService
from app.services.night import NightService
from app.services.orchestrator import end_night
from app.services.session import GameSession
from app.services.timer import TimerManager
from app.texts import NIGHT_DONE_PM

logger = logging.getLogger(__name__)
router = Router(name="night")


def _find_session_for_user(
    games: LobbyService, user_id: int
) -> GameSession | None:
    """Locate the live game in which ``user_id`` is a player."""
    for session in games._sessions.values():  # noqa: SLF001 — registry access
        if user_id in session.players:
            return session
    return None


# --- Mafia kill --------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.MAFIA_KILL}:"))
async def cb_mafia_kill(
    query: CallbackQuery,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot: Bot,
) -> None:
    game = _find_session_for_user(games, query.from_user.id)
    if game is None or game.phase.value != "night":
        await query.answer("Сейчас не время для этого действия.", show_alert=True)
        return

    _, target_id = parse_callback(query.data)
    service = NightService(game)
    try:
        async with game.lock:
            service.mafia_kill(query.from_user.id, target_id)
    except GameError as exc:
        await query.answer(f"⚠️ {exc}", show_alert=True)
        return

    await query.answer()
    try:
        await query.message.edit_text(
            f"🔴 Вы выбрали жертву.\n{NIGHT_DONE_PM}"
        )
    except TelegramBadRequest:
        pass

    await _maybe_close_night(bot, games, timers, session, game)


# --- Detective check ---------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.DETECTIVE_CHECK}:"))
async def cb_detective_check(
    query: CallbackQuery,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot: Bot,
) -> None:
    game = _find_session_for_user(games, query.from_user.id)
    if game is None or game.phase.value != "night":
        await query.answer("Сейчас не время для этого действия.", show_alert=True)
        return

    _, target_id = parse_callback(query.data)
    service = NightService(game)
    try:
        async with game.lock:
            # Result is revealed when the night resolves (see orchestrator).
            service.detective_check(query.from_user.id, target_id)
    except GameError as exc:
        await query.answer(f"⚠️ {exc}", show_alert=True)
        return

    # The full verdict is revealed when the night resolves — here we just
    # acknowledge the action so the player knows their pick was accepted.
    await query.answer("Проверка проведена. Результат — после рассвета.", show_alert=False)
    try:
        await query.message.edit_text(f"🔵 Проверка отправлена.\n{NIGHT_DONE_PM}")
    except TelegramBadRequest:
        pass

    await _maybe_close_night(bot, games, timers, session, game)


# --- Doctor heal -------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.DOCTOR_HEAL}:"))
async def cb_doctor_heal(
    query: CallbackQuery,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot: Bot,
) -> None:
    game = _find_session_for_user(games, query.from_user.id)
    if game is None or game.phase.value != "night":
        await query.answer("Сейчас не время для этого действия.", show_alert=True)
        return

    _, target_id = parse_callback(query.data)
    service = NightService(game)
    try:
        async with game.lock:
            service.doctor_heal(query.from_user.id, target_id)
    except GameError as exc:
        await query.answer(f"⚠️ {exc}", show_alert=True)
        return

    await query.answer()
    try:
        await query.message.edit_text(f"🟡 Пациент выбран.\n{NIGHT_DONE_PM}")
    except TelegramBadRequest:
        pass

    await _maybe_close_night(bot, games, timers, session, game)


# --- Helpers -----------------------------------------------------------

async def _maybe_close_night(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
) -> None:
    """If every required role has acted, resolve the night immediately."""
    if NightService(game).all_required_acted():
        timers.cancel(game.game_id)
        await end_night(bot, games, timers, session, game)
