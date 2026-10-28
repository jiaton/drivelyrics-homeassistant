"""What a media player's state means in DriveLyrics' push format (contract v1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_ALBUM_NAME,
    ATTR_MEDIA_ARTIST,
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_POSITION_UPDATED_AT,
    ATTR_MEDIA_TITLE,
    MediaPlayerState,
)
from homeassistant.core import State

_TEXT_LIMIT = 300  # the server refuses longer fields
_SOURCE_LIMIT = 40


def build_payload(state: State | None, fetch_id: str | None = None) -> dict[str, Any]:
    """The push body for a media player's current state."""
    payload: dict[str, Any] = {"playing": False}
    if fetch_id:
        payload["fetch_id"] = fetch_id
    if state is None:
        return payload
    attrs = state.attributes
    title = _text(attrs.get(ATTR_MEDIA_TITLE))
    payload |= {
        # Playing with nothing to look up (a radio stream without metadata, say)
        # is "nothing to show", not an error.
        "playing": state.state == MediaPlayerState.PLAYING and title is not None,
        "title": title,
        "artist": _text(attrs.get(ATTR_MEDIA_ARTIST)),
        "album": _text(attrs.get(ATTR_MEDIA_ALBUM_NAME)),
        "duration_ms": _ms(attrs.get(ATTR_MEDIA_DURATION)),
        "position_ms": _ms(attrs.get(ATTR_MEDIA_POSITION)),
        "measured_at": _measured_at(state),
        "source": _text(attrs.get(ATTR_INPUT_SOURCE), _SOURCE_LIMIT),
    }
    return {key: value for key, value in payload.items() if value is not None}


def track_key(state: State | None) -> tuple[Any, ...]:
    """What a push-worthy change is: another track, or playing ↔ paused. Position
    moves all the time and is not one.
    """
    payload = build_payload(state)
    return tuple(payload.get(k) for k in ("playing", "title", "artist", "album", "duration_ms"))


def _text(value: Any, limit: int = _TEXT_LIMIT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _ms(seconds: Any) -> int | None:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    return round(value * 1000) if 0 <= value <= 86_400 else None


def _measured_at(state: State) -> int:
    """When the position was read. Players that report it say so; others (Tesla Fleet)
    don't, and then it's when Home Assistant last received the state.
    """
    updated = state.attributes.get(ATTR_MEDIA_POSITION_UPDATED_AT)
    if isinstance(updated, datetime):
        return round(updated.timestamp() * 1000)
    return round(state.last_reported.timestamp() * 1000)
