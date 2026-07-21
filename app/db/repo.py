"""Repository layer: data access for Game / Player / UserStats."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Game, Player, UserStats
from app.game.enums import GameStatus, Role, Winner


class GameRepo:
    """CRUD + domain queries for Game."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, chat_id: int, creator_id: int) -> Game:
        game = Game(chat_id=chat_id, creator_id=creator_id, status=GameStatus.LOBBY)
        self._session.add(game)
        await self._session.flush()
        return game

    async def get_active(self, chat_id: int) -> Optional[Game]:
        """Return the non-finished game for a chat, if any."""
        stmt = (
            select(Game)
            .where(Game.chat_id == chat_id, Game.status != GameStatus.FINISHED)
            .options(selectinload(Game.players))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get(self, game_id: int) -> Optional[Game]:
        stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.players))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_status(self, game: Game, status: str) -> None:
        game.status = status
        await self._session.flush()

    async def finish(
        self, game: Game, winner: str, rounds_played: int
    ) -> None:
        game.status = GameStatus.FINISHED
        game.winner = winner
        game.rounds_played = rounds_played
        game.finished_at = datetime.now(timezone.utc)
        await self._session.flush()


class PlayerRepo:
    """CRUD + domain queries for Player."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        game_id: int,
        user_id: int,
        full_name: str,
    ) -> Player:
        player = Player(
            game_id=game_id,
            user_id=user_id,
            full_name=full_name,
        )
        self._session.add(player)
        await self._session.flush()
        return player

    async def get(self, game_id: int, user_id: int) -> Optional[Player]:
        stmt = select(Player).where(
            Player.game_id == game_id, Player.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_game(self, game_id: int) -> list[Player]:
        stmt = select(Player).where(Player.game_id == game_id).order_by(Player.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def remove(self, player: Player) -> None:
        await self._session.delete(player)
        await self._session.flush()

    async def assign_role(self, player: Player, role: Role) -> None:
        player.role = role.value
        await self._session.flush()

    async def kill(self, player: Player) -> None:
        player.is_alive = False
        await self._session.flush()


class StatsRepo:
    """Persistent per-user statistics."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_touch(self, user_id: int, full_name: str) -> None:
        stats = await self._session.get(UserStats, user_id)
        if stats is None:
            stats = UserStats(user_id=user_id, full_name=full_name)
            self._session.add(stats)
        else:
            stats.full_name = full_name
            stats.last_seen_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def record_result(
        self, user_id: int, full_name: str, *, won: bool
    ) -> None:
        await self.upsert_touch(user_id, full_name)
        stats = await self._session.get(UserStats, user_id)
        assert stats is not None  # noqa: S101 — upsert guarantees it
        stats.games_played += 1
        if won:
            stats.wins += 1
        else:
            stats.losses += 1
        await self._session.flush()

    async def get(self, user_id: int) -> Optional[UserStats]:
        return await self._session.get(UserStats, user_id)


# Re-export winner enum alias to avoid circular imports in callers.
__all__ = ["GameRepo", "PlayerRepo", "StatsRepo", "Winner"]
