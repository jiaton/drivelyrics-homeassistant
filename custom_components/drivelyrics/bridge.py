"""The running link between one media player and DriveLyrics.

DriveLyrics decides when it needs to know what's playing and sends a `fetch` event;
this answers each one by reading the player once and pushing the result. The event
stream is a connection *from* Home Assistant, so nothing has to be reachable from the
internet. See docs/feed.md in the DriveLyrics repository for the contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import random
import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    CALLBACK_TYPE,
    Event as HassEvent,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    DriveLyricsAuthError,
    DriveLyricsClient,
    DriveLyricsError,
    DriveLyricsRateLimitedError,
    Event,
)
from .const import (
    CHANGE_DEBOUNCE,
    DOMAIN,
    ISSUE_FEED_NOT_SELECTED,
    ISSUE_READ_LIMIT_HOURLY,
    ISSUE_READ_LIMIT_MONTHLY,
    LOGGER,
    MAX_REFRESH_WAIT,
    RECONNECT_MAX,
    RECONNECT_MIN,
    RECONNECT_STABLE_AFTER,
)
from .limits import Limited, ReadLimiter, next_month_start
from .payload import build_payload, track_key

if TYPE_CHECKING:
    from . import DriveLyricsConfigEntry


@dataclass(slots=True)
class BridgeStatus:
    """What the entities show."""

    connected: bool = False
    watching: bool = False
    last_fetch: datetime | None = None
    last_fetch_reason: str | None = None
    last_push: datetime | None = None
    pushed_title: str | None = None
    fetches: int = 0
    read_limit: str = "ok"  # "ok" | "hourly" | "monthly"
    reads_this_month: int = 0


class DriveLyricsBridge:
    """Answers one account's fetch events with one media player's state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DriveLyricsConfigEntry,
        client: DriveLyricsClient,
        player: str,
        *,
        refresh: bool,
        push_on_change: bool,
        limiter: ReadLimiter,
        store: Store[dict[str, Any]],
        feed_hint_shown: bool,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self.player = player
        self.refresh = refresh
        self.push_on_change = push_on_change
        self.limiter = limiter
        self._store = store
        self._feed_hint_shown = feed_hint_shown
        self.status = BridgeStatus()
        self._cancel_limit_recheck: CALLBACK_TYPE | None = None
        self._cancel_month_change: CALLBACK_TYPE | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._answering: asyncio.Task[None] | None = None
        self._next_fetch_id: str | None = None
        self._last_key: tuple[Any, ...] | None = None
        self._cancel_change_push: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> None:
        """Connect and keep connected until the entry unloads."""
        self.entry.async_create_background_task(self.hass, self._run(), f"{DOMAIN} event stream")
        self.entry.async_on_unload(
            async_track_state_change_event(self.hass, [self.player], self._async_player_changed)
        )
        self.entry.async_on_unload(self._cancel_pending_change_push)
        self.entry.async_on_unload(self._cancel_limit_timers)
        self._limit_changed(self.limiter.check(time.time()) if self.refresh else None)

    async def async_save(self) -> None:
        """Store the limiter now (on unload, so a reload starts from it)."""
        await self._store.async_save(self._stored())

    def _stored(self) -> dict[str, Any]:
        return self.limiter.as_dict() | {"feed_hint_shown": self._feed_hint_shown}

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        """Call `update` whenever the status changes."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # --- The event stream ---------------------------------------------------------

    async def _run(self) -> None:
        delay = RECONNECT_MIN
        while True:
            started = time.monotonic()
            try:
                await self._check_account()
                async for event in self.client.events(on_open=self._opened):
                    self._handle(event)
                LOGGER.debug("Event stream ended")
            except DriveLyricsAuthError:
                LOGGER.warning("DriveLyrics no longer accepts this link; re-link to continue")
                self._set(connected=False, watching=False)
                self.entry.async_start_reauth(self.hass)
                return
            except DriveLyricsRateLimitedError:
                LOGGER.warning(
                    "DriveLyrics refused the connection: this account already has the"
                    " most event streams it allows open (another receiver?)"
                )
                delay = RECONNECT_MAX
            except DriveLyricsError as err:
                LOGGER.debug("Event stream failed: %s", err)
            if self.status.connected:
                LOGGER.info("Disconnected from DriveLyrics; reconnecting")
            self._set(connected=False)
            if time.monotonic() - started > RECONNECT_STABLE_AFTER:
                delay = RECONNECT_MIN
            await asyncio.sleep(delay * random.uniform(0.8, 1.2))
            delay = min(delay * 2, RECONNECT_MAX)

    @callback
    def _opened(self) -> None:
        LOGGER.info("Connected to DriveLyrics at %s", self.client.server)
        self._set(connected=True)

    async def _check_account(self) -> None:
        """Tell the user once if their screens don't show the feed. Showing Spotify
        can be on purpose, so after that first time it's theirs to choose, unsaid.
        """
        me = await self.client.me()
        if me.feed_selected:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_FEED_NOT_SELECTED)
        elif not self._feed_hint_shown:
            self._feed_hint_shown = True
            self._store.async_delay_save(self._stored, 10)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_FEED_NOT_SELECTED,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_FEED_NOT_SELECTED,
                learn_more_url=f"{self.client.server}/feed",
            )

    @callback
    def _handle(self, event: Event) -> None:
        if event.type == "fetch":
            self._set(
                watching=True,
                last_fetch=dt_util.utcnow(),
                last_fetch_reason=str(event.data.get("reason") or ""),
                fetches=self.status.fetches + 1,
            )
            self._request_answer(str(event.data.get("id") or ""))
        elif event.type == "stop":
            self._set(watching=False)
        # ping (the Test button in DriveLyrics) and future event types: nothing to do.

    # --- Answering a fetch --------------------------------------------------------

    @callback
    def _request_answer(self, fetch_id: str) -> None:
        """One answer at a time: a fetch arriving mid-answer gets a fresh one after."""
        self._next_fetch_id = fetch_id
        if self._answering is None or self._answering.done():
            self._answering = self.entry.async_create_background_task(
                self.hass, self._answer_pending(), f"{DOMAIN} answer fetch"
            )

    async def _answer_pending(self) -> None:
        while (fetch_id := self._next_fetch_id) is not None:
            self._next_fetch_id = None
            await self._answer(fetch_id)

    async def _answer(self, fetch_id: str) -> None:
        limited: Limited | None = None
        if self.refresh:
            now = time.time()
            limited = self.limiter.check(now)
            if limited is None:
                self.limiter.take(now)
                self._store.async_delay_save(self._stored, 10)
            self._limit_changed(limited)
            if limited is None:
                await self._refresh_player()
        payload = build_payload(self.hass.states.get(self.player), fetch_id)
        if limited is not None:
            # Answered with what Home Assistant already has; DriveLyrics says so on screen.
            payload["limited"] = limited
        await self._push(payload)

    async def _refresh_player(self) -> None:
        """Have the player's integration read it now (for a Tesla: one vehicle_data
        call) and wait for the new state, as long as MAX_REFRESH_WAIT.
        """
        asked = dt_util.utcnow()
        try:
            await self.hass.services.async_call(
                "homeassistant",
                "update_entity",
                {ATTR_ENTITY_ID: self.player},
                blocking=True,
            )
        except HomeAssistantError as err:
            LOGGER.debug("Refreshing %s failed: %s", self.player, err)
            return
        deadline = time.monotonic() + MAX_REFRESH_WAIT
        while time.monotonic() < deadline:
            state = self.hass.states.get(self.player)
            if state is not None and state.last_reported >= asked:
                return
            await asyncio.sleep(0.25)
        LOGGER.debug("%s did not report a new state in time", self.player)

    async def _push(self, payload: dict[str, Any]) -> None:
        try:
            watching = await self.client.push(payload)
        except DriveLyricsAuthError:
            self.entry.async_start_reauth(self.hass)
            return
        except DriveLyricsError as err:
            LOGGER.debug("Push failed: %s", err)
            return
        self._last_key = track_key(self.hass.states.get(self.player))
        self._set(
            watching=watching,
            last_push=dt_util.utcnow(),
            pushed_title=payload.get("title") if payload.get("playing") else None,
        )

    # --- Changes the player reports by itself -------------------------------------

    @callback
    def _async_player_changed(self, event: HassEvent[EventStateChangedData]) -> None:
        """Players that update on their own (unlike a car) get their track changes
        pushed straight away, while a DriveLyrics screen is open. Free: pushing costs
        nothing, only reading a car does.
        """
        if not self.push_on_change or not self.status.watching:
            return
        if track_key(event.data["new_state"]) == self._last_key:
            return
        self._schedule_change_push()

    @callback
    def _schedule_change_push(self) -> None:
        self._cancel_pending_change_push()
        self._cancel_change_push = async_call_later(
            self.hass, CHANGE_DEBOUNCE, self._async_push_change
        )

    @callback
    def _async_push_change(self, _now: datetime) -> None:
        self._cancel_change_push = None
        if self._answering is not None and not self._answering.done():
            self._schedule_change_push()  # look again once the answer is out
            return
        if track_key(self.hass.states.get(self.player)) == self._last_key:
            return  # an answer already carried it
        self.entry.async_create_background_task(
            self.hass,
            self._push(build_payload(self.hass.states.get(self.player))),
            f"{DOMAIN} push change",
        )

    @callback
    def _cancel_pending_change_push(self) -> None:
        if self._cancel_change_push is not None:
            self._cancel_change_push()
            self._cancel_change_push = None

    # --- This side's read limit ---------------------------------------------------

    @callback
    def _limit_changed(self, limited: Limited | None) -> None:
        """Show the limit's state; tell the user once per kind (not on every fetch)."""
        self._set(read_limit=limited or "ok", reads_this_month=self.limiter.month_reads)
        hourly_issue = f"{ISSUE_READ_LIMIT_HOURLY}_{self.entry.entry_id}"
        monthly_issue = f"{ISSUE_READ_LIMIT_MONTHLY}_{self.entry.entry_id}"
        if limited != "hourly":
            ir.async_delete_issue(self.hass, DOMAIN, hourly_issue)
        if limited != "monthly":
            ir.async_delete_issue(self.hass, DOMAIN, monthly_issue)
        if limited == "hourly" and self.limiter.hourly_notified_rate != self.limiter.per_hour:
            self.limiter.hourly_notified_rate = self.limiter.per_hour
            self._create_issue(hourly_issue, ISSUE_READ_LIMIT_HOURLY, self.limiter.per_hour)
        if limited == "monthly" and self.limiter.monthly_notified != self.limiter.month:
            self.limiter.monthly_notified = self.limiter.month
            self._create_issue(monthly_issue, ISSUE_READ_LIMIT_MONTHLY, self.limiter.per_month)
        if limited is not None:
            LOGGER.info(
                "Read limit (%s) reached: answering without reading %s", limited, self.player
            )
            self._store.async_delay_save(self._stored, 10)
        self._schedule_limit_timers(limited)

    @callback
    def _create_issue(self, issue_id: str, key: str, limit: int) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={"limit": str(limit), "name": self.entry.title},
        )

    @callback
    def _schedule_limit_timers(self, limited: Limited | None) -> None:
        """Look again when the bucket has a read again, and when the month turns (the
        monthly count shown resets then).
        """
        self._cancel_limit_timers()
        now = time.time()
        if limited == "hourly":
            self._cancel_limit_recheck = async_call_later(
                self.hass, self.limiter.seconds_until_token(now) + 1, self._async_recheck_limit
            )
        self._cancel_month_change = async_track_point_in_utc_time(
            self.hass, self._async_recheck_limit, next_month_start(now)
        )

    @callback
    def _async_recheck_limit(self, _now: datetime) -> None:
        self._limit_changed(self.limiter.check(time.time()) if self.refresh else None)

    @callback
    def _cancel_limit_timers(self) -> None:
        for name in ("_cancel_limit_recheck", "_cancel_month_change"):
            if (cancel := getattr(self, name)) is not None:
                cancel()
                setattr(self, name, None)

    @callback
    def _set(self, **changes: Any) -> None:
        changed = False
        for name, value in changes.items():
            if getattr(self.status, name) != value:
                setattr(self.status, name, value)
                changed = True
        if changed:
            self._notify()
