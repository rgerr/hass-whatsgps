"""Binaire sensoren: online, bewegend, laden en contact (alleen als de tracker contact meldt)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TrackerStatus
from .coordinator import WhatsGPSConfigEntry, WhatsGPSCoordinator
from .entity import WhatsGPSEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WhatsGPSBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[TrackerStatus], bool | None]
    # Alleen aanmaken als de tracker het gegeven levert.
    supported_fn: Callable[[TrackerStatus], bool] = lambda t: True


BINARY_SENSORS: tuple[WhatsGPSBinaryDescription, ...] = (
    WhatsGPSBinaryDescription(
        key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.online and t.active,
    ),
    WhatsGPSBinaryDescription(
        key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda t: t.moving,
    ),
    WhatsGPSBinaryDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda t: t.charging,
        supported_fn=lambda t: t.charging is not None,
    ),
    WhatsGPSBinaryDescription(
        key="ignition",
        translation_key="ignition",
        value_fn=lambda t: t.acc,
        supported_fn=lambda t: t.acc is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WhatsGPSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        # Nieuwe trackers, en gegevens die een tracker pas later levert (zoals contact).
        new = [
            (car_id, description)
            for car_id, tracker in coordinator.data.items()
            for description in BINARY_SENSORS
            if (car_id, description.key) not in known and description.supported_fn(tracker)
        ]
        known.update((car_id, description.key) for car_id, description in new)
        async_add_entities(WhatsGPSBinarySensor(coordinator, car_id, description) for car_id, description in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WhatsGPSBinarySensor(WhatsGPSEntity, BinarySensorEntity):
    entity_description: WhatsGPSBinaryDescription

    def __init__(self, coordinator: WhatsGPSCoordinator, car_id: str, description: WhatsGPSBinaryDescription) -> None:
        super().__init__(coordinator, car_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.tracker)
