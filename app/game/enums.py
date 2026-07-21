"""Domain enumerations for the game."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Roles a player can be assigned."""

    CITIZEN = "citizen"
    MAFIA = "mafia"
    DETECTIVE = "detective"
    DOCTOR = "doctor"


class GameStatus(StrEnum):
    """Lifecycle status of a Game row."""

    LOBBY = "lobby"
    RUNNING = "running"
    FINISHED = "finished"


class GamePhase(StrEnum):
    """In-memory phases for an active game (not persisted per row)."""

    NIGHT = "night"
    DAY_ANNOUNCE = "day_announce"
    DAY_DISCUSSION = "day_discussion"
    DAY_VOTE = "day_vote"
    ENDED = "ended"


class Winner(StrEnum):
    """Who won the game."""

    MAFIA = "mafia"
    CITY = "city"
    NONE = "none"
