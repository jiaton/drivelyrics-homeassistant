"""Fixtures for DriveLyrics tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.drivelyrics.api import DriveLyricsAuthError, Event, Me
from custom_components.drivelyrics.const import CONF_PLAYER, CONF_SERVER, DOMAIN
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

PLAYER = "media_player.car"
SERVER = "https://drivelyrics.example"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


class FakeClient:
    """DriveLyrics at the port boundary: events are fed by the test, pushes recorded."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.server = SERVER
        self.events_queue: asyncio.Queue[Event | Exception | None] = asyncio.Queue()
        self.pushes: list[dict[str, Any]] = []
        self.pushed = asyncio.Event()
        self.me_result: Me | Exception = Me(token_name="Home Assistant", feed_selected=True)
        self.watching = True
        self.connections = 0
        self.forgotten = False

    async def me(self) -> Me:
        if isinstance(self.me_result, Exception):
            raise self.me_result
        return self.me_result

    async def forget(self) -> None:
        self.forgotten = True

    async def push(self, payload: dict[str, Any]) -> bool:
        self.pushes.append(payload)
        self.pushed.set()
        return self.watching

    async def events(self, on_open: Any = None) -> AsyncIterator[Event]:
        self.connections += 1
        if on_open is not None:
            on_open()
        while True:
            item = await self.events_queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def next_push(self) -> dict[str, Any]:
        for _ in range(500):
            if self.pushed.is_set():
                break
            await asyncio.sleep(0)
        assert self.pushed.is_set(), f"no push; pushes so far: {self.pushes}"
        self.pushed.clear()
        return self.pushes[-1]


@pytest.fixture
def fake_client() -> FakeClient:
    """One FakeClient, used by setup."""
    client = FakeClient()
    with patch("custom_components.drivelyrics.DriveLyricsClient", return_value=client):
        yield client


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A linked entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Car",
        unique_id=PLAYER,
        data={CONF_SERVER: SERVER, CONF_PLAYER: PLAYER, CONF_TOKEN: "dlf_test"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def core(hass: HomeAssistant) -> None:
    """homeassistant.update_entity and friends."""
    assert await async_setup_component(hass, "homeassistant", {})


def unauthorized() -> DriveLyricsAuthError:
    return DriveLyricsAuthError("revoked")
