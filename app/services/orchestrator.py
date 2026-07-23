"""Game orchestrator: high-level transitions between phases.

This module glues services (lobby, night, day, timer) together and
talks to Telegram on behalf of handlers. Handlers stay thin: they
delegate phase transitions here so the flow logic lives in one place.

Phase loop::

    start_game  -> start_night
    night done  -> end_night  -> start_discussion
    discussion  -> start_vote
    vote done   -> end_vote   -> check_winner -> start_night OR end_game

Language resolution:
  * Group announcements use the **creator's** language.
  * Private messages (role prompts, vote, detective result) use the
    **recipient's** own language.

Phase loop::

    start_game  -> start_night
    night done  -> end_night  -> start_discussion
    discussion  -> start_vote
    vote done   -> end_vote   -> check_winner -> start_night OR end_game
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo import GameRepo, PlayerRepo, StatsRepo
from app.game.constants import (
    DAY_DISCUSSION_DURATION,
    DAY_VOTE_DURATION,
    NIGHT_DURATION,
)
from app.game.enums import GamePhase, Role, Winner
from app.i18n import Translator, get_i18n
from app.keyboards.inline import (
    detective_targets_kb,
    doctor_targets_kb,
    mafia_targets_kb,
    vote_kb,
)
from app.services.day import DayService
from app.services.lobby import LobbyService
from app.services.night import NightService
from app.services.session import GameSession
from app.services.timer import TimerManager
from app.texts import (
    detective_result,
    game_over,
    night_killed,
    role_reveal_header,
    role_reveal_line,
    vote_result_lynch,
    vote_result_no_lynch,
)

logger = logging.getLogger(__name__)


# --- Language helpers --------------------------------------------------

async def _user_t(session: AsyncSession, user_id: int) -> Translator:
    """Translator bound to the recipient's language (for private chat)."""
    lang = await StatsRepo(session).get_language(user_id)
    return get_i18n().translator_for(lang)


async def _group_t(session: AsyncSession, game: GameSession) -> Translator:
    """Translator bound to the game creator's language (for group chat)."""
    return await _user_t(session, game.creator_id)


# ---------------------------------------------------------------------------
# Night
# ---------------------------------------------------------------------------

async def start_night(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
) -> None:
    """Open the night phase: announce + DM action prompts + start timer."""
    game.begin_night()
    chat_id = game.chat_id
    t_group = await _group_t(session, game)

    await bot.send_message(chat_id, t_group("night.started"))

    # DM each role its targets in the recipient's language.
    await _prompt_mafia(bot, session, game)
    await _prompt_detective(bot, session, game)
    await _prompt_doctor(bot, session, game)

    timers.schedule(
        game.game_id,
        NIGHT_DURATION,
        _on_night_timeout(bot, games, timers, session, game),
    )


def _on_night_timeout(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
):
    async def _cb() -> None:
        await end_night(bot, games, timers, session, game)

    return _cb


async def end_night(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
) -> None:
    """Resolve the night, announce death, then move to discussion."""
    if games.get(game.chat_id) is not game:
        return

    timers.cancel(game.game_id)
    outcome = NightService(game).resolve()
    t_group = await _group_t(session, game)

    # Reveal detective result privately in the detective's language.
    if outcome.detective_suspect is not None and outcome.detective_is_mafia is not None:
        detective = next(
            (p for p in game.alive_players if p.role is Role.DETECTIVE), None
        )
        if detective is not None:
            t_det = await _user_t(session, detective.user_id)
            try:
                await bot.send_message(
                    detective.user_id,
                    detective_result(
                        t_det,
                        outcome.detective_suspect.full_name,
                        outcome.detective_is_mafia,
                    ),
                )
            except TelegramBadRequest:
                logger.warning("Could not DM detective result.")

    # Announce the victim (or lack thereof) in the group.
    if outcome.killed is not None:
        killed_row = await _kill_player(session, game.game_id, outcome.killed.user_id)
        outcome.killed.is_alive = False
        await bot.send_message(
            game.chat_id, night_killed(t_group, killed_row.full_name)
        )
    else:
        await bot.send_message(game.chat_id, t_group("night.nobody_died"))

    winner = game.evaluate_winner()
    if winner is not None:
        await end_game(bot, games, timers, session, game, winner)
        return

    await start_discussion(bot, games, timers, session, game)


# ---------------------------------------------------------------------------
# Day discussion + vote
# ---------------------------------------------------------------------------

async def start_discussion(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
) -> None:
    game.phase = GamePhase.DAY_DISCUSSION
    t_group = await _group_t(session, game)
    await bot.send_message(game.chat_id, t_group("day.discussion"))
    timers.schedule(
        game.game_id,
        DAY_DISCUSSION_DURATION,
        _on_discussion_timeout(bot, games, timers, session, game),
    )


def _on_discussion_timeout(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
):
    async def _cb() -> None:
        await start_vote(bot, games, timers, session, game)

    return _cb


async def start_vote(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
) -> None:
    if games.get(game.chat_id) is not game:
        return
    timers.cancel(game.game_id)
    game.begin_vote()

    t_group = await _group_t(session, game)
    await bot.send_message(game.chat_id, t_group("day.vote_started"))

    # Send a private vote keyboard to every alive player (in their language).
    for player in game.alive_players:
        t_user = await _user_t(session, player.user_id)
        try:
            await bot.send_message(
                player.user_id,
                t_user("day.vote_prompt_pm"),
                reply_markup=vote_kb(game, player.user_id),
            )
        except TelegramBadRequest:
            logger.warning(
                "Could not DM vote keyboard to user %s.", player.user_id
            )

    timers.schedule(
        game.game_id,
        DAY_VOTE_DURATION,
        _on_vote_timeout(bot, games, timers, session, game),
    )


def _on_vote_timeout(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
):
    async def _cb() -> None:
        await end_vote(bot, games, timers, session, game)

    return _cb


async def end_vote(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
) -> None:
    if games.get(game.chat_id) is not game:
        return
    timers.cancel(game.game_id)

    t_group = await _group_t(session, game)
    result = DayService(game).resolve()
    if result.lynched is not None:
        killed_row = await _kill_player(session, game.game_id, result.lynched.user_id)
        result.lynched.is_alive = False
        await bot.send_message(
            game.chat_id,
            vote_result_lynch(t_group, killed_row.full_name, Role(result.lynched.role)),
        )
    else:
        await bot.send_message(game.chat_id, vote_result_no_lynch(t_group))

    winner = game.evaluate_winner()
    if winner is not None:
        await end_game(bot, games, timers, session, game, winner)
        return

    await start_night(bot, games, timers, session, game)


# ---------------------------------------------------------------------------
# End of game
# ---------------------------------------------------------------------------

async def end_game(
    bot: Bot,
    games: LobbyService,
    timers: TimerManager,
    session: AsyncSession,
    game: GameSession,
    winner: Winner,
) -> None:
    timers.cancel(game.game_id)
    game.phase = GamePhase.ENDED
    t_group = await _group_t(session, game)

    # Persist final state.
    game_row = await GameRepo(session).get(game.game_id)
    if game_row is not None:
        await GameRepo(session).finish(
            game_row,
            winner=winner.value,
            rounds_played=game.round_number,
        )

    # Update per-user stats (win/loss depending on role + winner).
    stats = StatsRepo(session)
    for player in game.players.values():
        is_mafia_side = player.role is Role.MAFIA
        won = (
            winner is Winner.MAFIA and is_mafia_side
            or winner is Winner.CITY and not is_mafia_side
        )
        await stats.record_result(player.user_id, player.full_name, won=won)

    games.remove(game.chat_id)

    # Public announcement + role reveal in the group language.
    reveal = "\n".join(
        role_reveal_line(t_group, p.full_name, Role(p.role)) for p in game.players.values()
    )
    await bot.send_message(
        game.chat_id,
        f"{game_over(t_group, winner)}\n\n{role_reveal_header(t_group)}\n{reveal}",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _kill_player(
    session: AsyncSession, game_id: int, user_id: int
):
    player = await PlayerRepo(session).get(game_id, user_id)
    if player is not None:
        await PlayerRepo(session).kill(player)
    return player


async def _prompt_mafia(
    bot: Bot, session: AsyncSession, game: GameSession
) -> None:
    mafia = game.alive_of(Role.MAFIA)
    if not mafia:
        return
    for member in mafia:
        kb = mafia_targets_kb(game, member.user_id)
        t_user = await _user_t(session, member.user_id)
        try:
            await bot.send_message(
                member.user_id,
                t_user("night.mafia_prompt"),
                reply_markup=kb,
            )
        except TelegramBadRequest:
            logger.warning("Could not DM mafia prompt to %s.", member.user_id)


async def _prompt_detective(
    bot: Bot, session: AsyncSession, game: GameSession
) -> None:
    detectives = game.alive_of(Role.DETECTIVE)
    if not detectives:
        return
    detective = detectives[0]
    kb = detective_targets_kb(game, detective.user_id)
    t_user = await _user_t(session, detective.user_id)
    try:
        await bot.send_message(
            detective.user_id,
            t_user("night.detective_prompt"),
            reply_markup=kb,
        )
    except TelegramBadRequest:
        logger.warning("Could not DM detective prompt.")


async def _prompt_doctor(
    bot: Bot, session: AsyncSession, game: GameSession
) -> None:
    doctors = game.alive_of(Role.DOCTOR)
    if not doctors:
        return
    doctor = doctors[0]
    kb = doctor_targets_kb(game, doctor.user_id)
    t_user = await _user_t(session, doctor.user_id)
    try:
        await bot.send_message(
            doctor.user_id,
            t_user("night.doctor_prompt"),
            reply_markup=kb,
        )
    except TelegramBadRequest:
        logger.warning("Could not DM doctor prompt.")
