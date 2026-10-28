"""Binary sensors: is the link up, is a DriveLyrics screen open."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DriveLyricsConfigEntry
from .bridge import BridgeStatus
from .entity import DriveLyricsEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DriveLyricsBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a DriveLyrics binary sensor."""

    is_on_fn: Callable[[BridgeStatus], bool]


BINARY_SENSORS: tuple[DriveLyricsBinarySensorDescription, ...] = (
    DriveLyricsBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda status: status.connected,
    ),
    DriveLyricsBinarySensorDescription(
        key="watching",
        translation_key="watching",
        is_on_fn=lambda status: status.watching,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DriveLyricsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_add_entities(
        DriveLyricsBinarySensor(entry, description) for description in BINARY_SENSORS
    )


class DriveLyricsBinarySensor(DriveLyricsEntity, BinarySensorEntity):
    """A DriveLyrics binary sensor."""

    entity_description: DriveLyricsBinarySensorDescription

    @property
    def is_on(self) -> bool:
        """Return the state."""
        return self.entity_description.is_on_fn(self.bridge.status)
