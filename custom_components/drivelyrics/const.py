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

CONF_READS_PER_HOUR: Final = "reads_per_hour"
CONF_MONTHLY_READS: Final = "monthly_reads"

DEFAULT_REFRESH: Final = True
DEFAULT_PUSH_ON_CHANGE: Final = True

# This Home Assistant's own limit on reading the player (each read of a Tesla is one
# billed vehicle data request, $0.002; Tesla gives a $10 monthly credit, 5,000 reads).
# Looser than DriveLyrics' defaults (60 an hour, 800 a month), which normally stop
# first: this one is the lock on the user's own side.
DEFAULT_READS_PER_HOUR: Final = 60
DEFAULT_MONTHLY_READS: Final = 3000
# Reads allowed in a quick burst (skipping tracks, tapping refresh) out of the hourly rate.
BURST: Final = 20

STORAGE_VERSION: Final = 1

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
# Per entry: f"{ISSUE_READ_LIMIT_HOURLY}_{entry_id}"; the key is the translation key.
ISSUE_READ_LIMIT_HOURLY: Final = "read_limit_hourly"
ISSUE_READ_LIMIT_MONTHLY: Final = "read_limit_monthly"
