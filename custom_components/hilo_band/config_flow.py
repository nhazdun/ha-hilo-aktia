"""Config flow for the Hilo Band (Aktiia)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ADDRESS,
    CONF_MODE,
    CONF_SCAN_INTERVAL,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_MODE,
    DOMAIN,
    MIN_ACTIVE_INTERVAL,
    MODE_ACTIVE,
    MODE_PASSIVE,
    POD_ADV_PREFIX,
)


def _is_hilo_band(service_info: BluetoothServiceInfoBleak) -> bool:
    """Match the band's advertised local name.

    ``PodBleImpl.isMatchingPod`` uses a case-insensitive prefix match on
    ``AKTIIA P``. The cuff advertises ``AKTIIA C`` and is deliberately excluded.
    """
    name = service_info.name or ""
    return name.upper().startswith(POD_ADV_PREFIX.upper())


_MODE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[MODE_PASSIVE, MODE_ACTIVE],
        translation_key="mode",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


class HiloBandConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Hilo Band."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a band discovered over Bluetooth."""
        if not _is_hilo_band(discovery_info):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered band."""
        assert self._discovered is not None

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered.name or "Hilo Band",
                data={
                    CONF_ADDRESS: self._discovered.address,
                    CONF_MODE: user_input.get(CONF_MODE, DEFAULT_MODE),
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Optional(CONF_MODE, default=DEFAULT_MODE): _MODE_SELECTOR}
            ),
            description_placeholders={"name": self._discovered.name or "Hilo Band"},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a band from the ones Home Assistant can currently see."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered_devices.get(address, "Hilo Band"),
                data={
                    CONF_ADDRESS: address,
                    CONF_MODE: user_input.get(CONF_MODE, DEFAULT_MODE),
                },
            )

        current = self._async_current_ids()
        self._discovered_devices = {
            info.address: f"{info.name} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=False)
            if _is_hilo_band(info) and info.address not in current
        }

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices),
                    vol.Optional(CONF_MODE, default=DEFAULT_MODE): _MODE_SELECTOR,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HiloBandOptionsFlow:
        """Get the options flow."""
        return HiloBandOptionsFlow()


class HiloBandOptionsFlow(OptionsFlow):
    """Let the user switch modes and tune the active poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MODE,
                        default=options.get(CONF_MODE, data.get(CONF_MODE, DEFAULT_MODE)),
                    ): _MODE_SELECTOR,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_ACTIVE_INTERVAL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_ACTIVE_INTERVAL,
                            max=86400,
                            step=60,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
