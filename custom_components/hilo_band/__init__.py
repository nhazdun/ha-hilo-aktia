"""The Hilo Band (Aktiia) integration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import ATTR_FULL, CONF_ENABLE_BLE, DOMAIN, SERVICE_IMPORT_HISTORY
from .coordinator import HiloBleCoordinator, HiloCloudCoordinator
from .statistics import HiloStatisticsImporter

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_FULL, default=False): cv.boolean})


@dataclass
class HiloRuntimeData:
    """What the platforms need at runtime."""

    cloud: HiloCloudCoordinator
    importer: HiloStatisticsImporter
    ble: HiloBleCoordinator | None = None


type HiloConfigEntry = ConfigEntry[HiloRuntimeData]


def _slug(entry: HiloConfigEntry, serial: str | None) -> str:
    """A stable, filesystem-safe id for this account's statistics."""
    raw = serial or entry.entry_id[:12]
    return re.sub(r"[^a-z0-9_]", "_", raw.lower())


async def async_setup_entry(hass: HomeAssistant, entry: HiloConfigEntry) -> bool:
    """Set up Hilo Band from a config entry."""
    cloud = HiloCloudCoordinator(hass, entry)
    await cloud.async_config_entry_first_refresh()

    pod = cloud.data.pod
    device_name = (pod.advertising_name if pod else None) or "Hilo Band"
    importer = HiloStatisticsImporter(
        hass,
        cloud.client,
        _slug(entry, pod.serial_number if pod else None),
        device_name,
    )
    cloud.importer = importer

    ble: HiloBleCoordinator | None = None
    # The cloud tells us the band's MAC, so Bluetooth presence can be attached
    # to the same device without asking the user for an address. Bluetooth is
    # optional here, so a system without it just gets the cloud entities.
    if entry.options.get(CONF_ENABLE_BLE, True) and pod and pod.mac_address:
        try:
            candidate = HiloBleCoordinator(hass, entry, pod.mac_address)
            await candidate.async_start()
        except (RuntimeError, ValueError, KeyError) as err:
            _LOGGER.debug("Bluetooth presence unavailable, continuing without: %s", err)
        else:
            ble = candidate

    entry.runtime_data = HiloRuntimeData(cloud=cloud, importer=importer, ble=ble)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # The first import can span a year of measurements, so keep it off the
    # setup path; later polls only top up the newest hours.
    entry.async_create_background_task(
        hass, _async_initial_import(importer), f"{DOMAIN}_initial_import"
    )

    _async_register_services(hass)
    return True


async def _async_initial_import(importer: HiloStatisticsImporter) -> None:
    """Backfill history once, without blocking setup."""
    try:
        await importer.async_import()
    except Exception:  # noqa: BLE001 - never let a backfill break setup
        _LOGGER.exception("Initial Hilo history import failed")


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the manual import service once."""
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORY):
        return

    async def _handle_import(call: ServiceCall) -> None:
        """Re-import history for every configured Hilo account."""
        full = call.data.get(ATTR_FULL, False)
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            _LOGGER.warning("No Hilo Band accounts are set up")
            return
        for entry in entries:
            runtime: HiloRuntimeData = entry.runtime_data
            count = await runtime.importer.async_import(full=full)
            _LOGGER.info(
                "Hilo history import for %s finished: %s measurements",
                entry.title,
                count,
            )

    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_HISTORY, _handle_import, schema=SERVICE_SCHEMA
    )


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
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_IMPORT_HISTORY)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: HiloConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
