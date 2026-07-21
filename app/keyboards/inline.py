"""Inline keyboard builders for lobby, voting and night actions.

Callback payload format is ``<action>:<arg>`` where ``arg`` is the
``game_id`` for lobby buttons or the target ``user_id`` for night and
vote buttons. Decoding is centralised in ``app.keyboards.callbacks``.
"""
from __future__ import annotations

from typing import Iterable

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.game.enums import Role
from app.keyboards.callbacks import CallbackAction
from app.services.session import GameSession, PlayerState


# --- Lobby -------------------------------------------------------------

def lobby_kb(game_id: int) -> InlineKeyboardMarkup:
    """Join / Leave / Start buttons for an open lobby."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Присоединиться",
        callback_data=f"{CallbackAction.JOIN}:{game_id}",
    )
    builder.button(
        text="➖ Выйти",
        callback_data=f"{CallbackAction.LEAVE}:{game_id}",
    )
    builder.button(
        text="✅ Начать игру",
        callback_data=f"{CallbackAction.START}:{game_id}",
    )
    builder.adjust(2, 1)
    return builder.as_markup()


# --- Night actions -----------------------------------------------------

def _safe_label(player: PlayerState) -> str:
    """Trim long names so the inline button stays under Telegram's limit."""
    name = player.full_name or f"User {player.user_id}"
    return name[:60]


def _targets_kb(
    action: CallbackAction, candidates: Iterable[PlayerState]
) -> InlineKeyboardMarkup:
    """Vertical list of alive targets for a night action."""
    builder = InlineKeyboardBuilder()
    for player in candidates:
        builder.button(
            text=_safe_label(player),
            callback_data=f"{action.value}:{player.user_id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def mafia_targets_kb(session: GameSession, actor_id: int) -> InlineKeyboardMarkup:
    """Mafia can target any alive non-mafia player.

    ``actor_id`` is accepted for API symmetry with the other night-action
    keyboards but not used: mafia members are all on the same team.
    """
    _ = actor_id  # explicit no-op for clarity
    targets = [p for p in session.alive_players if p.role is not Role.MAFIA]
    return _targets_kb(CallbackAction.MAFIA_KILL, targets)


def detective_targets_kb(
    session: GameSession, actor_id: int
) -> InlineKeyboardMarkup:
    """Detective can check any alive player except themselves."""
    targets = [
        p
        for p in session.alive_players
        if p.user_id != actor_id
    ]
    return _targets_kb(CallbackAction.DETECTIVE_CHECK, targets)


def doctor_targets_kb(session: GameSession, actor_id: int) -> InlineKeyboardMarkup:
    """Doctor can heal any alive player except the one healed last night."""
    targets = [
        p
        for p in session.alive_players
        if p.user_id != session.last_healed
    ]
    return _targets_kb(CallbackAction.DOCTOR_HEAL, targets)


# --- Day vote ----------------------------------------------------------

def vote_kb(session: GameSession, voter_id: int) -> InlineKeyboardMarkup:
    """Vote targets: every alive player except the voter."""
    targets = [p for p in session.alive_players if p.user_id != voter_id]
    return _targets_kb(CallbackAction.VOTE, targets)
