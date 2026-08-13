"""Base entity for the Hilo Band."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HiloBandCoordinator


class HiloBandEntity(CoordinatorEntity[HiloBandCoordinator]):
    """Common device wiring for all Hilo Band entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HiloBandCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the band to the device registry."""
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, self.coordinator.address)},
            name=data.name or "Hilo Band",
            manufacturer=data.manufacturer or MANUFACTURER,
            model=data.model or MODEL,
            sw_version=data.firmware_revision,
            hw_version=data.hardware_revision,
            serial_number=data.serial_number,
        )

    @property
    def available(self) -> bool:
        """Entities follow advertisement presence, not GATT reachability."""
        return self.coordinator.available
