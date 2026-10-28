"""Constants for the DriveLyrics integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "drivelyrics"
LOGGER = logging.getLogger(__package__)

CONF_SERVER: Final = "server"
CONF_PLAYER: Final = "player"
CONF_REFRESH: Final = "refresh"
CONF_PUSH_ON_CHANGE: Final = "push_on_change"

DEFAULT_REFRESH: Final = True
DEFAULT_PUSH_ON_CHANGE: Final = True

# The token's name in DriveLyrics' settings.
CLIENT_NAME: Final = "Home Assistant"

# Integrations whose media player reads a car through a billed API: suggested first,
# and the reason "refresh before reading" is on by default.
CAR_PLATFORMS: Final = ("tesla_fleet", "teslemetry", "tessie", "tesla_custom")

# After asking the player's integration to refresh, wait at most this long for the
# new state to arrive before pushing what there is.
MAX_REFRESH_WAIT: Final = 10.0

# Reconnecting the event stream: 1 s, doubling, at most a minute (plus jitter).
RECONNECT_MIN: Final = 1.0
RECONNECT_MAX: Final = 60.0
# A connection that lasted this long resets the backoff.
RECONNECT_STABLE_AFTER: Final = 60.0

# Pushing changes the player reports on its own: wait for this quiet period so a
# track change that arrives as several state updates is pushed once.
CHANGE_DEBOUNCE: Final = 1.0

ISSUE_FEED_NOT_SELECTED: Final = "feed_not_selected"
