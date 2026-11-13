"""Config flow for Régie des Eaux Montpellier integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import RegieDesEauxAPI
from .const import (
    CONF_PASSWORD,
    CONF_UPDATE_TIME,
    CONF_USERNAME,
    DEFAULT_UPDATE_TIME,
    DOMAIN,
    LOGGER,
)
from .exceptions import CannotConnect, InvalidAuth

TIME_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.TIME))


async def validate_input(hass: HomeAssistant, data: dict[str, str]) -> dict[str, str]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    api = RegieDesEauxAPI(session, data[CONF_USERNAME], data[CONF_PASSWORD])

    if not await api.async_authenticate():
        raise InvalidAuth

    # Return info that you want to store in the config entry.
    return {
        "title": data[CONF_USERNAME],
        CONF_UPDATE_TIME: data.get(CONF_UPDATE_TIME, DEFAULT_UPDATE_TIME),
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Régie des Eaux Montpellier."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except  # noqa: BLE001
                LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(),
            errors=errors,
        )

    def _build_schema(self) -> vol.Schema:
        """Build the schema for the initial step."""
        return vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_UPDATE_TIME, default=DEFAULT_UPDATE_TIME
                ): TIME_SELECTOR,
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow changes.

    Since HA 2024.11+, `self.config_entry` is injected by the framework;
    subclasses must not define __init__ or assign it (it's a read-only property).
    """

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            merged = {**dict(self.config_entry.options), **user_input}
            return self.async_create_entry(title="", data=merged)

        current = self.config_entry.options
        update_time = current.get(
            CONF_UPDATE_TIME,
            self.config_entry.data.get(CONF_UPDATE_TIME, DEFAULT_UPDATE_TIME),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_TIME, default=update_time
                    ): TIME_SELECTOR,
                }
            ),
        )
