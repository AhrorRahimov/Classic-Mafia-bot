"""Day voting and lynching."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.game.exceptions import VoteError
from app.services.session import GameSession, PlayerState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VoteResult:
    """Outcome of the daytime vote."""

    lynched: Optional[PlayerState] = None
    tally: dict[int, int] = None  # type: ignore[assignment]
    total_votes: int = 0


class DayService:
    """Collects and resolves daytime lynching votes."""

    def __init__(self, session: GameSession) -> None:
        self._s = session

    def cast_vote(self, voter_id: int, target_id: int) -> None:
        voter = self._s.get(voter_id)
        if voter is None:
            raise VoteError("errors.not_participant")
        if not voter.is_alive:
            raise VoteError("errors.dead_no_vote")
        target = self._s.get(target_id)
        if target is None or not target.is_alive:
            raise VoteError("errors.vote_alive_only")
        if target_id == voter_id:
            raise VoteError("errors.no_self_vote")

        # Allow changing the vote until phase ends.
        self._s.day.cast(voter_id, target_id)
        logger.debug(
            "Vote: chat=%s voter=%s target=%s",
            self._s.chat_id, voter_id, target_id,
        )

    def has_voted(self, user_id: int) -> bool:
        return user_id in self._s.day.voted

    def all_required_voted(self) -> bool:
        required = {p.user_id for p in self._s.alive_players}
        return required.issubset(self._s.day.voted)

    def resolve(self) -> VoteResult:
        """Tally votes; the highest-voted player is lynched.

        On a tie nobody is lynched (the city cannot agree).
        """
        votes = self._s.day.votes
        if not votes:
            self._s.day.reset()
            return VoteResult(lynched=None, tally={}, total_votes=0)

        tally: dict[int, int] = {}
        for target_id in votes.values():
            tally[target_id] = tally.get(target_id, 0) + 1

        max_votes = max(tally.values())
        top = [uid for uid, n in tally.items() if n == max_votes]

        lynched: Optional[PlayerState] = None
        if len(top) == 1:
            lynched = self._s.get(top[0])

        logger.info(
            "Vote resolved: chat=%s round=%s lynched=%s",
            self._s.chat_id, self._s.round_number,
            getattr(lynched, "user_id", None),
        )
        self._s.day.reset()
        return VoteResult(
            lynched=lynched,
            tally=tally,
            total_votes=sum(tally.values()),
        )
