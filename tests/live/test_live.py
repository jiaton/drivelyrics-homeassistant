"""End to end against a real DriveLyrics server (one with DEV_LOGIN=true).

    DRIVELYRICS_E2E_URL=http://127.0.0.1:8010 pytest tests/live

Real Home Assistant core, real HTTP: link by approval, the event stream, a screen
opening, the answer reaching that screen, removal revoking the token.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import aiohttp
import pytest

from custom_components.drivelyrics.const import CONF_PLAYER, CONF_SERVER, DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType

SERVER = os.environ.get("DRIVELYRICS_E2E_URL", "")
PLAYER = "media_player.car"
PLAYING = {
    "friendly_name": "Car",
    "media_title": "Invented Song",
    "media_artist": "Nobody",
    "media_duration": 200,
    "media_position": 42,
    "source": "Spotify",
}

pytestmark = pytest.mark.skipif(not SERVER, reason="set DRIVELYRICS_E2E_URL to run")


async def _screen_events(session: aiohttp.ClientSession, events: list[dict[str, Any]]) -> None:
    """A DriveLyrics screen: the now-playing stream of the signed-in user."""
    async with session.get(
        f"{SERVER}/api/now-playing/stream", timeout=aiohttp.ClientTimeout(total=None)
    ) as resp:
        assert resp.status == 200
        async for line in resp.content:
            text = line.decode().strip()
            if text.startswith("data:"):
                events.append(json.loads(text[5:]))


async def test_live(hass: HomeAssistant, socket_enabled: None) -> None:
    refreshed: list[ServiceCall] = []

    async def update_entity(call: ServiceCall) -> None:
        refreshed.append(call)
        hass.states.async_set(PLAYER, "playing", PLAYING, force_update=True)

    hass.services.async_register("homeassistant", "update_entity", update_entity)
    hass.states.async_set(PLAYER, "paused", {"friendly_name": "Car"})

    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as user:  # IP host
        resp = await user.post(
            f"{SERVER}/api/auth/dev-login",
            json={"email": f"ha-e2e-{os.urandom(4).hex()}@example.com"},
        )
        assert resp.status == 200

        # 1. Link: the user approves the code in DriveLyrics.
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER, "show_advanced_options": True}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PLAYER: PLAYER, CONF_SERVER: SERVER}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        code = result["description_placeholders"]["code"]
        info = await (await user.get(f"{SERVER}/api/feed/link", params={"code": code})).json()
        assert info["client_name"] == "Home Assistant"
        assert (
            await user.post(f"{SERVER}/api/feed/link/approve", json={"code": code})
        ).status == 200
        await user.put(f"{SERVER}/api/now-playing/source", json={"source": "feed"})

        for _ in range(100):  # the flow polls every 3 s
            await asyncio.sleep(0.1)
            if hass.config_entries.flow.async_get(result["flow_id"])["step_id"] == "finish":
                break
        # What the frontend does when the progress ends:
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["type"] is FlowResultType.CREATE_ENTRY
        entries = hass.config_entries.async_entries(DOMAIN)
        assert len(entries) == 1
        await hass.async_block_till_done(wait_background_tasks=False)
        for _ in range(50):
            await asyncio.sleep(0.1)
            if (
                state := hass.states.get("binary_sensor.drivelyrics_car_connection")
            ) and state.state == "on":
                break
        assert hass.states.get("binary_sensor.drivelyrics_car_connection").state == "on"

        # 2. A screen opens: DriveLyrics asks, Home Assistant refreshes and answers.
        screen: list[dict[str, Any]] = []
        watcher = asyncio.create_task(_screen_events(user, screen))
        for _ in range(100):
            await asyncio.sleep(0.1)
            if any(event.get("name") == "Invented Song" for event in screen):
                break
        watcher.cancel()
        shown = [event for event in screen if event.get("name") == "Invented Song"]
        assert shown, screen
        assert shown[-1]["artist"] == "Nobody" and shown[-1]["is_playing"] is True
        assert 42_000 <= shown[-1]["progress_ms"] < 52_000
        assert len(refreshed) == 1
        assert hass.states.get("sensor.drivelyrics_car_last_request_reason").state == "opened"

        # 3. Removing the integration removes its key in DriveLyrics.
        async def token_ids() -> set[int]:
            body = await (await user.get(f"{SERVER}/api/feed/tokens")).json()
            return {token["id"] for token in body["tokens"]}

        before = await token_ids()
        assert await hass.config_entries.async_remove(entries[0].entry_id)
        await hass.async_block_till_done(wait_background_tasks=False)
        assert len(before - await token_ids()) == 1
