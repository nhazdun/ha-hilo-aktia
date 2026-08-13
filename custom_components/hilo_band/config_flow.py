"""Config flow for the Hilo Band (Aktiia)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AktiiaAuthError, AktiiaClient, AktiiaError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_ENABLE_BLE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_URL,
    DEFAULT_CLOUD_INTERVAL,
    DOMAIN,
    MIN_CLOUD_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class HiloBandConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Hilo Band."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in to the Aktiia account."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            device_id = uuid.uuid4().hex
            client = AktiiaClient(
                async_get_clientsession(self.hass), device_id=device_id
            )
            try:
                await client.async_login(username, user_input[CONF_PASSWORD])
            except AktiiaAuthError:
                errors["base"] = "invalid_auth"
            except AktiiaError as err:
                _LOGGER.debug("Aktiia login failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_USERNAME: username,
                        CONF_DEVICE_ID: device_id,
                        CONF_ACCESS_TOKEN: client.access_token,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                        CONF_SERVER_URL: client.server_url,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle an expired session."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and mint a fresh session."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = entry.data.get(CONF_DEVICE_ID) or uuid.uuid4().hex
            client = AktiiaClient(
                async_get_clientsession(self.hass), device_id=device_id
            )
            try:
                await client.async_login(
                    entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except AktiiaAuthError:
                errors["base"] = "invalid_auth"
            except AktiiaError as err:
                _LOGGER.debug("Aktiia re-login failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_DEVICE_ID: device_id,
                        CONF_ACCESS_TOKEN: client.access_token,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                        CONF_SERVER_URL: client.server_url,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            description_placeholders={"username": entry.data.get(CONF_USERNAME, "")},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HiloBandOptionsFlow:
        """Get the options flow."""
        return HiloBandOptionsFlow()


class HiloBandOptionsFlow(OptionsFlow):
    """Poll interval and Bluetooth presence toggle."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_CLOUD_INTERVAL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_CLOUD_INTERVAL,
                            max=86400,
                            step=60,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ENABLE_BLE,
                        default=options.get(CONF_ENABLE_BLE, True),
                    ): selector.BooleanSelector(),
                }
            ),
        )
