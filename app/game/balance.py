"""Role distribution logic per player count.

Balance table (designed for 4–10 players):
    4 players -> 1 mafia, 1 detective, 1 doctor, 1 citizen
    5 players -> 1 mafia, 1 detective, 1 doctor, 2 citizens
    6 players -> 1 mafia, 1 detective, 1 doctor, 3 citizens
    7 players -> 2 mafia, 1 detective, 1 doctor, 3 citizens
    8 players -> 2 mafia, 1 detective, 1 doctor, 4 citizens
    9 players -> 2 mafia, 1 detective, 1 doctor, 5 citizens
   10 players -> 3 mafia, 1 detective, 1 doctor, 5 citizens
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from app.game.constants import MAX_PLAYERS, MIN_PLAYERS
from app.game.enums import Role


@dataclass(frozen=True, slots=True)
class RoleSetup:
    """How many of each role should be in the game."""

    mafia: int
    detective: int
    doctor: int
    citizen: int

    @property
    def total(self) -> int:
        return self.mafia + self.detective + self.doctor + self.citizen

    def to_list(self) -> list[Role]:
        """Expand setup into a flat list of roles (order irrelevant)."""
        return (
            [Role.MAFIA] * self.mafia
            + [Role.DETECTIVE] * self.detective
            + [Role.DOCTOR] * self.doctor
            + [Role.CITIZEN] * self.citizen
        )


# Static balance table — single source of truth for setup.
_BALANCE_TABLE: dict[int, RoleSetup] = {
    4: RoleSetup(1, 1, 1, 1),
    5: RoleSetup(1, 1, 1, 2),
    6: RoleSetup(1, 1, 1, 3),
    7: RoleSetup(2, 1, 1, 3),
    8: RoleSetup(2, 1, 1, 4),
    9: RoleSetup(2, 1, 1, 5),
    10: RoleSetup(3, 1, 1, 5),
}


def is_valid_player_count(count: int) -> bool:
    """Check if a lobby size can start a game."""
    return MIN_PLAYERS <= count <= MAX_PLAYERS


def get_setup(player_count: int) -> RoleSetup:
    """Return the role setup for a given player count.

    Raises:
        ValueError: if player_count is outside [MIN_PLAYERS, MAX_PLAYERS].
    """
    if not is_valid_player_count(player_count):
        raise ValueError(
            f"Player count must be {MIN_PLAYERS}–{MAX_PLAYERS}, got {player_count}."
        )
    return _BALANCE_TABLE[player_count]


def shuffle_roles(
    player_count: int, rng: random.Random | None = None
) -> list[Role]:
    """Return a shuffled list of roles for the given player count."""
    rng = rng or random.Random()
    roles = get_setup(player_count).to_list()
    rng.shuffle(roles)
    return roles


def assign_roles(
    user_ids: Iterable[int],
    rng: random.Random | None = None,
) -> dict[int, Role]:
    """Assign a role to each user id (random order).

    Raises:
        ValueError: if the number of users is invalid.
    """
    user_id_list = list(user_ids)
    roles = shuffle_roles(len(user_id_list), rng=rng)
    return dict(zip(user_id_list, roles))
