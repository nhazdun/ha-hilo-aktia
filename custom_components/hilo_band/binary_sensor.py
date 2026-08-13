"""Binary sensors for the Hilo Band."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiloConfigEntry
from .entity import HiloBleEntity, HiloCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hilo Band binary sensors."""
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = [HiloCalibratedSensor(runtime.cloud)]
    if runtime.ble is not None:
        entities.append(HiloPresenceSensor(runtime.ble, runtime.cloud))
    async_add_entities(entities)


class HiloCalibratedSensor(HiloCloudEntity, BinarySensorEntity):
    """Whether the band has a completed calibration."""

    _attr_translation_key = "calibrated"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "calibrated")

    @property
    def is_on(self) -> bool | None:
        """On when a full (non-partial) calibration exists."""
        data = self.coordinator.data
        if data.last_calibration is None:
            return None
        # isPartial True means calibration was started but not finished.
        return not bool(data.calibration_partial)


class HiloPresenceSensor(HiloBleEntity, BinarySensorEntity):
    """True while the band is advertising within Bluetooth range."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_translation_key = "presence"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, ble, cloud) -> None:
        super().__init__(ble, cloud, "presence")

    @property
    def is_on(self) -> bool:
        """Return whether the band advertised recently."""
        return self._ble.in_range
