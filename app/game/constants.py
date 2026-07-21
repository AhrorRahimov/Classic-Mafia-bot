"""Game-level constants: timings, limits, role copy."""
from __future__ import annotations

from app.game.enums import Role

# --- Lobby size ---
MIN_PLAYERS = 4
MAX_PLAYERS = 10

# --- Phase timings (seconds) ---
NIGHT_DURATION = 45
DAY_DISCUSSION_DURATION = 60
DAY_VOTE_DURATION = 60

# --- Callback data limits ---
MAX_INLINE_BUTTON_LABEL = 64  # Telegram inline button text limit


# --- Role presentation copy ---
ROLE_TITLE: dict[Role, str] = {
    Role.CITIZEN: "🟢 Житель",
    Role.MAFIA: "🔴 Мафия",
    Role.DETECTIVE: "🔵 Детектив",
    Role.DOCTOR: "🟡 Доктор",
}

ROLE_DESCRIPTION: dict[Role, str] = {
    Role.CITIZEN:
        "Ты — обычный житель города. Днём ты участвуешь в обсуждении "
        "и голосуешь за того, кого подозреваешь в мафии. "
        "Ваша цель — вычислить и обезвредить всю мафию.",
    Role.MAFIA:
        "Ты — мафия. Каждую ночь вы выбираете жертву для убийства. "
        "Ваша цель — уничтожить всех мирных жителей, чтобы стать "
        "сильнее города. Днём притворяйся обычным жителем!",
    Role.DETECTIVE:
        "Ты — детектив. Каждую ночь ты можешь проверить одного игрока "
        "и узнать, мафия он или нет. Используй информацию аккуратно, "
        "не раскрыв себя раньше времени. Твоя цель — помочь городу.",
    Role.DOCTOR:
        "Ты — доктор. Каждую ночь ты выбираешь игрока для спасения. "
        "Если на него покушается мафия — он выживет. "
        "Ты не можешь лечить одного и того же игрока два раза подряд.",
}


def role_text(role: Role) -> str:
    """Return combined title + description for a role."""
    return (
        f"<b>{ROLE_TITLE[role]}</b>\n\n"
        f"{ROLE_DESCRIPTION[role]}\n\n"
        f"<i>Никому не сообщай свою роль сам — иначе проиграешь!</i>"
    )
