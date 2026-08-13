"""Coordinators for the Hilo Band integration.

Two independent sources feed one Home Assistant device:

* :class:`HiloCloudCoordinator` polls Aktiia's cloud for the actual health data
  (blood pressure, heart rate, time-in-range, sleep, steps, calibration). This
  is the only place blood pressure exists - the band never computes it.
* :class:`HiloBleCoordinator` optionally listens for the band's Bluetooth
  advertisements to tell you whether it is physically nearby. It never
  connects, so it cannot disturb the phone app.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AktiiaAuthError, AktiiaClient, AktiiaData, AktiiaError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_URL,
    DEFAULT_AWAY_TIMEOUT,
    DEFAULT_CLOUD_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class HiloCloudCoordinator(DataUpdateCoordinator[AktiiaData]):
    """Polls the Aktiia cloud for this account."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_CLOUD_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} cloud",
            update_interval=timedelta(seconds=interval),
        )
        self.client = AktiiaClient(
            async_get_clientsession(hass),
            device_id=entry.data[CONF_DEVICE_ID],
            access_token=entry.data.get(CONF_ACCESS_TOKEN),
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            server_url=entry.data.get(CONF_SERVER_URL),
        )

    async def _async_update_data(self) -> AktiiaData:
        """Fetch the current snapshot from the cloud."""
        try:
            data = await self.client.async_fetch_all(dt_util.now().date())
        except AktiiaAuthError as err:
            # Refresh token is dead - ask the user to sign in again.
            raise ConfigEntryAuthFailed(str(err)) from err
        except AktiiaError as err:
            raise UpdateFailed(str(err)) from err

        self._persist_tokens()
        return data

    def _persist_tokens(self) -> None:
        """Write refreshed tokens back to the config entry.

        The client rotates tokens transparently on 401; without this the entry
        would keep the stale pair and force a full re-login after a restart.
        """
        entry = self.config_entry
        if entry is None:
            return
        current = {
            CONF_ACCESS_TOKEN: self.client.access_token,
            CONF_REFRESH_TOKEN: self.client.refresh_token,
            CONF_SERVER_URL: self.client.server_url,
        }
        if all(entry.data.get(key) == value for key, value in current.items()):
            return
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **current}
        )


class HiloBleCoordinator:
    """Tracks the band's Bluetooth advertisements. Passive, never connects."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        self.hass = hass
        self.entry = entry
        self.address = address.upper()
        self.rssi: int | None = None
        self.last_seen: datetime | None = None
        self._unregister: CALLBACK_TYPE | None = None
        self._listeners: list[CALLBACK_TYPE] = []

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register an entity to be notified on each advertisement."""
        self._listeners.append(update_callback)

        @callback
        def _remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    async def async_start(self) -> None:
        """Begin listening for this band's advertisements."""
        self._unregister = bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            {"address": self.address},
            BluetoothScanningMode.PASSIVE,
        )
        self.entry.async_on_unload(self.async_stop)

        if service_info := bluetooth.async_last_service_info(
            self.hass, self.address, connectable=False
        ):
            self._apply(service_info)

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    @callback
    def _async_on_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        self._apply(service_info)
        for listener in self._listeners:
            listener()

    @callback
    def _apply(self, service_info: BluetoothServiceInfoBleak) -> None:
        self.rssi = service_info.rssi
        self.last_seen = datetime.now(timezone.utc)

    @property
    def in_range(self) -> bool:
        """True while the band advertised recently."""
        if self.last_seen is None:
            return False
        return datetime.now(timezone.utc) - self.last_seen < timedelta(
            seconds=DEFAULT_AWAY_TIMEOUT
        )
