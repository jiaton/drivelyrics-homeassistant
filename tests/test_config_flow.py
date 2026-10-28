"""Config flow: choose the player, link by approval, reauth, reconfigure, options."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.drivelyrics.api import DriveLyricsConnectionError, LinkStarted
from custom_components.drivelyrics.const import (
    CONF_MONTHLY_READS,
    CONF_PLAYER,
    CONF_PUSH_ON_CHANGE,
    CONF_READS_PER_HOUR,
    CONF_REFRESH,
    CONF_SERVER,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from .conftest import PLAYER

LINK = LinkStarted(
    code="ABCD-EFGH",
    verify_url="https://drivelyrics.com/link?code=ABCDEFGH",
    poll_secret="s",
    interval=0,
    expires_in=60,
)


@pytest.fixture
def link_client() -> AsyncMock:
    """The client the flow talks to: approves on the second poll."""
    client = AsyncMock()
    client.link_start.return_value = LINK
    client.link_poll.side_effect = [("pending", None), ("approved", "dlf_new")]
    with patch("custom_components.drivelyrics.config_flow.DriveLyricsClient", return_value=client):
        yield client


@pytest.fixture(autouse=True)
def no_setup() -> None:
    """Creating an entry doesn't start the integration in these tests."""
    with patch("custom_components.drivelyrics.async_setup_entry", return_value=True):
        yield


async def _until_done(hass: HomeAssistant, flow_id: str) -> dict[str, Any]:
    """Let the poll finish, then do what the frontend does when the progress ends."""
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(flow_id)


async def test_user_links_by_approval(hass: HomeAssistant, link_client: AsyncMock) -> None:
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Car"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: PLAYER}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "wait_for_approval"
    assert result["description_placeholders"] == {"url": LINK.verify_url, "code": "ABCD-EFGH"}
    link_client.link_start.assert_awaited_once_with("Home Assistant")

    result = await _until_done(hass, result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Car"
    assert result["data"] == {
        CONF_SERVER: "https://drivelyrics.com",
        CONF_PLAYER: PLAYER,
        CONF_TOKEN: "dlf_new",
    }
    assert result["result"].unique_id == PLAYER


@pytest.mark.parametrize(
    ("status", "reason"), [("denied", "link_denied"), ("expired", "link_expired")]
)
async def test_link_not_approved(
    hass: HomeAssistant, link_client: AsyncMock, status: str, reason: str
) -> None:
    link_client.link_poll.side_effect = [(status, None)]
    hass.states.async_set(PLAYER, "idle")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: PLAYER}
    )
    result = await _until_done(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT and result["reason"] == reason


async def test_unreachable(hass: HomeAssistant, link_client: AsyncMock) -> None:
    link_client.link_start.side_effect = DriveLyricsConnectionError("down")
    hass.states.async_set(PLAYER, "idle")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: PLAYER}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "cannot_connect"


async def test_player_already_linked(
    hass: HomeAssistant, link_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    hass.states.async_set(PLAYER, "idle")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: PLAYER}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    link_client.link_start.assert_not_called()  # no token is made for nothing


async def test_turns_on_a_disabled_car_player(hass: HomeAssistant, link_client: AsyncMock) -> None:
    car_integration = MockConfigEntry(domain="tesla_fleet")
    car_integration.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "media_player",
        "tesla_fleet",
        "vin-media",
        config_entry=car_integration,
        suggested_object_id="car_media_player",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "enable_player"

    with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PLAYER: entity.entity_id}
        )
    assert registry.async_get(entity.entity_id).disabled_by is None
    reload.assert_awaited_once_with(car_integration.entry_id)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    result = await _until_done(hass, result["flow_id"])
    assert result["data"][CONF_PLAYER] == entity.entity_id


async def test_reauth_links_again(
    hass: HomeAssistant, link_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    result = await _until_done(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == "dlf_new" and config_entry.data[CONF_PLAYER] == PLAYER


async def test_reconfigure_another_player(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    hass.states.async_set("media_player.kitchen", "idle", {"friendly_name": "Kitchen"})
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: "media_player.kitchen"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    assert (
        config_entry.data[CONF_PLAYER] == "media_player.kitchen"
        and config_entry.unique_id == "media_player.kitchen"
    )
    assert config_entry.data[CONF_TOKEN] == "dlf_test"  # same link


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_REFRESH: False, CONF_PUSH_ON_CHANGE: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_REFRESH: False,
        CONF_PUSH_ON_CHANGE: True,
        CONF_READS_PER_HOUR: 60,
        CONF_MONTHLY_READS: 3000,
    }

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_REFRESH: True,
            CONF_PUSH_ON_CHANGE: True,
            CONF_READS_PER_HOUR: 30.0,
            CONF_MONTHLY_READS: 600.0,
        },
    )
    assert config_entry.options[CONF_READS_PER_HOUR] == 30  # stored as whole numbers
    assert config_entry.options[CONF_MONTHLY_READS] == 600


async def test_declining_to_enable_lets_you_pick_another(
    hass: HomeAssistant, link_client: AsyncMock
) -> None:
    car_integration = MockConfigEntry(domain="tesla_fleet")
    car_integration.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "media_player",
        "tesla_fleet",
        "vin-media",
        config_entry=car_integration,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    hass.states.async_set("media_player.kitchen", "idle")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: "other"}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: "media_player.kitchen"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS


async def test_self_hosted_server_in_advanced_mode(
    hass: HomeAssistant, link_client: AsyncMock
) -> None:
    hass.states.async_set(PLAYER, "idle")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER, "show_advanced_options": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYER: PLAYER, CONF_SERVER: "https://lyrics.example.org/"}
    )
    result = await _until_done(hass, result["flow_id"])
    assert result["data"][CONF_SERVER] == "https://lyrics.example.org"
