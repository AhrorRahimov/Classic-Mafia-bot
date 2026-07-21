"""Night actions: mafia kill, detective check, doctor heal."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.game.enums import Role
from app.game.exceptions import RoleError, TargetError
from app.services.session import GameSession, PlayerState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NightOutcome:
    """Resolved outcome of a single night."""

    killed: Optional[PlayerState] = None      # who died (None if saved)
    healed: Optional[PlayerState] = None      # who was saved by doctor
    detective_suspect: Optional[PlayerState] = None
    detective_is_mafia: Optional[bool] = None


class NightService:
    """Validates and collects night actions for a game session."""

    def __init__(self, session: GameSession) -> None:
        self._s = session

    # --- eligibility checks ---------------------------------------------

    def _require_alive_actor(self, user_id: int, role: Role) -> PlayerState:
        player = self._s.get(user_id)
        if player is None:
            raise RoleError("Ты не участвуешь в этой игре.")
        if not player.is_alive:
            raise RoleError("Мертвые не говорят.")
        if player.role is not role:
            raise RoleError("Эта роль не может выполнять это действие.")
        return player

    def _require_alive_target(self, target_id: int) -> PlayerState:
        target = self._s.get(target_id)
        if target is None:
            raise TargetError("Цель не найдена.")
        if not target.is_alive:
            raise TargetError("Этот игрок уже мертв.")
        return target

    def has_acted(self, user_id: int) -> bool:
        return user_id in self._s.night.acted

    # --- actions ---------------------------------------------------------

    def mafia_kill(self, actor_id: int, target_id: int) -> None:
        # Validation: raises if actor is not alive mafia or target invalid.
        self._require_alive_actor(actor_id, Role.MAFIA)
        target = self._require_alive_target(target_id)
        if target.role is Role.MAFIA:
            raise TargetError("Мафия не может убивать своих.")
        if actor_id in self._s.night.acted:
            raise RoleError("Ты уже сделал свой ход этой ночью.")

        # Team vote: store per-mafia choice; majority wins (tie -> last wins).
        self._s.night.mafia_votes[actor_id] = target_id
        # Reconcile team target from current votes.
        self._s.night.mafia_target = self._resolve_mafia_target()
        self._s.night.acted.add(actor_id)

    def detective_check(self, actor_id: int, target_id: int) -> bool:
        # Validation: raises if actor is not alive detective or target invalid.
        self._require_alive_actor(actor_id, Role.DETECTIVE)
        target = self._require_alive_target(target_id)
        if actor_id in self._s.night.acted:
            raise RoleError("Ты уже проверял кого-то этой ночью.")

        is_mafia = target.role is Role.MAFIA
        self._s.night.detective_target = target_id
        # Persist the latest check on the session (not on NightActions,
        # which is reset each night) so the orchestrator can reveal it.
        self._s.last_detective_check = (target_id, is_mafia)
        self._s.night.acted.add(actor_id)
        return is_mafia

    def doctor_heal(self, actor_id: int, target_id: int) -> None:
        # Validation: raises if actor is not alive doctor or target invalid.
        self._require_alive_actor(actor_id, Role.DOCTOR)
        self._require_alive_target(target_id)
        if actor_id in self._s.night.acted:
            raise RoleError("Ты уже лечил кого-то этой ночью.")
        # Doctor cannot heal the same player two nights in a row.
        if (
            self._s.last_healed is not None
            and target_id == self._s.last_healed
        ):
            raise TargetError("Нельзя лечить того же игрока два раза подряд.")

        self._s.night.doctor_target = target_id
        self._s.night.acted.add(actor_id)

    # --- resolution ------------------------------------------------------

    def all_required_acted(self) -> bool:
        """True if every alive role-actor has acted this night."""
        required = {
            p.user_id
            for p in self._s.alive_players
            if p.role in (Role.MAFIA, Role.DETECTIVE, Role.DOCTOR)
        }
        return required.issubset(self._s.night.acted)

    def resolve(self) -> NightOutcome:
        """Resolve the night and return its outcome. Resets night state."""
        night = self._s.night
        killed: Optional[PlayerState] = None
        healed: Optional[PlayerState] = None

        mafia_target_id = night.mafia_target
        if mafia_target_id is not None:
            killed = self._s.get(mafia_target_id)
            if night.doctor_target == mafia_target_id:
                healed = killed
                killed = None

        # Doctor restriction carry-over for next night.
        self._s.last_healed = night.doctor_target

        # Detective info is surfaced privately; not part of public outcome.
        # It is stored on the session (not on NightActions) so it survives
        # the per-night reset.
        detective_suspect: Optional[PlayerState] = None
        detective_is_mafia: Optional[bool] = None
        if self._s.last_detective_check is not None:
            tid, is_mafia = self._s.last_detective_check
            detective_suspect = self._s.get(tid)
            detective_is_mafia = is_mafia

        outcome = NightOutcome(
            killed=killed,
            healed=healed,
            detective_suspect=detective_suspect,
            detective_is_mafia=detective_is_mafia,
        )
        logger.info(
            "Night resolved: chat=%s round=%s killed=%s healed=%s",
            self._s.chat_id, self._s.round_number,
            getattr(killed, "user_id", None),
            getattr(healed, "user_id", None),
        )
        return outcome

    # --- private ---------------------------------------------------------

    def _resolve_mafia_target(self) -> Optional[int]:
        """Pick the most-voted mafia target. Tie -> highest voted seen last."""
        votes = self._s.night.mafia_votes
        if not votes:
            return None
        tally: dict[int, int] = {}
        for target_id in votes.values():
            tally[target_id] = tally.get(target_id, 0) + 1
        return max(tally, key=tally.get)
