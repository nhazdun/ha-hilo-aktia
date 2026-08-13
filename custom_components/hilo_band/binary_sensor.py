"""Binary sensors for the Hilo Band."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiloBandConfigEntry
from .entity import HiloBandEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiloBandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hilo Band binary sensors."""
    async_add_entities([HiloBandPresence(entry.runtime_data)])


class HiloBandPresence(HiloBandEntity, BinarySensorEntity):
    """True while the band is advertising within range."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_translation_key = "presence"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "presence")

    @property
    def available(self) -> bool:
        """Presence itself is always meaningful, even when the band is away."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the band advertised recently."""
        return self.coordinator.available
