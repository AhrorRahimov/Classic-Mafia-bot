"""Lobby commands and inline buttons: /newgame, /join, /leave, /startgame."""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo import GameRepo, PlayerRepo
from app.game.constants import MAX_PLAYERS, MIN_PLAYERS
from app.game.enums import Role
from app.game.exceptions import CREATOR_LEFT, GameError
from app.i18n import Translator
from app.keyboards.callbacks import CallbackAction
from app.keyboards.inline import lobby_kb
from app.services.lobby import LobbyService
from app.services.orchestrator import start_night
from app.services.session import GameSession
from app.services.timer import TimerManager
from app.texts import lobby_opened, mafia_teammates, your_role

logger = logging.getLogger(__name__)
router = Router(name="lobby")


# --- Helpers -----------------------------------------------------------

def _display_name(message: Message | CallbackQuery) -> str:
    user = message.from_user
    return user.full_name or f"User {user.id}"


async def _get_lobby_row(session: AsyncSession, chat_id: int):
    return await GameRepo(session).get_active(chat_id)


async def _refresh_lobby_card(
    bot: Bot,
    chat_id: int,
    game_id: int,
    creator_name: str,
    players_names: list[str],
    t: Translator,
) -> None:
    """Post a fresh lobby card. Used by /newgame."""
    await bot.send_message(
        chat_id,
        lobby_opened(t, creator_name, players_names),
        reply_markup=lobby_kb(game_id, t),
    )


# --- /newgame ----------------------------------------------------------

@router.message(Command("newgame"))
async def cmd_newgame(
    message: Message,
    games: LobbyService,
    session: AsyncSession,
    t: Translator,
) -> None:
    if message.chat.type == "private":
        await message.answer(t("errors.not_in_group"))
        return

    chat_id = message.chat.id
    creator_name = _display_name(message)
    try:
        game = await games.create_lobby(
            db=session, chat_id=chat_id,
            creator_id=message.from_user.id, creator_name=creator_name,
        )
    except GameError as exc:
        await message.answer(f"⚠️ {t(exc.key, **exc.kwargs)}")
        return

    players = await PlayerRepo(session).list_by_game(game.id)
    names = [p.full_name for p in players]
    await message.answer(
        lobby_opened(t, creator_name, names),
        reply_markup=lobby_kb(game.id, t),
    )


# --- /join -------------------------------------------------------------

@router.message(Command("join"))
async def cmd_join(
    message: Message,
    games: LobbyService,
    session: AsyncSession,
    t: Translator,
) -> None:
    if message.chat.type == "private":
        await message.answer(t("errors.not_in_group"))
        return

    await _do_join(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        full_name=_display_name(message),
        games=games,
        session=session,
        t=t,
        reply=message.answer,
    )


@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.JOIN}:"))
async def cb_join(
    query: CallbackQuery,
    games: LobbyService,
    session: AsyncSession,
    t: Translator,
) -> None:
    await _do_join(
        chat_id=query.message.chat.id,
        user_id=query.from_user.id,
        full_name=_display_name(query),
        games=games,
        session=session,
        t=t,
        reply=lambda text, **kw: query.message.answer(text, **kw),
    )
    await query.answer()


async def _do_join(
    *,
    chat_id: int,
    user_id: int,
    full_name: str,
    games: LobbyService,
    session: AsyncSession,
    t: Translator,
    reply,
) -> None:
    try:
        game = await games.join(
            db=session, chat_id=chat_id, user_id=user_id, full_name=full_name
        )
    except GameError as exc:
        await reply(f"⚠️ {t(exc.key, **exc.kwargs)}")
        return

    players = await PlayerRepo(session).list_by_game(game.id)
    await reply(
        t("lobby.joined", name=full_name, count=len(players), min=MIN_PLAYERS, max=MAX_PLAYERS),
    )


# --- /leave ------------------------------------------------------------

@router.message(Command("leave"))
async def cmd_leave(
    message: Message,
    games: LobbyService,
    session: AsyncSession,
    t: Translator,
) -> None:
    if message.chat.type == "private":
        await message.answer(t("errors.not_in_group"))
        return
    try:
        await games.leave(session, message.chat.id, message.from_user.id)
    except GameError as exc:
        if exc.key == CREATOR_LEFT:
            await message.answer(t("lobby.creator_left_dissolved"))
            return
        await message.answer(f"⚠️ {t(exc.key, **exc.kwargs)}")
        return
    await message.answer(t("lobby.left", name=_display_name(message)))


@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.LEAVE}:"))
async def cb_leave(
    query: CallbackQuery,
    games: LobbyService,
    session: AsyncSession,
    t: Translator,
) -> None:
    try:
        await games.leave(session, query.message.chat.id, query.from_user.id)
    except GameError as exc:
        if exc.key == CREATOR_LEFT:
            await query.message.answer(t("lobby.dissolved_creator_left"))
            try:
                await query.message.edit_text(t("lobby.closed"))
            except TelegramBadRequest:
                pass
            await query.answer()
            return
        await query.answer(f"⚠️ {t(exc.key, **exc.kwargs)}", show_alert=True)
        return
    await query.answer(t("lobby.left", name=_display_name(query)))


# --- /startgame --------------------------------------------------------

@router.message(Command("startgame"))
async def cmd_startgame(
    message: Message,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    if message.chat.type == "private":
        await message.answer(t("errors.not_in_group"))
        return
    await _do_start(
        chat_id=message.chat.id,
        actor_id=message.from_user.id,
        games=games,
        timers=timers,
        session=session,
        t=t,
        bot=bot,
        reply=message.answer,
    )


@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.START}:"))
async def cb_start(
    query: CallbackQuery,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    await _do_start(
        chat_id=query.message.chat.id,
        actor_id=query.from_user.id,
        games=games,
        timers=timers,
        session=session,
        t=t,
        bot=bot,
        reply=lambda text, **kw: query.message.answer(text, **kw),
    )
    await query.answer()


async def _do_start(
    *,
    chat_id: int,
    actor_id: int,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
    reply,
) -> None:
    # Only the lobby creator can start the game.
    active = await _get_lobby_row(session, chat_id)
    if active is None or active.status != "lobby":
        await reply(t("lobby.no_lobby_here"))
        return
    if active.creator_id != actor_id:
        await reply(t("lobby.not_creator_start"))
        return

    try:
        game_session = await games.start(db=session, chat_id=chat_id)
    except GameError as exc:
        await reply(f"⚠️ {t(exc.key, **exc.kwargs)}")
        return

    # Notify the group…
    await reply(
        t("lobby.game_started", count=len(game_session.players)),
    )
    # …and DM each player their role (in their own language).
    await _send_roles(bot, session, game_session)

    # Kick off the first night.
    await start_night(bot, games, timers, session, game_session)


# --- Role DMs ----------------------------------------------------------

async def _send_roles(
    bot: Bot, session: AsyncSession, game_session: GameSession
) -> None:
    """DM each player their role in their own language. Best-effort."""
    from app.db.repo import StatsRepo
    from app.i18n import get_i18n

    i18n = get_i18n()
    stats_repo = StatsRepo(session)

    for user_id, player in game_session.players.items():
        lang = await stats_repo.get_language(user_id)
        t = i18n.translator_for(lang)
        extra = ""
        if player.role is Role.MAFIA:
            teammates = [
                p for uid, p in game_session.players.items()
                if uid != user_id and p.role is Role.MAFIA
            ]
            extra = mafia_teammates(t, teammates)
        try:
            await bot.send_message(user_id, your_role(t, player.role, extra))
        except TelegramBadRequest:
            logger.warning(
                "Could not DM user %s their role (bot blocked?).", user_id
            )
