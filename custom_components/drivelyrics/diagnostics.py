"""Diagnostics: the link's settings and status, with the token redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from . import DriveLyricsConfigEntry

TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DriveLyricsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    bridge = entry.runtime_data
    player = hass.states.get(bridge.player)
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "status": asdict(bridge.status),
        "read_limit": {
            "per_hour": bridge.limiter.per_hour,
            "per_month": bridge.limiter.per_month,
            "capacity": bridge.limiter.capacity,
            **bridge.limiter.as_dict(),
        },
        "player": {
            "state": player.state if player else None,
            "attributes": sorted(player.attributes) if player else None,
            "last_reported": player.last_reported.isoformat() if player else None,
        },
    }
