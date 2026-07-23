"""Night-action callbacks (private chat).

Each active role gets a private message with targets during the night.
Selecting a target triggers the corresponding callback here. The
callback resolves the right ``GameSession`` regardless of which chat
the update came from — we look it up by the acting user.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo import StatsRepo
from app.game.exceptions import GameError
from app.i18n import Translator, get_i18n
from app.keyboards.callbacks import CallbackAction, parse_callback
from app.services.lobby import LobbyService
from app.services.night import NightService
from app.services.orchestrator import end_night
from app.services.session import GameSession
from app.services.timer import TimerManager

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


async def _resolve_t(
    session: AsyncSession, user_id: int, fallback_t: Translator
) -> Translator:
    """Build a translator in the user's own language (for PMs).

    Falls back to the handler's injected translator if the lookup fails.
    """
    try:
        lang = await StatsRepo(session).get_language(user_id)
        return get_i18n().translator_for(lang)
    except Exception:  # noqa: BLE001
        return fallback_t


# --- Mafia kill --------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.MAFIA_KILL}:"))
async def cb_mafia_kill(
    query: CallbackQuery,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot: Bot,
    t: Translator,
) -> None:
    game = _find_session_for_user(games, query.from_user.id)
    if game is None or game.phase.value != "night":
        await query.answer(t("errors.wrong_time_action"), show_alert=True)
        return

    _, target_id = parse_callback(query.data)
    service = NightService(game)
    try:
        async with game.lock:
            service.mafia_kill(query.from_user.id, target_id)
    except GameError as exc:
        await query.answer(f"⚠️ {t(exc.key, **exc.kwargs)}", show_alert=True)
        return

    await query.answer()
    try:
        await query.message.edit_text(
            t("night.mafia_done_pm", footer=t("night.action_done"))
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
    t: Translator,
) -> None:
    game = _find_session_for_user(games, query.from_user.id)
    if game is None or game.phase.value != "night":
        await query.answer(t("errors.wrong_time_action"), show_alert=True)
        return

    _, target_id = parse_callback(query.data)
    service = NightService(game)
    try:
        async with game.lock:
            service.detective_check(query.from_user.id, target_id)
    except GameError as exc:
        await query.answer(f"⚠️ {t(exc.key, **exc.kwargs)}", show_alert=True)
        return

    await query.answer(t("night.detective_toast_pending"), show_alert=False)
    try:
        await query.message.edit_text(
            t("night.detective_done_pm", footer=t("night.action_done"))
        )
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
    t: Translator,
) -> None:
    game = _find_session_for_user(games, query.from_user.id)
    if game is None or game.phase.value != "night":
        await query.answer(t("errors.wrong_time_action"), show_alert=True)
        return

    _, target_id = parse_callback(query.data)
    service = NightService(game)
    try:
        async with game.lock:
            service.doctor_heal(query.from_user.id, target_id)
    except GameError as exc:
        await query.answer(f"⚠️ {t(exc.key, **exc.kwargs)}", show_alert=True)
        return

    await query.answer()
    try:
        await query.message.edit_text(
            t("night.doctor_done_pm", footer=t("night.action_done"))
        )
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
