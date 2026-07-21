"""Lobby operations and the process-local session registry.

The registry maps ``chat_id -> GameSession`` for any running game in
this process. Database rows (``Game``, ``Player``) mirror the data so
that finished games and stats survive restarts.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game
from app.db.repo import GameRepo, PlayerRepo, StatsRepo
from app.game.balance import assign_roles
from app.game.constants import MAX_PLAYERS, MIN_PLAYERS
from app.game.enums import GameStatus, Role
from app.game.exceptions import LobbyError
from app.services.session import GameSession, PlayerState

logger = logging.getLogger(__name__)


class LobbyService:
    """Manages lobby creation, joining, leaving and starting games."""

    def __init__(self) -> None:
        # chat_id -> live GameSession (only running games live here)
        self._sessions: dict[int, GameSession] = {}
        # chat_id -> creator_id for active lobbies (status LOBBY)
        self._lobby_creators: dict[int, int] = {}

    # --- registry access -------------------------------------------------

    def get(self, chat_id: int) -> Optional[GameSession]:
        return self._sessions.get(chat_id)

    def has(self, chat_id: int) -> bool:
        return chat_id in self._sessions

    def remove(self, chat_id: int) -> Optional[GameSession]:
        self._lobby_creators.pop(chat_id, None)
        return self._sessions.pop(chat_id, None)

    # --- lobby lifecycle -------------------------------------------------

    async def create_lobby(
        self,
        db: AsyncSession,
        chat_id: int,
        creator_id: int,
        creator_name: str,
    ) -> Game:
        """Create a new lobby. Raises if another game is active in the chat."""
        if self.has(chat_id):
            raise LobbyError("В этом чате уже идёт игра или открыто лобби.")
        active = await GameRepo(db).get_active(chat_id)
        if active is not None:
            raise LobbyError("В этом чате уже есть активная игра в БД.")

        game = await GameRepo(db).create(chat_id=chat_id, creator_id=creator_id)
        await PlayerRepo(db).add(
            game_id=game.id, user_id=creator_id, full_name=creator_name
        )
        await StatsRepo(db).upsert_touch(creator_id, creator_name)
        await db.commit()

        self._lobby_creators[chat_id] = creator_id
        logger.info("Lobby created: chat=%s creator=%s game_id=%s",
                    chat_id, creator_id, game.id)
        return game

    async def join(
        self,
        db: AsyncSession,
        chat_id: int,
        user_id: int,
        full_name: str,
    ) -> Game:
        """Add a player to the active lobby for ``chat_id``."""
        game = await self._require_lobby(db, chat_id)
        players = await PlayerRepo(db).list_by_game(game.id)

        if any(p.user_id == user_id for p in players):
            raise LobbyError("Ты уже в лобби.")
        if len(players) >= MAX_PLAYERS:
            raise LobbyError(f"Лобби заполнено (максимум {MAX_PLAYERS} игроков).")

        await PlayerRepo(db).add(
            game_id=game.id, user_id=user_id, full_name=full_name
        )
        await StatsRepo(db).upsert_touch(user_id, full_name)
        await db.commit()
        logger.info("Player joined: chat=%s user=%s", chat_id, user_id)
        return game

    async def leave(
        self,
        db: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> Game:
        """Remove a player from the active lobby."""
        game = await self._require_lobby(db, chat_id)
        players = await PlayerRepo(db).list_by_game(game.id)
        player = next((p for p in players if p.user_id == user_id), None)
        if player is None:
            raise LobbyError("Тебя нет в этом лобби.")

        # Creator leaving dissolves the lobby.
        if game.creator_id == user_id:
            await self._cancel_lobby(db, chat_id, game)
            raise LobbyError("_creator_left_")

        await PlayerRepo(db).remove(player)
        await db.commit()
        logger.info("Player left: chat=%s user=%s", chat_id, user_id)
        return game

    async def cancel(
        self, db: AsyncSession, chat_id: int, by_user_id: int
    ) -> None:
        """Cancel the lobby (creator-only)."""
        game = await self._require_lobby(db, chat_id)
        if game.creator_id != by_user_id:
            raise LobbyError("Отменить лобби может только его создатель.")
        await self._cancel_lobby(db, chat_id, game)

    async def start(
        self,
        db: AsyncSession,
        chat_id: int,
        rng: Optional[random.Random] = None,
    ) -> GameSession:
        """Promote the lobby to a running game and return its session."""
        game = await self._require_lobby(db, chat_id)
        players = await PlayerRepo(db).list_by_game(game.id)

        if game.creator_id not in {p.user_id for p in players}:
            # Edge case: creator left but lobby still tracked. Reset.
            await self._cancel_lobby(db, chat_id, game)
            raise LobbyError("Создатель покинул лобби. Создай новую игру.")

        count = len(players)
        if not (MIN_PLAYERS <= count <= MAX_PLAYERS):
            raise LobbyError(
                f"Нужно {MIN_PLAYERS}–{MAX_PLAYERS} игроков. Сейчас: {count}."
            )

        # Assign roles.
        assignments = assign_roles([p.user_id for p in players], rng=rng)
        player_repo = PlayerRepo(db)
        name_by_id = {p.user_id: p.full_name for p in players}
        states: dict[int, PlayerState] = {}
        for user_id, role in assignments.items():
            # Persist role on the matching Player row.
            row = next(p for p in players if p.user_id == user_id)
            await player_repo.assign_role(row, Role(role))
            states[user_id] = PlayerState(
                user_id=user_id,
                full_name=name_by_id[user_id],
                role=Role(role),
            )

        await GameRepo(db).set_status(game, GameStatus.RUNNING)
        await db.commit()

        session = GameSession(
            game_id=game.id,
            chat_id=chat_id,
            creator_id=game.creator_id,
            players=states,
        )
        self._sessions[chat_id] = session
        self._lobby_creators.pop(chat_id, None)
        logger.info(
            "Game started: chat=%s game_id=%s players=%s",
            chat_id, game.id, count,
        )
        return session

    # --- private helpers -------------------------------------------------

    async def _require_lobby(self, db: AsyncSession, chat_id: int) -> Game:
        game = await GameRepo(db).get_active(chat_id)
        if game is None or game.status != GameStatus.LOBBY:
            raise LobbyError("В этом чате нет открытого лобби.")
        return game

    async def _cancel_lobby(
        self, db: AsyncSession, chat_id: int, game: Game
    ) -> None:
        await GameRepo(db).set_status(game, GameStatus.FINISHED)
        game.winner = "none"
        await db.commit()
        self.remove(chat_id)
        logger.info("Lobby cancelled: chat=%s game_id=%s", chat_id, game.id)
