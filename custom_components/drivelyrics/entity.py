"""Base entity: everything belongs to one DriveLyrics service device per link."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from . import DriveLyricsConfigEntry
from .bridge import DriveLyricsBridge
from .const import DOMAIN


class DriveLyricsEntity(Entity):
    """Shows part of a bridge's status; updates when it changes (pushed, no polling)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: DriveLyricsConfigEntry, description: EntityDescription) -> None:
        """Initialize."""
        self.bridge: DriveLyricsBridge = entry.runtime_data
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"DriveLyrics ({entry.title})",
            manufacturer="DriveLyrics",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{self.bridge.client.server}/feed",
        )

    async def async_added_to_hass(self) -> None:
        """Follow the bridge's status."""
        self.async_on_remove(self.bridge.async_add_listener(self.async_write_ha_state))
