"""Client for DriveLyrics' now-playing feed, contract v1.

https://github.com/jiaton/drivelyrics/blob/main/docs/feed.md

No Home Assistant imports: this module only speaks HTTP, so it can be tested (and one
day published) on its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import json
from typing import Any

import aiohttp

DEFAULT_SERVER = "https://drivelyrics.com"

# The server sends a keep-alive comment every 15 s; three missed ones mean the
# connection is dead even if TCP hasn't noticed.
_EVENTS_READ_TIMEOUT = 45
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class DriveLyricsError(Exception):
    """Base error."""


class DriveLyricsConnectionError(DriveLyricsError):
    """DriveLyrics could not be reached, or answered with a server error."""


class DriveLyricsAuthError(DriveLyricsError):
    """The token is unknown or was revoked (HTTP 401)."""


class DriveLyricsRateLimitedError(DriveLyricsError):
    """Too many requests or connections (HTTP 429)."""


@dataclass(frozen=True, slots=True)
class LinkStarted:
    """A pending link: show `code` and `verify_url` to the user, poll with the secret."""

    code: str
    verify_url: str
    poll_secret: str
    interval: int
    expires_in: int


@dataclass(frozen=True, slots=True)
class Me:
    """What a token is."""

    token_name: str
    feed_selected: bool


@dataclass(frozen=True, slots=True)
class Event:
    """One event from the event stream: `fetch`, `stop`, `ping`, or a newer type."""

    type: str
    data: dict[str, Any]


class DriveLyricsClient:
    """One account's feed. `token` may be None while linking."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        server: str = DEFAULT_SERVER,
        token: str | None = None,
    ) -> None:
        """Initialize."""
        self._session = session
        self._server = server.rstrip("/")
        self._token = token

    @property
    def server(self) -> str:
        """The DriveLyrics server this client talks to."""
        return self._server

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def _request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self._server}{path}",
                json=json_body,
                headers=self._headers(),
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                _raise_for_status(resp)
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DriveLyricsConnectionError(str(err) or type(err).__name__) from err

    async def link_start(self, client_name: str) -> LinkStarted:
        """Ask for a link code (no token needed)."""
        body = await self._request("POST", "/api/feed/v1/link", {"client_name": client_name})
        return LinkStarted(
            code=body["code"],
            verify_url=body["verify_url"],
            poll_secret=body["poll_secret"],
            interval=int(body["interval_s"]),
            expires_in=int(body["expires_in_s"]),
        )

    async def link_poll(self, poll_secret: str) -> tuple[str, str | None]:
        """(status, token): pending, approved (with the token, handed out once),
        denied or expired.
        """
        body = await self._request("POST", "/api/feed/v1/link/poll", {"poll_secret": poll_secret})
        return body["status"], body.get("token")

    async def me(self) -> Me:
        """Check the token; raises DriveLyricsAuthError when it is no good."""
        body = await self._request("GET", "/api/feed/v1/me")
        return Me(
            token_name=body.get("token_name", ""),
            feed_selected=bool(body.get("feed_selected")),
        )

    async def forget(self) -> None:
        """Revoke this client's token (the integration is being removed)."""
        await self._request("DELETE", "/api/feed/v1/me")

    async def push(self, payload: dict[str, Any]) -> bool:
        """Push what is playing. Returns whether a DriveLyrics screen is open."""
        body = await self._request("POST", "/api/feed/v1/now-playing", payload)
        return bool(body.get("watching"))

    async def events(self, on_open: Callable[[], None] | None = None) -> AsyncIterator[Event]:
        """The event stream, until it ends or fails (raises; the caller reconnects)."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=_EVENTS_READ_TIMEOUT)
        headers = self._headers() | {"Accept": "text/event-stream"}
        try:
            async with self._session.get(
                f"{self._server}/api/feed/v1/events", headers=headers, timeout=timeout
            ) as resp:
                _raise_for_status(resp)
                if on_open is not None:
                    on_open()  # events only come when needed; the stream is up now
                parser = SseParser()
                async for line in resp.content:
                    if (event := parser.feed(line.decode("utf-8", "replace"))) is not None:
                        yield event
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DriveLyricsConnectionError(str(err) or type(err).__name__) from err


def _raise_for_status(resp: aiohttp.ClientResponse) -> None:
    if resp.status == 401:
        raise DriveLyricsAuthError("token unknown or revoked")
    if resp.status == 429:
        raise DriveLyricsRateLimitedError("too many requests")
    if resp.status >= 400:
        raise DriveLyricsConnectionError(f"HTTP {resp.status}")


class SseParser:
    """Server-Sent Events, one line at a time (https://html.spec.whatwg.org/#parsing-an-event-stream).

    Only what the feed uses: `event` and `data` fields; comments are keep-alives.
    """

    def __init__(self) -> None:
        """Initialize."""
        self._event = ""
        self._data: list[str] = []

    def feed(self, line: str) -> Event | None:
        """Take one line; return an event when a blank line completes one."""
        line = line.rstrip("\r\n")
        if not line:
            return self._dispatch()
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            self._event = value
        elif name == "data":
            self._data.append(value)
        return None

    def _dispatch(self) -> Event | None:
        event_type, data = self._event, "\n".join(self._data)
        self._event, self._data = "", []
        if not data:
            return None
        try:
            parsed = json.loads(data)
        except ValueError:
            return None
        if not isinstance(parsed, dict):
            return None
        return Event(type=event_type or str(parsed.get("type", "message")), data=parsed)
