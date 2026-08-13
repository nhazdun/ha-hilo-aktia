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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import HiloConfigEntry
from .api import AktiiaData
from .entity import HiloBleEntity, HiloCloudEntity

UNIT_MMHG = "mmHg"
UNIT_BPM = "bpm"
UNIT_STEPS = "steps"


@dataclass(frozen=True, kw_only=True)
class HiloSensorDescription(SensorEntityDescription):
    """Describes a cloud-backed Hilo sensor."""

    value_fn: Callable[[AktiiaData], StateType | datetime]


SENSORS: tuple[HiloSensorDescription, ...] = (
    # --- Latest measurement ------------------------------------------------
    HiloSensorDescription(
        key="systolic",
        translation_key="systolic",
        native_unit_of_measurement=UNIT_MMHG,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=lambda data: data.latest.systolic,
    ),
    HiloSensorDescription(
        key="diastolic",
        translation_key="diastolic",
        native_unit_of_measurement=UNIT_MMHG,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=lambda data: data.latest.diastolic,
    ),
    HiloSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart",
        value_fn=lambda data: data.latest.heart_rate,
    ),
    HiloSensorDescription(
        key="last_measurement",
        translation_key="last_measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.latest.taken_at,
    ),
    HiloSensorDescription(
        key="measurement_type",
        translation_key="measurement_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.latest.measurement_type,
    ),
    # --- Today's averages --------------------------------------------------
    HiloSensorDescription(
        key="avg_systolic_today",
        translation_key="avg_systolic_today",
        native_unit_of_measurement=UNIT_MMHG,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:chart-line",
        value_fn=lambda data: data.today.avg_systolic,
    ),
    HiloSensorDescription(
        key="avg_diastolic_today",
        translation_key="avg_diastolic_today",
        native_unit_of_measurement=UNIT_MMHG,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:chart-line",
        value_fn=lambda data: data.today.avg_diastolic,
    ),
    HiloSensorDescription(
        key="avg_heart_rate_today",
        translation_key="avg_heart_rate_today",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:heart",
        value_fn=lambda data: data.today.avg_heart_rate,
    ),
    HiloSensorDescription(
        key="measurements_today",
        translation_key="measurements_today",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:counter",
        value_fn=lambda data: data.today.measurement_count,
    ),
    # --- Time in range -----------------------------------------------------
    HiloSensorDescription(
        key="ttr_excellent",
        translation_key="ttr_excellent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:target",
        value_fn=lambda data: data.ttr.excellent,
    ),
    HiloSensorDescription(
        key="ttr_adequate",
        translation_key="ttr_adequate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:target",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.ttr.adequate,
    ),
    HiloSensorDescription(
        key="ttr_inadequate",
        translation_key="ttr_inadequate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:target",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.ttr.inadequate,
    ),
    HiloSensorDescription(
        key="ttr_poor",
        translation_key="ttr_poor",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:target",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.ttr.poor,
    ),
    # --- Sleep and steps ---------------------------------------------------
    HiloSensorDescription(
        key="sleep_duration",
        translation_key="sleep_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sleep",
        value_fn=lambda data: data.sleep.duration_seconds,
    ),
    HiloSensorDescription(
        key="time_asleep",
        translation_key="time_asleep",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sleep",
        value_fn=lambda data: data.sleep.time_asleep_seconds,
    ),
    HiloSensorDescription(
        key="steps_today",
        translation_key="steps_today",
        native_unit_of_measurement=UNIT_STEPS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:shoe-print",
        value_fn=lambda data: data.steps_today,
    ),
    HiloSensorDescription(
        key="steps_average",
        translation_key="steps_average",
        native_unit_of_measurement=UNIT_STEPS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:shoe-print",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.steps_average,
    ),
    # --- Calibration -------------------------------------------------------
    HiloSensorDescription(
        key="last_calibration",
        translation_key="last_calibration",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_calibration,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hilo Band sensors."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        HiloCloudSensor(runtime.cloud, description) for description in SENSORS
    ]
    if runtime.ble is not None:
        entities.append(HiloRssiSensor(runtime.ble, runtime.cloud))
    async_add_entities(entities)


class HiloCloudSensor(HiloCloudEntity, SensorEntity):
    """A sensor fed by the Aktiia cloud."""

    entity_description: HiloSensorDescription

    def __init__(self, coordinator, description: HiloSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data)


class HiloRssiSensor(HiloBleEntity, SensorEntity):
    """Bluetooth signal strength, from advertisements only."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "rssi"

    def __init__(self, ble, cloud) -> None:
        super().__init__(ble, cloud, "rssi")

    @property
    def native_value(self) -> StateType:
        """Return the last advertised RSSI."""
        return self._ble.rssi

    @property
    def available(self) -> bool:
        """Only meaningful while the band is nearby."""
        return self._ble.in_range
