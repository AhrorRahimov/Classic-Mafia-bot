"""In-memory state of an active game.

This module is the single source of truth for runtime game state.
Database rows mirror final results, but per-second gameplay
(votes, night actions, phases) lives here to avoid hot-writing SQL.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from app.game.enums import GamePhase, Role, Winner


@dataclass(slots=True)
class PlayerState:
    """Runtime view of a player inside an active game."""

    user_id: int
    full_name: str
    role: Role
    is_alive: bool = True

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        status = "alive" if self.is_alive else "dead"
        return f"<Player {self.full_name} ({self.role.value}, {status})>"


@dataclass(slots=True)
class NightActions:
    """Collected choices during a single night."""

    # mafia_target: a single user_id — the team must converge.
    mafia_target: Optional[int] = None
    detective_target: Optional[int] = None
    doctor_target: Optional[int] = None
    # Per-mafia votes to decide the team target.
    mafia_votes: dict[int, int] = field(default_factory=dict)
    # Track who has acted this night so we know when everyone is done.
    acted: set[int] = field(default_factory=set)

    def reset(self) -> None:
        """Clear all choices for the next night."""
        self.mafia_target = None
        self.detective_target = None
        self.doctor_target = None
        self.mafia_votes.clear()
        self.acted.clear()


@dataclass(slots=True)
class DayVotes:
    """Collected votes during the daytime lynching phase."""

    # voter_user_id -> target_user_id
    votes: dict[int, int] = field(default_factory=dict)
    # Track who has voted.
    voted: set[int] = field(default_factory=set)

    def reset(self) -> None:
        self.votes.clear()
        self.voted.clear()

    def cast(self, voter: int, target: int) -> None:
        self.votes[voter] = target
        self.voted.add(voter)


@dataclass(slots=True)
class GameSession:
    """All mutable state for a running game.

    Lives in a process-local registry keyed by chat_id; see
    ``app.services.lobby`` and ``app.services.session`` modules.
    """

    game_id: int
    chat_id: int
    creator_id: int
    players: dict[int, PlayerState]
    phase: GamePhase = GamePhase.NIGHT
    round_number: int = 0
    night: NightActions = field(default_factory=NightActions)
    day: DayVotes = field(default_factory=DayVotes)
    last_healed: Optional[int] = None  # doctor cannot heal same target twice
    last_detective_check: Optional[tuple[int, bool]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # --- players helpers -------------------------------------------------

    @property
    def alive_players(self) -> list[PlayerState]:
        return [p for p in self.players.values() if p.is_alive]

    def get(self, user_id: int) -> Optional[PlayerState]:
        return self.players.get(user_id)

    def alive_of(self, role: Role) -> list[PlayerState]:
        return [p for p in self.alive_players if p.role is role]

    def alive_roles(self) -> set[Role]:
        return {p.role for p in self.alive_players}

    def count_alive(self, role: Role) -> int:
        return sum(1 for p in self.players.values() if p.is_alive and p.role is role)

    # --- night / day reset helpers --------------------------------------

    def begin_night(self) -> None:
        self.round_number += 1
        self.phase = GamePhase.NIGHT
        self.night.reset()

    def begin_vote(self) -> None:
        self.phase = GamePhase.DAY_VOTE
        self.day.reset()

    # --- win-condition check --------------------------------------------

    def evaluate_winner(self) -> Optional[Winner]:
        """Return the winner if the game has ended, else ``None``."""
        mafia_alive = self.count_alive(Role.MAFIA)
        non_mafia_alive = sum(
            1
            for p in self.players.values()
            if p.is_alive and p.role is not Role.MAFIA
        )

        if mafia_alive == 0:
            return Winner.CITY
        if mafia_alive >= non_mafia_alive:
            # Mafia equals/exceeds citizens — they cannot lose anymore.
            return Winner.MAFIA
        return None
