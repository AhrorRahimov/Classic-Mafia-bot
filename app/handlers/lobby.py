"""Lobby commands and inline buttons: /newgame, /join, /leave, /startgame."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo import PlayerRepo
from app.game.constants import MAX_PLAYERS, MIN_PLAYERS
from app.game.exceptions import LobbyError
from app.keyboards.callbacks import CallbackAction
from app.keyboards.inline import lobby_kb
from app.services.lobby import LobbyService
from app.services.timer import TimerManager
from app.texts import NOT_IN_GROUP, lobby_opened

logger = logging.getLogger(__name__)
router = Router(name="lobby")


def _display_name(message: Message | CallbackQuery) -> str:
    user = message.from_user
    return user.full_name or f"User {user.id}"


@router.message(Command("newgame"))
async def cmd_newgame(
    message: Message,
    games: LobbyService,
    session: AsyncSession,
) -> None:
    if message.chat.type == "private":
        await message.answer(NOT_IN_GROUP)
        return

    chat_id = message.chat.id
    creator_name = _display_name(message)
    try:
        game = await games.create_lobby(
            db=session, chat_id=chat_id,
            creator_id=message.from_user.id, creator_name=creator_name,
        )
    except LobbyError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    players = await PlayerRepo(session).list_by_game(game.id)
    names = [p.full_name for p in players]
    await message.answer(
        lobby_opened(creator_name, names),
        reply_markup=lobby_kb(game.id),
    )


@router.message(Command("join"))
async def cmd_join(
    message: Message,
    games: LobbyService,
    session: AsyncSession,
) -> None:
    if message.chat.type == "private":
        await message.answer(NOT_IN_GROUP)
        return

    await _do_join(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        full_name=_display_name(message),
        games=games,
        session=session,
        reply=message.answer,
    )


@router.message(Command("leave"))
async def cmd_leave(
    message: Message,
    games: LobbyService,
    session: AsyncSession,
) -> None:
    if message.chat.type == "private":
        await message.answer(NOT_IN_GROUP)
        return

    try:
        await games.leave(session, message.chat.id, message.from_user.id)
    except LobbyError as exc:
        # Sentinel raised when the creator leaves — the lobby is gone.
        if str(exc) == "_creator_left_":
            await message.answer("🛑 Создатель покинул лобби — игра распущена.")
            return
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(f"👋 {_display_name(message)} покинул лобби.")


@router.message(Command("startgame"))
async def cmd_startgame(
    message: Message,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot,
) -> None:
    if message.chat.type == "private":
        await message.answer(NOT_IN_GROUP)
        return

    await _do_start(
        chat_id=message.chat.id,
        actor_id=message.from_user.id,
        games=games,
        timers=timers,
        session=session,
        bot=bot,
        reply=message.answer,
    )


# --- Inline callbacks --------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.JOIN}:"))
async def cb_join(
    query: CallbackQuery,
    games: LobbyService,
    session: AsyncSession,
) -> None:
    chat_id = query.message.chat.id
    await _do_join(
        chat_id=chat_id,
        user_id=query.from_user.id,
        full_name=_display_name(query),
        games=games,
        session=session,
        reply=lambda text, **kw: query.message.answer(text, **kw),
    )
    await query.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.LEAVE}:"))
async def cb_leave(
    query: CallbackQuery,
    games: LobbyService,
    session: AsyncSession,
) -> None:
    try:
        await games.leave(session, query.message.chat.id, query.from_user.id)
    except LobbyError as exc:
        if str(exc) == "_creator_left_":
            await query.message.answer("🛑 Лобби распущено (создатель вышел).")
            await _safe_edit(query, "Лобби закрыто.")
            await query.answer()
            return
        await query.answer(f"⚠️ {exc}", show_alert=True)
        return
    await query.answer("Ты покинул лобби.")


@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.START}:"))
async def cb_start(
    query: CallbackQuery,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot,
) -> None:
    await _do_start(
        chat_id=query.message.chat.id,
        actor_id=query.from_user.id,
        games=games,
        timers=timers,
        session=session,
        bot=bot,
        reply=lambda text, **kw: query.message.answer(text, **kw),
    )
    await query.answer()


# --- Shared helpers ----------------------------------------------------

async def _do_join(
    *,
    chat_id: int,
    user_id: int,
    full_name: str,
    games: LobbyService,
    session: AsyncSession,
    reply,
) -> None:
    try:
        game = await games.join(
            db=session, chat_id=chat_id, user_id=user_id, full_name=full_name
        )
    except LobbyError as exc:
        await reply(f"⚠️ {exc}")
        return

    players = await PlayerRepo(session).list_by_game(game.id)
    names = [p.full_name for p in players]
    await reply(
        f"✅ <b>{full_name}</b> в игре! Теперь игроков: {len(names)}.\n"
        f"({MIN_PLAYERS}–{MAX_PLAYERS})",
    )


async def _do_start(
    *,
    chat_id: int,
    actor_id: int,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    bot,
    reply,
) -> None:
    # Only the lobby creator can start the game.
    # ``LobbyService.start`` does not enforce creator, so check here.
    active = await _get_lobby_row(session, chat_id)
    if active is None:
        await reply("⚠️ В этом чате нет открытого лобби.")
        return
    if active.creator_id != actor_id:
        await reply("⚠️ Начать игру может только создатель лобби.")
        return

    try:
        game_session = await games.start(db=session, chat_id=chat_id)
    except LobbyError as exc:
        await reply(f"⚠️ {exc}")
        return

    # Notify the group and DM each player their role.
    await reply(
        f"🎮 <b>Игра началась!</b> Игроков: {len(game_session.players)}.\n"
        "Я отправил каждому его роль в личные сообщения."
    )
    await _send_roles(bot, game_session)

    # Kick off the first night via the orchestrator (imported lazily to
    # avoid a circular import: orchestrator -> handlers).
    from app.services.orchestrator import start_night
    await start_night(bot, games, timers, session, game_session)


async def _get_lobby_row(session: AsyncSession, chat_id: int):
    from app.db.repo import GameRepo
    return await GameRepo(session).get_active(chat_id)


async def _send_roles(bot, game_session) -> None:
    """DM each player their role. Best-effort: skips users who blocked the bot."""
    from app.game.enums import Role
    from app.texts import mafia_teammates, your_role

    for user_id, player in game_session.players.items():
        extra = ""
        if player.role is Role.MAFIA:
            teammates = [
                p for uid, p in game_session.players.items()
                if uid != user_id and p.role is Role.MAFIA
            ]
            extra = mafia_teammates(teammates)
        try:
            await bot.send_message(user_id, your_role(player.role, extra))
        except TelegramBadRequest:
            logger.warning(
                "Could not DM user %s their role (bot blocked?).",
                user_id,
            )


async def _safe_edit(query: CallbackQuery, text: str) -> None:
    try:
        await query.message.edit_text(text)
    except TelegramBadRequest:
        pass
