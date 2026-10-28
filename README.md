# DriveLyrics for Home Assistant

Synced lyrics on your car's screen — or any browser — for whatever a Home Assistant
media player is playing. Made for a Tesla's media player (Tesla Fleet, Teslemetry,
Tessie), works with any `media_player`.

[中文说明](README.zh-CN.md)

[DriveLyrics](https://drivelyrics.com) normally reads Spotify. With this integration it
shows lyrics for what your **car** plays instead — Spotify, Apple Music, Bluetooth,
radio — with no Spotify account needed.

## Install

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiaton&repository=drivelyrics-homeassistant&category=integration)

1. Click the button above (or in HACS: ⋮ → Custom repositories → add
   `https://github.com/jiaton/drivelyrics-homeassistant`, type Integration), then
   **Download**, and restart Home Assistant.
2. [![Add the DriveLyrics integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=drivelyrics)
   — or Settings → Devices & services → Add integration → DriveLyrics.
3. Pick the media player. (If your Tesla's media player is turned off — Tesla Fleet ships
   it that way — the integration offers to turn it on.)
4. Click **Open website**, sign in to DriveLyrics, check the code and tap **Approve**.
   Home Assistant finishes by itself.

That's all: no token to copy, no YAML, nothing exposed to the internet.

## How it works

DriveLyrics decides when it needs to know what's playing — when a DriveLyrics screen
opens, right after the current song should have ended, when you tap refresh — and asks
over a connection Home Assistant keeps open to it. Each time, the integration has the
player's integration read the car once, then sends title, artist, album, duration and
position back. When no screen is open, nothing is asked.

- **Privacy.** The integration gets its own key that can only send what's playing and
  receive update requests. Removing the integration removes the key; removing the key in
  DriveLyrics (Settings → Now-playing feed) makes Home Assistant ask you to link again.
- **Other players.** Players that report changes on their own (Sonos, Music Assistant,
  …) also get track changes sent the moment they happen while a screen is open. For those
  you can turn off "Refresh the player before each answer" in the integration's options.

## Limits and cost

For a Tesla, each answer is one Fleet API vehicle data request. Tesla bills $0.002 each
(500 per $1) and gives a $10 monthly credit (5,000 reads). With a screen open while music
plays that's about 15–20 reads an hour; with no screen open, none.

Two limits, both yours to change:

- **In DriveLyrics** (Settings → Now-playing feed): a monthly budget (default 800) and
  reads per hour. These decide when DriveLyrics asks.
- **In Home Assistant** (this integration's options): **Car reads per hour** (default 60,
  up to 20 in a quick burst for skipping and refresh) and **Car reads per month**
  (default 1,000). This is the lock on your side: whatever DriveLyrics asks, Home
  Assistant reads the car no more than this, and the defaults leave most of Tesla's
  credit for Home Assistant's own use.

When a limit is reached nothing goes quiet: DriveLyrics gets what Home Assistant already
knows (no read, no cost) and says so on screen, the **Read limit** sensor shows it, and
a repair notice tells you once (once per limit you set for the hourly one, once a month
for the monthly one), not on every request. **Car reads this month** counts every read.

## Entities

| Entity | |
|---|---|
| Screen open | A DriveLyrics screen of yours is open (handy in automations). |
| Now showing | The title last sent while playing. |
| Car reads this month | Reads of the player for DriveLyrics this calendar month (UTC). |
| Read limit | Not reached, hourly or monthly limit reached (diagnostic). |
| Connection | The link to DriveLyrics is up (diagnostic). |
| Last request, Last request reason, Last update sent | When and why DriveLyrics last asked, when the answer went out (diagnostic). |
| Requests since start | Disabled by default (diagnostic). |

If your DriveLyrics screens are set to show Spotify instead, a repair issue says so.

## Self-hosted DriveLyrics

With *Advanced mode* on in your Home Assistant profile, the first step also asks for the
server address.

## Development

```sh
uv venv -p 3.14 && uv pip install pytest-homeassistant-custom-component
.venv/bin/pytest
# against a real DriveLyrics server started with DEV_LOGIN=true:
DRIVELYRICS_E2E_URL=http://127.0.0.1:8000 .venv/bin/pytest tests/live
```

The protocol is DriveLyrics' [now-playing feed, v1](https://github.com/jiaton/drivelyrics/blob/main/docs/feed.md).
