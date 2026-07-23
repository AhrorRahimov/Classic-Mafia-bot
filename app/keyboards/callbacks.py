"""Callback-data schema used across inline keyboards.

We use a ``<action>:<arg>`` payload format. ``arg`` is usually the
``user_id`` of the chosen target, or the ``game_id`` for lobby actions.
Keeping actions in an enum prevents typos in magic strings scattered
throughout the handlers.
"""
from __future__ import annotations

from enum import StrEnum


class CallbackAction(StrEnum):
    """All inline-button callback actions."""

    # Lobby
    JOIN = "join"
    LEAVE = "leave"
    START = "start"

    # Night
    MAFIA_KILL = "mafia_kill"
    DETECTIVE_CHECK = "detective_check"
    DOCTOR_HEAL = "doctor_heal"

    # Day
    VOTE = "vote"

    # Settings
    SET_LANG = "set_lang"


def parse_callback(data: str) -> tuple[CallbackAction, int]:
    """Parse ``<action>:<arg>`` into ``(CallbackAction, int)``.

    Raises:
        ValueError: if the payload is malformed.
    """
    action_str, _, arg_str = data.partition(":")
    return CallbackAction(action_str), int(arg_str)
