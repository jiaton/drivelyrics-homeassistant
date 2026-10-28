"""The HTTP client and the event-stream parser."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.drivelyrics.api import (
    DriveLyricsAuthError,
    DriveLyricsClient,
    DriveLyricsConnectionError,
    DriveLyricsRateLimitedError,
    SseParser,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import SERVER


def parse(text: str) -> list:
    parser = SseParser()
    return [event for line in text.splitlines(keepends=True) if (event := parser.feed(line))]


def test_sse_events_comments_and_multiline_data() -> None:
    events = parse(
        ": ping\r\n\r\n"
        'event: fetch\r\ndata: {"type": "fetch", "id": "a", "reason": "opened"}\r\n\r\n'
        'event: stop\ndata: {"type":\n'
        'data: "stop"}\n\n'
        "data: not json\n\n"
        'data: {"type": "ping", "id": "p"}\n\n'
    )
    assert [(e.type, e.data.get("id")) for e in events] == [
        ("fetch", "a"),
        ("stop", None),
        ("ping", "p"),
    ]


async def test_requests_and_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{SERVER}/api/feed/v1/link",
        json={
            "code": "ABCD-EFGH",
            "verify_url": f"{SERVER}/link?code=ABCDEFGH",
            "poll_secret": "s",
            "interval_s": 3,
            "expires_in_s": 600,
        },
    )
    aioclient_mock.post(
        f"{SERVER}/api/feed/v1/now-playing", json={"watching": True, "next_fetch_in_ms": None}
    )
    aioclient_mock.get(f"{SERVER}/api/feed/v1/me", status=401)
    client = DriveLyricsClient(async_get_clientsession(hass), SERVER + "/", "dlf_x")

    link = await client.link_start("Home Assistant")
    assert (link.code, link.interval, link.expires_in) == ("ABCD-EFGH", 3, 600)
    assert await client.push({"playing": False}) is True
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer dlf_x"
    with pytest.raises(DriveLyricsAuthError):
        await client.me()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"status": 429}, DriveLyricsRateLimitedError),
        ({"status": 502}, DriveLyricsConnectionError),
        ({"exc": TimeoutError()}, DriveLyricsConnectionError),
    ],
)
async def test_failures_map_to_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, kwargs, error
) -> None:
    aioclient_mock.post(f"{SERVER}/api/feed/v1/now-playing", **kwargs)
    with pytest.raises(error):
        await DriveLyricsClient(async_get_clientsession(hass), SERVER, "dlf_x").push(
            {"playing": False}
        )


async def test_event_stream(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{SERVER}/api/feed/v1/events",
        text=': keep-alive\n\nevent: fetch\ndata: {"type": "fetch", "id": "k3", "reason": "refresh", "at": 1}\n\n',
    )
    client = DriveLyricsClient(async_get_clientsession(hass), SERVER, "dlf_x")
    events = [event async for event in client.events()]
    assert [(e.type, e.data["id"]) for e in events] == [("fetch", "k3")]
