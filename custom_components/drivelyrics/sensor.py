"""Sensors: the last fetch DriveLyrics asked for, and what was pushed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DriveLyricsConfigEntry
from .bridge import BridgeStatus
from .entity import DriveLyricsEntity

PARALLEL_UPDATES = 0

FETCH_REASONS = ["opened", "track_ending", "skip_check", "paused_check", "refresh", "retry"]


@dataclass(frozen=True, kw_only=True)
class DriveLyricsSensorDescription(SensorEntityDescription):
    """Describes a DriveLyrics sensor."""

    value_fn: Callable[[BridgeStatus], datetime | str | int | None]


SENSORS: tuple[DriveLyricsSensorDescription, ...] = (
    DriveLyricsSensorDescription(
        key="pushed_title",
        translation_key="pushed_title",
        value_fn=lambda status: status.pushed_title,
    ),
    DriveLyricsSensorDescription(
        key="last_fetch",
        translation_key="last_fetch",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.last_fetch,
    ),
    DriveLyricsSensorDescription(
        key="last_fetch_reason",
        translation_key="last_fetch_reason",
        device_class=SensorDeviceClass.ENUM,
        options=FETCH_REASONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Reasons added to the contract later show as unknown until translated here.
        value_fn=lambda status: (
            status.last_fetch_reason if status.last_fetch_reason in FETCH_REASONS else None
        ),
    ),
    DriveLyricsSensorDescription(
        key="last_push",
        translation_key="last_push",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.last_push,
    ),
    DriveLyricsSensorDescription(
        key="fetches",
        translation_key="fetches",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.fetches,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DriveLyricsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(DriveLyricsSensor(entry, description) for description in SENSORS)


class DriveLyricsSensor(DriveLyricsEntity, SensorEntity):
    """A DriveLyrics sensor."""

    entity_description: DriveLyricsSensorDescription

    @property
    def native_value(self) -> datetime | str | int | None:
        """Return the state."""
        return self.entity_description.value_fn(self.bridge.status)
