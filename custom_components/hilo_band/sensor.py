"""Sensors for the Hilo Band."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import HiloBandConfigEntry
from .band import HiloBandData
from .const import MODE_ACTIVE
from .entity import HiloBandEntity


@dataclass(frozen=True, kw_only=True)
class HiloBandSensorDescription(SensorEntityDescription):
    """Describes a Hilo Band sensor."""

    value_fn: Callable[[HiloBandData], StateType | datetime]
    # True when the value can only be obtained by connecting to the band.
    requires_active: bool = False


SENSORS: tuple[HiloBandSensorDescription, ...] = (
    # --- Passive: available without ever connecting -----------------------
    HiloBandSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rssi,
    ),
    HiloBandSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_seen,
    ),
    # --- Active: require a GATT connection --------------------------------
    HiloBandSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_active=True,
        value_fn=lambda data: data.battery_level,
    ),
    HiloBandSensorDescription(
        key="frames_pending",
        translation_key="frames_pending",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="frames",
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_active=True,
        value_fn=lambda data: data.frames_pending,
    ),
    HiloBandSensorDescription(
        key="storage_level",
        translation_key="storage_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_active=True,
        value_fn=lambda data: data.storage_level,
    ),
    HiloBandSensorDescription(
        key="band_time",
        translation_key="band_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        requires_active=True,
        value_fn=lambda data: data.band_time,
    ),
    HiloBandSensorDescription(
        key="last_active_read",
        translation_key="last_active_read",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        requires_active=True,
        value_fn=lambda data: data.last_active_read,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiloBandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hilo Band sensors."""
    coordinator = entry.runtime_data
    active = coordinator.mode == MODE_ACTIVE
    async_add_entities(
        HiloBandSensor(coordinator, description)
        for description in SENSORS
        if active or not description.requires_active
    )


class HiloBandSensor(HiloBandEntity, SensorEntity):
    """A single Hilo Band sensor."""

    entity_description: HiloBandSensorDescription

    def __init__(
        self, coordinator, description: HiloBandSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data)
