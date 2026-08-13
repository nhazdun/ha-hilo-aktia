"""The Hilo Band (Aktiia) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import HiloBandCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type HiloBandConfigEntry = ConfigEntry[HiloBandCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HiloBandConfigEntry) -> bool:
    """Set up Hilo Band from a config entry."""
    coordinator = HiloBandCoordinator(hass, entry)
    await coordinator.async_start()

    if coordinator.update_interval is not None:
        # Active mode: do a first read, but never block setup on it - the band
        # is frequently connected to the phone and will refuse us.
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HiloBandConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: HiloBandConfigEntry) -> None:
    """Reload when the user changes mode or interval."""
    await hass.config_entries.async_reload(entry.entry_id)
