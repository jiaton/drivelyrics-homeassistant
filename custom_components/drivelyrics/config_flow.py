"""Config flow: pick the player, then link to DriveLyrics without copying a token.

Linking is a device flow: DriveLyrics gives a code and a URL, the user approves there
(signed in), and the flow's own poll receives a token for this link alone.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from . import DriveLyricsConfigEntry
from .api import DEFAULT_SERVER, DriveLyricsClient, DriveLyricsError, LinkStarted
from .const import (
    CAR_PLATFORMS,
    CLIENT_NAME,
    CONF_PLAYER,
    CONF_PUSH_ON_CHANGE,
    CONF_REFRESH,
    CONF_SERVER,
    DEFAULT_PUSH_ON_CHANGE,
    DEFAULT_REFRESH,
    DOMAIN,
    LOGGER,
)


def _car_players(hass: HomeAssistant, *, disabled: bool) -> list[er.RegistryEntry]:
    """Media players of car integrations, enabled or turned off by their integration
    (Tesla Fleet ships its media player disabled).
    """
    return [
        entry
        for entry in er.async_get(hass).entities.values()
        if entry.domain == MEDIA_PLAYER_DOMAIN
        and entry.platform in CAR_PLATFORMS
        and (entry.disabled_by is not None) == disabled
    ]


def _suggested_player(hass: HomeAssistant) -> str | None:
    """A car's player if there is one, else the only player there is."""
    cars = [e.entity_id for e in _car_players(hass, disabled=False) if hass.states.get(e.entity_id)]
    if cars:
        return cars[0]
    players = hass.states.async_entity_ids(MEDIA_PLAYER_DOMAIN)
    return players[0] if len(players) == 1 else None


class DriveLyricsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DriveLyrics."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._server = DEFAULT_SERVER
        self._player: str | None = None
        self._link: LinkStarted | None = None
        self._link_task: asyncio.Task[None] | None = None
        self._link_outcome: str | None = None  # approved / denied / expired / cannot_connect
        self._token: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: DriveLyricsConfigEntry) -> OptionsFlowHandler:
        """Options: how to read the player."""
        return OptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the media player."""
        if (
            user_input is None
            and not _car_players(self.hass, disabled=False)
            and _car_players(self.hass, disabled=True)
        ):
            return await self.async_step_enable_player()

        if user_input is not None:
            self._server = user_input.get(CONF_SERVER, DEFAULT_SERVER).rstrip("/")
            return await self._async_player_chosen(user_input[CONF_PLAYER])

        fields: dict[Any, Any] = {
            vol.Required(
                CONF_PLAYER, default=_suggested_player(self.hass) or vol.UNDEFINED
            ): EntitySelector(EntitySelectorConfig(domain=MEDIA_PLAYER_DOMAIN)),
        }
        if self.show_advanced_options:
            fields[vol.Optional(CONF_SERVER, default=DEFAULT_SERVER)] = str
        return self.async_show_form(step_id="user", data_schema=vol.Schema(fields))

    async def async_step_enable_player(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The car's media player exists but is turned off: offer to turn it on."""
        disabled = _car_players(self.hass, disabled=True)
        if user_input is not None:
            if user_input[CONF_PLAYER] == "other":
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_PLAYER): EntitySelector(
                                EntitySelectorConfig(domain=MEDIA_PLAYER_DOMAIN)
                            )
                        }
                    ),
                )
            registry = er.async_get(self.hass)
            entity = registry.async_get(user_input[CONF_PLAYER])
            if entity is None:
                return self.async_abort(reason="player_gone")
            registry.async_update_entity(entity.entity_id, disabled_by=None)
            # The owning integration only creates the entity on its next load.
            if entity.config_entry_id:
                await self.hass.config_entries.async_reload(entity.config_entry_id)
            return await self._async_player_chosen(entity.entity_id)

        options = [
            SelectOptionDict(value=e.entity_id, label=e.name or e.original_name or e.entity_id)
            for e in disabled
        ] + [SelectOptionDict(value="other", label="other")]
        return self.async_show_form(
            step_id="enable_player",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAYER, default=disabled[0].entity_id): SelectSelector(
                        SelectSelectorConfig(options=options, translation_key="enable_player")
                    )
                }
            ),
        )

    async def _async_player_chosen(self, player: str) -> ConfigFlowResult:
        self._player = player
        await self.async_set_unique_id(player)
        self._abort_if_unique_id_configured()
        return await self.async_step_link()

    async def async_step_link(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Wait while the user approves the link in DriveLyrics."""
        if self._link is None:
            client = DriveLyricsClient(async_get_clientsession(self.hass), self._server)
            try:
                self._link = await client.link_start(CLIENT_NAME)
            except DriveLyricsError as err:
                LOGGER.debug("Could not start linking: %s", err)
                return self.async_abort(reason="cannot_connect")
            self._link_task = self.hass.async_create_task(
                self._async_wait_for_approval(client, self._link)
            )

        if self._link_outcome is None:
            return self.async_external_step(
                step_id="link",
                url=self._link.verify_url,
                description_placeholders={"code": self._link.code},
            )
        if self._link_outcome == "approved":
            return self.async_external_step_done(next_step_id="finish")
        return self.async_external_step_done(next_step_id=f"link_{self._link_outcome}")

    async def _async_wait_for_approval(self, client: DriveLyricsClient, link: LinkStarted) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + link.expires_in
        outcome = "expired"
        while loop.time() < deadline:
            await asyncio.sleep(link.interval)
            try:
                status, token = await client.link_poll(link.poll_secret)
            except DriveLyricsError as err:
                LOGGER.debug("Polling the link failed: %s", err)
                continue
            if status == "pending":
                continue
            if status == "approved" and token:
                self._token = token
            outcome = status if status in ("approved", "denied") else "expired"
            break
        self._link_outcome = outcome
        with suppress(UnknownFlow):  # the dialog was closed meanwhile
            await self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)

    async def async_step_link_denied(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The user said no in DriveLyrics."""
        return self.async_abort(reason="link_denied")

    async def async_step_link_expired(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ten minutes passed without an answer."""
        return self.async_abort(reason="link_expired")

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Linked: save the token (and the player)."""
        assert self._token is not None and self._player is not None
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={CONF_TOKEN: self._token}
            )
        state = self.hass.states.get(self._player)
        return self.async_create_entry(
            title=state.name if state else self._player,
            data={CONF_SERVER: self._server, CONF_PLAYER: self._player, CONF_TOKEN: self._token},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """DriveLyrics stopped accepting the token (removed in its settings)."""
        self._server = entry_data[CONF_SERVER]
        self._player = entry_data[CONF_PLAYER]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain, then link again."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_link()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use another media player with the same link."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            player = user_input[CONF_PLAYER]
            await self.async_set_unique_id(player)
            if player != entry.unique_id:
                self._abort_if_unique_id_configured()
            state = self.hass.states.get(player)
            return self.async_update_reload_and_abort(
                entry,
                unique_id=player,
                title=state.name if state else player,
                data_updates={CONF_PLAYER: player},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAYER, default=entry.data[CONF_PLAYER]): EntitySelector(
                        EntitySelectorConfig(domain=MEDIA_PLAYER_DOMAIN)
                    )
                }
            ),
        )

    @callback
    def async_remove(self) -> None:
        """The dialog was closed: stop polling."""
        if self._link_task is not None and not self._link_task.done():
            self._link_task.cancel()


class OptionsFlowHandler(OptionsFlowWithReload):
    """How to read the player."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFRESH, default=options.get(CONF_REFRESH, DEFAULT_REFRESH)
                    ): bool,
                    vol.Required(
                        CONF_PUSH_ON_CHANGE,
                        default=options.get(CONF_PUSH_ON_CHANGE, DEFAULT_PUSH_ON_CHANGE),
                    ): bool,
                }
            ),
        )
