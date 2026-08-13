"""Base entities for the Hilo Band."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HiloBleCoordinator, HiloCloudCoordinator


def _build_device_info(coordinator: HiloCloudCoordinator) -> DeviceInfo:
    """Describe the band, enriched with whatever the cloud knows about it."""
    entry = coordinator.config_entry
    assert entry is not None

    pod = coordinator.data.pod if coordinator.data else None
    connections = set()
    if pod and pod.mac_address:
        connections.add((CONNECTION_BLUETOOTH, pod.mac_address.upper()))

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections=connections,
        name=(pod.advertising_name if pod and pod.advertising_name else "Hilo Band"),
        manufacturer=(
            pod.manufacturer_name if pod and pod.manufacturer_name else MANUFACTURER
        ),
        model=MODEL,
        sw_version=pod.firmware_revision if pod else None,
        serial_number=pod.serial_number if pod else None,
    )


class HiloCloudEntity(CoordinatorEntity[HiloCloudCoordinator]):
    """An entity backed by the Aktiia cloud."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HiloCloudCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared device record."""
        return _build_device_info(self.coordinator)


class HiloBleEntity(Entity):
    """An entity backed by Bluetooth advertisements.

    Shares the device record with the cloud entities so presence shows up on
    the same Hilo Band device rather than a second one.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        ble: HiloBleCoordinator,
        cloud: HiloCloudCoordinator,
        key: str,
    ) -> None:
        self._ble = ble
        self._cloud = cloud
        entry = cloud.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to advertisement updates."""
        self.async_on_remove(self._ble.async_add_listener(self.async_write_ha_state))

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared device record."""
        return _build_device_info(self._cloud)
