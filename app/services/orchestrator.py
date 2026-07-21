"""Game orchestrator: high-level transitions between phases.

This module glues services (lobby, night, day, timer) together and
talks to Telegram on behalf of handlers. Handlers stay thin: they
delegate phase transitions here so the flow logic lives in one place.

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
    DAY_DISCUSSION,
    DAY_VOTE_STARTED,
    NIGHT_ENDED_NOBODY,
    NIGHT_STARTED,
    detective_result,
    game_over,
    night_killed,
    vote_result_no_lynch,
    vote_result_lynch,
)

logger = logging.getLogger(__name__)


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

    await bot.send_message(chat_id, NIGHT_STARTED)

    # DM each role its targets. Skip citizens — they have nothing to do.
    await _prompt_mafia(bot, game)
    await _prompt_detective(bot, game)
    await _prompt_doctor(bot, game)

    timers.schedule(game.game_id, NIGHT_DURATION, _on_night_timeout(bot, games, timers, session, game))


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
    # Defensive: if the game was cancelled meanwhile, do nothing.
    if games.get(game.chat_id) is not game:
        return

    timers.cancel(game.game_id)
    outcome = NightService(game).resolve()

    # Reveal detective result privately before resetting.
    if outcome.detective_suspect is not None and outcome.detective_is_mafia is not None:
        detective = next(
            (p for p in game.alive_players if p.role is Role.DETECTIVE), None
        )
        if detective is not None:
            try:
                await bot.send_message(
                    detective.user_id,
                    detective_result(
                        outcome.detective_suspect.full_name,
                        outcome.detective_is_mafia,
                    ),
                )
            except TelegramBadRequest:
                logger.warning("Could not DM detective result.")

    if outcome.killed is not None:
        killed_row = await _kill_player(session, game.game_id, outcome.killed.user_id)
        outcome.killed.is_alive = False
        await bot.send_message(
            game.chat_id, night_killed(killed_row.full_name)
        )
    else:
        await bot.send_message(game.chat_id, NIGHT_ENDED_NOBODY)

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
    await bot.send_message(game.chat_id, DAY_DISCUSSION)
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

    await bot.send_message(game.chat_id, DAY_VOTE_STARTED)

    # Send a private vote keyboard to every alive player.
    for player in game.alive_players:
        try:
            await bot.send_message(
                player.user_id,
                "⚖️ За кого голосуешь?",
                reply_markup=vote_kb(game, player.user_id),
            )
        except TelegramBadRequest:
            logger.warning("Could not DM vote keyboard to user %s.", player.user_id)

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

    result = DayService(game).resolve()
    if result.lynched is not None:
        killed_row = await _kill_player(session, game.game_id, result.lynched.user_id)
        result.lynched.is_alive = False
        await bot.send_message(
            game.chat_id,
            vote_result_lynch(killed_row.full_name, Role(result.lynched.role)),
        )
    else:
        await bot.send_message(game.chat_id, vote_result_no_lynch())

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

    # Public announcement + role reveal.
    reveal = "\n".join(
        f"• <b>{p.full_name}</b> — {p.role.value}" for p in game.players.values()
    )
    await bot.send_message(
        game.chat_id,
        f"{game_over(winner)}\n\n<b>Роли игроков:</b>\n{reveal}",
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


async def _prompt_mafia(bot: Bot, game: GameSession) -> None:
    mafia = game.alive_of(Role.MAFIA)
    if not mafia:
        return
    kb = mafia_targets_kb(game, mafia[0].user_id)
    for member in mafia:
        try:
            await bot.send_message(
                member.user_id,
                "🔴 <b>Мафия, выберите жертву.</b>",
                reply_markup=kb,
            )
        except TelegramBadRequest:
            logger.warning("Could not DM mafia prompt to %s.", member.user_id)


async def _prompt_detective(bot: Bot, game: GameSession) -> None:
    detectives = game.alive_of(Role.DETECTIVE)
    if not detectives:
        return
    kb = detective_targets_kb(game, detectives[0].user_id)
    detective = detectives[0]
    try:
        await bot.send_message(
            detective.user_id,
            "🔵 <b>Детектив, кого проверяем?</b>",
            reply_markup=kb,
        )
    except TelegramBadRequest:
        logger.warning("Could not DM detective prompt.")


async def _prompt_doctor(bot: Bot, game: GameSession) -> None:
    doctors = game.alive_of(Role.DOCTOR)
    if not doctors:
        return
    kb = doctor_targets_kb(game, doctors[0].user_id)
    doctor = doctors[0]
    try:
        await bot.send_message(
            doctor.user_id,
            "🟡 <b>Доктор, кого лечим?</b>",
            reply_markup=kb,
        )
    except TelegramBadRequest:
        logger.warning("Could not DM doctor prompt.")
