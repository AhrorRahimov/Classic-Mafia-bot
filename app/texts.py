"""User-facing text builders parameterised by a translator.

Centralising copy in one module keeps handlers short. Every function
takes ``t`` (a ``Translator`` callable bound to the user's language)
as its first argument so the resulting string is in the right locale.
"""
from __future__ import annotations

from typing import Callable, Iterable

from app.db.models import UserStats
from app.game.constants import MAX_PLAYERS, MIN_PLAYERS
from app.game.enums import Role, Winner
from app.services.session import GameSession, PlayerState


# --- Translator type hint ---------------------------------------------

# A Translator is a callable: t(key: str, **kwargs) -> str
Translator = Callable[..., str]


# --- Lobby -------------------------------------------------------------

def lobby_opened(t: Translator, creator_name: str, players: Iterable[str]) -> str:
    player_list = "\n".join(f"• {name}" for name in players)
    if not player_list:
        player_list = t("lobby.players_empty")
    return t(
        "lobby.opened",
        creator=creator_name,
        players=player_list,
        min=MIN_PLAYERS,
        max=MAX_PLAYERS,
    )


# --- Roles -------------------------------------------------------------

def your_role(t: Translator, role: Role, extra: str = "") -> str:
    title = t(f"role.{role.value}.title")
    description = t(f"role.{role.value}.description")
    footer = t("role.your_role_footer")
    text = f"<b>{title}</b>\n\n{description}\n\n{footer}"
    if extra:
        text += f"\n\n{extra}"
    return text


def mafia_teammates(t: Translator, teammates: list[PlayerState]) -> str:
    if not teammates:
        return ""
    names = ", ".join(p.full_name for p in teammates)
    return t("role.mafia_teammates", names=names)


def role_title(t: Translator, role: Role) -> str:
    """Localised role title (used in lynching announcements, reveal)."""
    return t(f"role.{role.value}.title")


def role_reveal_line(t: Translator, name: str, role: Role) -> str:
    return t("role.reveal_line", name=name, role=role_title(t, role))


def role_reveal_header(t: Translator) -> str:
    return t("role.reveal_header")


# --- Detective ---------------------------------------------------------

def detective_result(t: Translator, target_name: str, is_mafia: bool) -> str:
    verdict_key = (
        "night.detective_verdict_mafia"
        if is_mafia
        else "night.detective_verdict_clean"
    )
    return t(
        "night.detective_result",
        name=target_name,
        verdict=t(verdict_key),
    )


# --- Day / vote --------------------------------------------------------

def night_killed(t: Translator, name: str) -> str:
    return t("night.killed", name=name)


def vote_result_lynch(t: Translator, name: str, role: Role) -> str:
    return t("day.vote_result_lynch", name=name, role=role_title(t, role))


def vote_result_no_lynch(t: Translator) -> str:
    return t("day.vote_result_no_lynch")


# --- End of game -------------------------------------------------------

def game_over(t: Translator, winner: Winner) -> str:
    if winner is Winner.MAFIA:
        return t("game_over.mafia_wins")
    if winner is Winner.CITY:
        return t("game_over.city_wins")
    return t("game_over.none")


# --- Stats -------------------------------------------------------------

def stats_text(t: Translator, stats: UserStats | None) -> str:
    if stats is None:
        return t("stats.empty")
    winrate = (
        f"{(stats.wins / stats.games_played * 100):.0f}%"
        if stats.games_played
        else "—"
    )
    return t(
        "stats.text",
        played=stats.games_played,
        wins=stats.wins,
        losses=stats.losses,
        winrate=winrate,
    )


# --- Helpers -----------------------------------------------------------

def player_names(session: GameSession, *, alive_only: bool = False) -> list[str]:
    players = session.alive_players if alive_only else list(session.players.values())
    return [p.full_name for p in players]
