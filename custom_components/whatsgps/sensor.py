"""Sensoren: snelheid, richting, accu, positiebron, status, tijden en de waarden uit exData."""

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
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TrackerStatus
from .const import POSITION_SOURCES, TRACKER_STATUSES
from .coordinator import WhatsGPSConfigEntry, WhatsGPSCoordinator
from .entity import WhatsGPSEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WhatsGPSSensorDescription(SensorEntityDescription):
    value_fn: Callable[[TrackerStatus], float | int | str | datetime | None]


SENSORS: tuple[WhatsGPSSensorDescription, ...] = (
    WhatsGPSSensorDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.speed,
    ),
    WhatsGPSSensorDescription(
        key="direction",
        translation_key="direction",
        native_unit_of_measurement=DEGREE,
        value_fn=lambda t: t.direction,
    ),
    WhatsGPSSensorDescription(
        key="battery",
        # De eigen accu van de tracker, niet de accu van de auto.
        translation_key="tracker_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.battery,
    ),
    WhatsGPSSensorDescription(
        key="position_source",
        translation_key="position_source",
        device_class=SensorDeviceClass.ENUM,
        options=list(POSITION_SOURCES.values()),
        value_fn=lambda t: t.position_source,
    ),
    WhatsGPSSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=TRACKER_STATUSES,
        value_fn=lambda t: t.status,
    ),
    WhatsGPSSensorDescription(
        key="last_fix",
        translation_key="last_fix",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: t.last_fix,
    ),
    WhatsGPSSensorDescription(
        key="last_communication",
        translation_key="last_communication",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.last_communication,
    ),
    WhatsGPSSensorDescription(
        key="stationary_since",
        translation_key="stationary_since",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: t.stationary_since,
    ),
    WhatsGPSSensorDescription(
        key="today_distance",
        translation_key="today_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda t: t.today_km,
    ),
    WhatsGPSSensorDescription(
        key="total_distance",
        translation_key="total_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda t: t.total_km,
    ),
    WhatsGPSSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.temperature,
    ),
    WhatsGPSSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.humidity,
    ),
    WhatsGPSSensorDescription(
        key="voltage",
        translation_key="external_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.voltage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WhatsGPSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        # Ook trackers die later aan het account worden toegevoegd, zonder herladen.
        new = [car_id for car_id in coordinator.data if car_id not in known]
        known.update(new)
        async_add_entities(
            WhatsGPSSensor(coordinator, car_id, description) for car_id in new for description in SENSORS
        )

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WhatsGPSSensor(WhatsGPSEntity, SensorEntity):
    entity_description: WhatsGPSSensorDescription

    def __init__(self, coordinator: WhatsGPSCoordinator, car_id: str, description: WhatsGPSSensorDescription) -> None:
        super().__init__(coordinator, car_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | datetime | None:
        return self.entity_description.value_fn(self.tracker)
