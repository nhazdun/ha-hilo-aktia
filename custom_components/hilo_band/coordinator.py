"""Coordinator for the Hilo Band.

Two modes:

* ``passive`` (default) - only listens for advertisements. Never connects, so
  it cannot interfere with the phone app's link to the band. Gives presence,
  RSSI and last-seen.
* ``active`` - additionally connects on a slow interval to read battery, frame
  count, storage and device info. Reads only; see ``band.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .band import HiloBandAuthError, HiloBandClient, HiloBandData
from .const import (
    CONF_MODE,
    CONF_SCAN_INTERVAL,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_AWAY_TIMEOUT,
    DEFAULT_MODE,
    DOMAIN,
    MODE_ACTIVE,
)

_LOGGER = logging.getLogger(__name__)


class HiloBandCoordinator(DataUpdateCoordinator[HiloBandData]):
    """Keeps a HiloBandData snapshot fresh from advertisements and GATT reads."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.address: str = entry.data["address"]
        self.mode: str = entry.options.get(
            CONF_MODE, entry.data.get(CONF_MODE, DEFAULT_MODE)
        )
        interval_seconds: int = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_ACTIVE_INTERVAL)
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.address}",
            # Passive mode never polls; the advertisement callback drives updates.
            update_interval=(
                timedelta(seconds=interval_seconds) if self.mode == MODE_ACTIVE else None
            ),
        )

        self.entry = entry
        self._client = HiloBandClient(self.address)
        self._unregister_advertisements: CALLBACK_TYPE | None = None
        self.data = HiloBandData(address=self.address)

    # ------------------------------------------------------------------
    # Passive advertisement tracking
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Begin listening for advertisements from this band."""
        self._unregister_advertisements = bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            {"address": self.address},
            BluetoothScanningMode.PASSIVE,
        )
        self.entry.async_on_unload(self.async_stop)

        # Seed from whatever the Bluetooth integration has already cached.
        if service_info := bluetooth.async_last_service_info(
            self.hass, self.address, connectable=False
        ):
            self._apply_advertisement(service_info)

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        if self._unregister_advertisements is not None:
            self._unregister_advertisements()
            self._unregister_advertisements = None

    @callback
    def _async_on_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        self._apply_advertisement(service_info)
        self.async_update_listeners()

    @callback
    def _apply_advertisement(self, service_info: BluetoothServiceInfoBleak) -> None:
        self.data.name = service_info.name or self.data.name
        self.data.rssi = service_info.rssi
        self.data.last_seen = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Presence
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True while the band has advertised recently."""
        if self.data.last_seen is None:
            return False
        age = datetime.now(timezone.utc) - self.data.last_seen
        return age < timedelta(seconds=DEFAULT_AWAY_TIMEOUT)

    # ------------------------------------------------------------------
    # Active polling
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> HiloBandData:
        """Connect and read. Only called in active mode."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            # Out of range, or only reachable through a non-connectable proxy.
            # Keep the passive data we already have rather than going unavailable.
            self.data.last_error = "not_in_range"
            return self.data

        try:
            data = await self._client.async_read(device, previous=self.data)
        except HiloBandAuthError as err:
            # Expected whenever the band is bonded to the phone. Log once at
            # info level and keep serving passive data.
            _LOGGER.info("Hilo Band %s: %s", self.address, err)
            self.data.last_error = "bonded_elsewhere"
            return self.data
        except BleakError as err:
            _LOGGER.debug("Hilo Band %s read failed: %s", self.address, err)
            self.data.last_error = str(err)
            return self.data

        # Preserve passive fields the GATT read does not provide.
        data.rssi = self.data.rssi
        data.last_seen = self.data.last_seen
        data.last_error = None
        self.data = data
        return data
