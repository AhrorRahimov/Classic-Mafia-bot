"""Basic commands: /start /help /cancel /stats /lang."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo import GameRepo, StatsRepo
from app.game.enums import Winner
from app.game.exceptions import GameError
from app.i18n import Translator
from app.keyboards.callbacks import CallbackAction
from app.keyboards.inline import language_kb
from app.services.lobby import LobbyService
from app.services.timer import TimerManager
from app.texts import stats_text

logger = logging.getLogger(__name__)
router = Router(name="basic")

# Language code -> human-readable name (used for the /lang confirmation).
_LANGUAGE_NAMES = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "uz": "🇺🇿 O'zbekcha",
}


@router.message(Command("start"))
async def cmd_start(message: Message, t: Translator) -> None:
    # Touch the DB so the user gets a stats row + default language early.
    await message.answer(t("start.greeting"))


@router.message(Command("help"))
async def cmd_help(message: Message, t: Translator) -> None:
    from app.game.constants import MAX_PLAYERS, MIN_PLAYERS
    await message.answer(t("help.text", min=MIN_PLAYERS, max=MAX_PLAYERS))


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    session: AsyncSession,
    t: Translator,
) -> None:
    stats = await StatsRepo(session).get(message.from_user.id)
    await message.answer(stats_text(t, stats))


@router.message(Command("lang"))
async def cmd_lang(message: Message, i18n) -> None:
    """Show language picker (works in private and group chats)."""
    await message.answer(i18n.translator_for("ru")("lang.prompt"), reply_markup=language_kb())


@router.callback_query(lambda c: c.data and c.data.startswith(f"{CallbackAction.SET_LANG}:"))
async def cb_set_lang(
    query: CallbackQuery,
    session: AsyncSession,
    i18n,
) -> None:
    """Persist the selected language and confirm on the new language."""
    _, lang_code = query.data.split(":", 1)
    if lang_code not in _LANGUAGE_NAMES:
        await query.answer("⚠️", show_alert=True)
        return
    await StatsRepo(session).set_language(query.from_user.id, lang_code)
    t = i18n.translator_for(lang_code)
    try:
        await query.message.edit_text(
            t("lang.changed", lang_name=_LANGUAGE_NAMES[lang_code]),
        )
    except TelegramBadRequest:
        pass
    await query.answer()


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    t: Translator,
) -> None:
    """Cancel the current lobby or running game (creator only)."""
    if message.chat.type == "private":
        await message.answer(t("errors.not_in_group"))
        return

    chat_id = message.chat.id
    active = games.get(chat_id)

    # 1) Active running game — stop timers and tear down the session.
    if active is not None:
        if active.creator_id != message.from_user.id:
            await message.answer(t("errors.only_creator_cancel_game"))
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
        await message.answer(t("errors.game_cancelled_by_creator"))
        return

    # 2) Otherwise try to cancel an open lobby.
    try:
        await games.cancel(session, chat_id, message.from_user.id)
    except GameError:  # LobbyError variants all mean "nothing to cancel"
        await message.answer(t("errors.no_active_game"))
        return
    await message.answer(t("lobby.cancelled_by_creator"))
