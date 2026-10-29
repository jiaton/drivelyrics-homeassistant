"""Media player state → push body."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.drivelyrics.payload import build_payload, track_key
from homeassistant.core import State

TESLA = {
    "media_title": "轉眼",
    "media_artist": "Mayday",
    "media_album_name": "自傳",
    "media_duration": 367,
    "media_position": 16,
    "source": "Spotify",
}


def test_tesla_fleet_player() -> None:
    state = State("media_player.car", "playing", TESLA)
    payload = build_payload(state, "f1")
    assert payload == {
        "playing": True,
        "title": "轉眼",
        "artist": "Mayday",
        "album": "自傳",
        "duration_ms": 367_000,
        "position_ms": 16_000,
        "measured_at": round(state.last_reported.timestamp() * 1000) - 700,  # car's lag
        "source": "Spotify",
        "fetch_id": "f1",
    }


def test_position_updated_at_is_preferred() -> None:
    at = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)
    state = State("media_player.sonos", "playing", TESLA | {"media_position_updated_at": at})
    assert build_payload(state)["measured_at"] == round(at.timestamp() * 1000)


def test_nothing_to_show() -> None:
    assert build_payload(None, "f") == {"playing": False, "fetch_id": "f"}
    assert build_payload(State("media_player.car", "unavailable")) == {
        "playing": False,
        "measured_at": build_payload(State("media_player.car", "unavailable"))["measured_at"],
    }
    # Paused with empty strings (what Tesla Fleet reports when idle).
    idle = build_payload(
        State("media_player.car", "paused", {"media_title": "", "media_duration": 262})
    )
    assert idle["playing"] is False and "title" not in idle
    # Playing a stream without a title: nothing DriveLyrics could look up.
    assert (
        build_payload(State("media_player.radio", "playing", {"media_title": " "}))["playing"]
        is False
    )


def test_odd_values_are_dropped_or_clipped() -> None:
    state = State(
        "media_player.x",
        "playing",
        {"media_title": "t" * 500, "media_duration": "n/a", "media_position": -5},
    )
    payload = build_payload(state)
    assert (
        len(payload["title"]) == 300
        and "duration_ms" not in payload
        and "position_ms" not in payload
    )


def test_track_key_ignores_position() -> None:
    a = State("media_player.car", "playing", TESLA)
    b = State("media_player.car", "playing", TESLA | {"media_position": 100})
    c = State("media_player.car", "paused", TESLA)
    assert track_key(a) == track_key(b) != track_key(c)
