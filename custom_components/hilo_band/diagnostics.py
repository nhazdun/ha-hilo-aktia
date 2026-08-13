"""Diagnostics for the Hilo Band."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HiloConfigEntry
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_REFRESH_TOKEN,
)

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_DEVICE_ID,
    "username",
    "mac_address",
    "serial_number",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HiloConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with credentials stripped."""
    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(asdict(runtime.cloud.data), TO_REDACT),
        "ble": {
            "enabled": runtime.ble is not None,
            "in_range": runtime.ble.in_range if runtime.ble else None,
            "rssi": runtime.ble.rssi if runtime.ble else None,
        },
    }
