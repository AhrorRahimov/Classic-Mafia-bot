"""Game-level constants: timings and lobby size limits.

All user-facing role copy now lives in ``app/locales/*.json`` and is
served through the i18n layer (``app.texts.role_title``, ``your_role``).
"""
from __future__ import annotations

# --- Lobby size ---
MIN_PLAYERS = 4
MAX_PLAYERS = 10

# --- Phase timings (seconds) ---
NIGHT_DURATION = 45
DAY_DISCUSSION_DURATION = 60
DAY_VOTE_DURATION = 60

# --- Callback data limits ---
MAX_INLINE_BUTTON_LABEL = 64  # Telegram inline button text limit
