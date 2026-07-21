"""User-facing text templates (HTML-formatted).

Centralising copy keeps handlers short and makes future translation
straightforward. All strings are returned as HTML so they can be sent
with ``parse_mode=HTML`` without further escaping of static parts.
"""
from __future__ import annotations

from typing import Iterable

from app.db.models import UserStats
from app.game.constants import MIN_PLAYERS, MAX_PLAYERS
from app.game.enums import Role, Winner
from app.services.session import GameSession, PlayerState


# --- Basic -------------------------------------------------------------

HELP_TEXT = (
    "<b>🎭 Mafia Bot — игра в мафию с друзьями</b>\n\n"
    "<b>Команды:</b>\n"
    "/newgame — открыть лобби в группе\n"
    "/join — присоединиться к лобби (или кнопкой)\n"
    "/leave — выйти из лобби\n"
    "/startgame — запустить игру (только создатель)\n"
    "/cancel — отменить лобби/игру (только создатель)\n"
    "/stats — твоя статистика\n"
    "/help — эта справка\n\n"
    "<b>Роли:</b>\n"
    "🟢 Житель — голосует днём за подозреваемого\n"
    "🔴 Мафия — каждую ночь убивает одного жителя\n"
    "🔵 Детектив — ночью проверяет, мафия ли игрок\n"
    "🟡 Доктор — ночью спасает одного игрока от смерти\n\n"
    f"<b>Игроков в лобби:</b> {MIN_PLAYERS}–{MAX_PLAYERS}\n"
    "<b>Победа города:</b> уничтожить всю мафию.\n"
    "<b>Победа мафии:</b> сравняться по числу с мирными жителями."
)

START_TEXT = (
    "Привет! Я — <b>Mafia Bot</b> 🎭\n"
    "Добавь меня в группу и используй /newgame, чтобы начать играть "
    "в мафию с друзьями. Нажми /help для полного списка команд."
)

NOT_IN_PRIVATE = "Эту команду можно использовать только в личке с ботом."
NOT_IN_GROUP = "Эту команду нужно использовать в группе, где идёт игра."
NO_ACTIVE_GAME = "В этом чате сейчас нет активной игры."


# --- Lobby -------------------------------------------------------------

def lobby_opened(creator_name: str, players: Iterable[str]) -> str:
    player_list = "\n".join(f"• {name}" for name in players) or "— пусто —"
    return (
        f"<b>🎭 Открыто лобби мафии!</b>\n"
        f"Создатель: {creator_name}\n\n"
        f"<b>Игроки:</b>\n{player_list}\n\n"
        f"Нужно {MIN_PLAYERS}–{MAX_PLAYERS} игроков. "
        "Жмите «Присоединиться», а когда все готовы — «Начать игру»."
    )


def lobby_updated(creator_name: str, players: Iterable[str]) -> str:
    player_list = "\n".join(f"• {name}" for name in players) or "— пусто —"
    return (
        f"<b>Лобби обновлено</b>\n"
        f"Создатель: {creator_name}\n\n"
        f"<b>Игроки ({sum(1 for _ in players)}):</b>\n{player_list}"
    )


# --- Roles -------------------------------------------------------------


def your_role(role: Role, extra: str = "") -> str:
    from app.game.constants import role_text
    text = role_text(role)
    if extra:
        text += f"\n\n{extra}"
    return text


def mafia_teammates(teammates: list[PlayerState]) -> str:
    if not teammates:
        return ""
    names = ", ".join(t.full_name for t in teammates)
    return f"<b>Твои подельщики:</b> {names}"


# --- Night -------------------------------------------------------------

NIGHT_STARTED = (
    "🌙 <b>Город засыпает… просыпается мафия.</b>\n"
    "Активные роли получили личные сообщения с выбором действия. "
    "Ждите рассвета."
)

NIGHT_ENDED_NOBODY = "☀️ <b>Наступило утро.</b> Этой ночью никто не погиб."

def night_killed(name: str) -> str:
    return (
        f"☀️ <b>Наступило утро.</b>\n"
        f"К сожалению, этой ночью погиб <b>{name}</b>. "
        "Собололезнуем. Минута обсуждения — кто подозревается в мафии?"
    )

NIGHT_DONE_PM = "✅ Твой ход принят. Жди рассвета."

def detective_result(target_name: str, is_mafia: bool) -> str:
    verdict = "🔴 МАФИЯ" if is_mafia else "🟢 не мафия"
    return (
        f"🔵 <b>Результат проверки:</b>\n"
        f"<b>{target_name}</b> — {verdict}.\n"
        "Используй информацию аккуратно днём."
    )


# --- Day ---------------------------------------------------------------

DAY_DISCUSSION = (
    "💬 <b>Обсуждение.</b> У вас есть минута, чтобы поделиться "
    "подозрениями. Затем начнётся голосование."
)

DAY_VOTE_STARTED = (
    "⚖️ <b>Голосование!</b>\n"
    "Каждый живой игрок должен проголосовать в личке с ботом "
    "(я прислал тебе кнопку). Время ограничено!"
)

VOTE_DONE_PM = "✅ Твой голос учтён."

def vote_result_no_lynch() -> str:
    return "⚖️ <b>Голосование завершено.</b> Город не смог прийти к согласию — никто не казнён."

def vote_result_lynch(name: str, role: Role) -> str:
    from app.game.constants import ROLE_TITLE
    return (
        f"⚖️ <b>Голосование завершено.</b>\n"
        f"По решению большинства казнён <b>{name}</b> "
        f"({ROLE_TITLE[role]})."
    )


# --- End of game -------------------------------------------------------

def game_over(winner: Winner) -> str:
    if winner is Winner.MAFIA:
        return "🏆 <b>Игра окончена!</b>\n\n🔴 <b>Победа мафии!</b> Город пал."
    if winner is Winner.CITY:
        return "🏆 <b>Игра окончена!</b>\n\n🟢 <b>Победа города!</b> Вся мафия уничтожена."
    return "🤝 <b>Игра завершена.</b>"


# --- Stats -------------------------------------------------------------

def stats_text(stats: UserStats | None) -> str:
    if stats is None:
        return "У тебя пока нет сыгранных игр."
    winrate = (
        f"{(stats.wins / stats.games_played * 100):.0f}%"
        if stats.games_played
        else "—"
    )
    return (
        f"📊 <b>Твоя статистика</b>\n\n"
        f"Игр сыграно: <b>{stats.games_played}</b>\n"
        f"Побед: <b>{stats.wins}</b>\n"
        f"Поражений: <b>{stats.losses}</b>\n"
        f"Винрейт: <b>{winrate}</b>"
    )


# --- Helpers -----------------------------------------------------------

def player_names(session: GameSession, *, alive_only: bool = False) -> list[str]:
    players = session.alive_players if alive_only else list(session.players.values())
    return [p.full_name for p in players]
