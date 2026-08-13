"""The Hilo Band (Aktiia) integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENABLE_BLE
from .coordinator import HiloBleCoordinator, HiloCloudCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


@dataclass
class HiloRuntimeData:
    """What the platforms need at runtime."""

    cloud: HiloCloudCoordinator
    ble: HiloBleCoordinator | None = None


type HiloConfigEntry = ConfigEntry[HiloRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: HiloConfigEntry) -> bool:
    """Set up Hilo Band from a config entry."""
    cloud = HiloCloudCoordinator(hass, entry)
    await cloud.async_config_entry_first_refresh()

    ble: HiloBleCoordinator | None = None
    # The cloud tells us the band's MAC, so Bluetooth presence can be attached
    # to the same device without asking the user for an address. Bluetooth is
    # optional here, so a system without it just gets the cloud entities.
    pod = cloud.data.pod
    if entry.options.get(CONF_ENABLE_BLE, True) and pod and pod.mac_address:
        try:
            candidate = HiloBleCoordinator(hass, entry, pod.mac_address)
            await candidate.async_start()
        except (RuntimeError, ValueError, KeyError) as err:
            _LOGGER.debug("Bluetooth presence unavailable, continuing without: %s", err)
        else:
            ble = candidate

    entry.runtime_data = HiloRuntimeData(cloud=cloud, ble=ble)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle entries created by the Bluetooth-only 0.1.x releases.

    Those entries stored a Bluetooth address and nothing else; 0.2 is account
    based, so there is nothing to migrate from. Fail cleanly and let the user
    re-add the integration with their Hilo credentials rather than blowing up
    on a missing key at runtime.
    """
    if entry.version < 2:
        _LOGGER.error(
            "Hilo Band entry '%s' was created by the Bluetooth-only version. "
            "Blood pressure now comes from your Hilo account, so please remove "
            "this entry and add the integration again with your Hilo email and "
            "password",
            entry.title,
        )
        return False
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HiloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: HiloConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
