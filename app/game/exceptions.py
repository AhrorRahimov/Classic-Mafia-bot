"""Domain-specific exceptions for clean error handling in handlers."""
from __future__ import annotations


class GameError(Exception):
    """Base error for any game-related failure."""


class LobbyError(GameError):
    """Lobby-related precondition failed (full, already joined, etc)."""


class PhaseError(GameError):
    """Action is not allowed in the current phase."""


class RoleError(GameError):
    """Player's role does not permit this action."""


class TargetError(GameError):
    """Selected target is invalid (dead, self, same team, etc)."""


class VoteError(GameError):
    """Voting-related failure (already voted, etc)."""
