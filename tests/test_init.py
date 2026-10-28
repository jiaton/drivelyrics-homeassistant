"""Setup, the event stream, answering fetches, entities, repairs."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.drivelyrics.api import DriveLyricsConnectionError, Event, Me
from custom_components.drivelyrics.const import (
    CONF_PUSH_ON_CHANGE,
    CONF_REFRESH,
    DOMAIN,
    ISSUE_FEED_NOT_SELECTED,
)
from custom_components.drivelyrics.diagnostics import async_get_config_entry_diagnostics
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir

from .conftest import PLAYER, FakeClient, unauthorized

PLAYING = {
    "media_title": "轉眼",
    "media_artist": "Mayday",
    "media_duration": 367,
    "media_position": 16,
    "source": "Spotify",
}


def fetch(fetch_id: str, reason: str = "opened") -> Event:
    return Event("fetch", {"type": "fetch", "id": fetch_id, "reason": reason, "at": 1})


@pytest.fixture
def refreshes(hass: HomeAssistant) -> list[ServiceCall]:
    """homeassistant.update_entity, standing in for a car integration: each refresh
    makes the player report its (next) state."""
    calls: list[ServiceCall] = []

    async def update_entity(call: ServiceCall) -> None:
        calls.append(call)
        state = hass.states.get(PLAYER)
        position = (state.attributes.get("media_position", 0) if state else 0) + 10
        hass.states.async_set(
            PLAYER, "playing", PLAYING | {"media_position": position}, force_update=True
        )

    hass.services.async_register("homeassistant", "update_entity", update_entity)
    return calls


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_fetch_refreshes_the_player_and_pushes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    refreshes: list[ServiceCall],
) -> None:
    hass.states.async_set(PLAYER, "paused", {"media_title": ""})
    await setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    fake_client.events_queue.put_nowait(fetch("k1"))
    pushed = await fake_client.next_push()
    assert len(refreshes) == 1 and refreshes[0].data["entity_id"] == PLAYER
    assert (
        pushed["fetch_id"] == "k1" and pushed["title"] == "轉眼" and pushed["position_ms"] == 10_000
    )

    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.drivelyrics_car_connection").state == "on"
    assert hass.states.get("binary_sensor.drivelyrics_car_screen_open").state == "on"
    assert hass.states.get("sensor.drivelyrics_car_now_showing").state == "轉眼"
    assert hass.states.get("sensor.drivelyrics_car_last_request_reason").state == "opened"

    fake_client.events_queue.put_nowait(Event("stop", {"type": "stop", "at": 2}))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.drivelyrics_car_screen_open").state == "off"


async def test_without_refresh_the_current_state_is_pushed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    refreshes: list[ServiceCall],
) -> None:
    hass.config_entries.async_update_entry(config_entry, options={CONF_REFRESH: False})
    hass.states.async_set(PLAYER, "playing", PLAYING)
    await setup(hass, config_entry)
    fake_client.events_queue.put_nowait(fetch("k1"))
    assert (await fake_client.next_push())["position_ms"] == 16_000
    assert refreshes == []


async def test_fetches_during_an_answer_are_answered_once_more(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    gate = asyncio.Event()
    refreshed: list[ServiceCall] = []

    async def slow_update_entity(call: ServiceCall) -> None:  # a car taking its time
        refreshed.append(call)
        await gate.wait()
        hass.states.async_set(PLAYER, "playing", PLAYING, force_update=True)

    hass.services.async_register("homeassistant", "update_entity", slow_update_entity)
    hass.states.async_set(PLAYER, "playing", PLAYING)
    await setup(hass, config_entry)
    for fetch_id in ("a", "b", "c"):
        fake_client.events_queue.put_nowait(fetch(fetch_id))
    await hass.async_block_till_done(wait_background_tasks=False)
    for _ in range(20):
        await asyncio.sleep(0)
    gate.set()
    await fake_client.next_push()
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(fake_client.pushes) == 2:
            break
    # "a" was being answered when "b" and "c" arrived: one more answer, for the latest.
    assert [p["fetch_id"] for p in fake_client.pushes] == ["a", "c"]
    assert len(refreshed) == 2


async def test_track_changes_are_pushed_while_watched(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_REFRESH: False, CONF_PUSH_ON_CHANGE: True}
    )
    debounce = patch("custom_components.drivelyrics.bridge.CHANGE_DEBOUNCE", 0.05)
    debounce.start()
    hass.states.async_set(PLAYER, "playing", PLAYING)
    await setup(hass, config_entry)

    hass.states.async_set(PLAYER, "playing", PLAYING | {"media_title": "Not watched yet"})
    await hass.async_block_till_done()
    assert fake_client.pushes == []

    fake_client.events_queue.put_nowait(fetch("k1"))
    await fake_client.next_push()
    hass.states.async_set(
        PLAYER, "playing", PLAYING | {"media_title": "Next song", "media_position": 0}
    )
    hass.states.async_set(
        PLAYER, "playing", PLAYING | {"media_title": "Next song", "media_position": 1}
    )
    await asyncio.sleep(0.1)
    pushed = await fake_client.next_push()
    assert pushed["title"] == "Next song" and "fetch_id" not in pushed
    assert len(fake_client.pushes) == 2  # debounced: one push for the change

    # Only the position moved: nothing to push.
    hass.states.async_set(
        PLAYER, "playing", PLAYING | {"media_title": "Next song", "media_position": 30}
    )
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert len(fake_client.pushes) == 2
    debounce.stop()


async def test_revoked_link_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    await setup(hass, config_entry)
    fake_client.events_queue.put_nowait(unauthorized())
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_setup_with_a_revoked_link_asks_to_relink(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.me_result = unauthorized()
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    await hass.async_block_till_done()
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.me_result = DriveLyricsConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_reconnects_after_a_dropped_stream(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    with patch("custom_components.drivelyrics.bridge.RECONNECT_MIN", 0.01):
        await setup(hass, config_entry)
        fake_client.events_queue.put_nowait(fetch("k1"))
        await fake_client.next_push()
        fake_client.events_queue.put_nowait(DriveLyricsConnectionError("reset"))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if fake_client.connections == 2:
                break
        assert fake_client.connections == 2
        fake_client.events_queue.put_nowait(fetch("k2"))
        assert (await fake_client.next_push())["fetch_id"] == "k2"
        await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.drivelyrics_car_connection").state == "on"


async def test_repair_issue_while_the_feed_is_not_shown(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.me_result = Me(token_name="Home Assistant", feed_selected=False)
    await setup(hass, config_entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FEED_NOT_SELECTED)


async def test_unload_stops_everything(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    await setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redact_the_token(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    hass.states.async_set(PLAYER, "playing", PLAYING)
    await setup(hass, config_entry)
    diagnostics: dict[str, Any] = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["entry"]["data"]["token"] == "**REDACTED**"
    assert "dlf_test" not in str(diagnostics)


async def test_removing_the_entry_revokes_its_token(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    await setup(hass, config_entry)
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert fake_client.forgotten
