"""DriveLyrics: synced lyrics on a car's screen for what a Home Assistant media player plays."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import DriveLyricsAuthError, DriveLyricsClient, DriveLyricsError
from .bridge import DriveLyricsBridge
from .const import (
    CONF_MONTHLY_READS,
    CONF_PLAYER,
    CONF_PUSH_ON_CHANGE,
    CONF_READS_PER_HOUR,
    CONF_REFRESH,
    CONF_SERVER,
    DEFAULT_MONTHLY_READS,
    DEFAULT_PUSH_ON_CHANGE,
    DEFAULT_READS_PER_HOUR,
    DEFAULT_REFRESH,
    DOMAIN,
    ISSUE_FEED_NOT_SELECTED,
    ISSUE_READ_LIMIT_HOURLY,
    ISSUE_READ_LIMIT_MONTHLY,
    LOGGER,
    STORAGE_VERSION,
)
from .limits import ReadLimiter

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type DriveLyricsConfigEntry = ConfigEntry[DriveLyricsBridge]


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    """Where this link's read limit state is kept across restarts."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


async def async_setup_entry(hass: HomeAssistant, entry: DriveLyricsConfigEntry) -> bool:
    """Set up DriveLyrics from a config entry."""
    client = DriveLyricsClient(
        async_get_clientsession(hass), entry.data[CONF_SERVER], entry.data[CONF_TOKEN]
    )
    try:
        await client.me()
    except DriveLyricsAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except DriveLyricsError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    store = _store(hass, entry)
    limiter = ReadLimiter.restore(
        int(entry.options.get(CONF_READS_PER_HOUR, DEFAULT_READS_PER_HOUR)),
        int(entry.options.get(CONF_MONTHLY_READS, DEFAULT_MONTHLY_READS)),
        await store.async_load(),
    )
    bridge = DriveLyricsBridge(
        hass,
        entry,
        client,
        entry.data[CONF_PLAYER],
        refresh=entry.options.get(CONF_REFRESH, DEFAULT_REFRESH),
        push_on_change=entry.options.get(CONF_PUSH_ON_CHANGE, DEFAULT_PUSH_ON_CHANGE),
        limiter=limiter,
        store=store,
    )
    entry.runtime_data = bridge
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    bridge.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DriveLyricsConfigEntry) -> bool:
    """Unload a config entry; the event stream task ends with it."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_save()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: DriveLyricsConfigEntry) -> None:
    """Removing the integration also removes its key in DriveLyrics' settings."""
    client = DriveLyricsClient(
        async_get_clientsession(hass), entry.data[CONF_SERVER], entry.data[CONF_TOKEN]
    )
    try:
        await client.forget()
    except DriveLyricsError as err:
        LOGGER.warning(
            "Could not remove this link's key in DriveLyrics (%s); remove it in"
            " DriveLyrics under Settings → Now-playing feed",
            err,
        )
    await _store(hass, entry).async_remove()
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_READ_LIMIT_HOURLY}_{entry.entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_READ_LIMIT_MONTHLY}_{entry.entry_id}")
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_FEED_NOT_SELECTED)
