"""Positie van de tracker."""

from __future__ import annotations

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACCURACY_BY_SOURCE
from .coordinator import WhatsGPSConfigEntry, WhatsGPSCoordinator
from .entity import WhatsGPSEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WhatsGPSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [car_id for car_id in coordinator.data if car_id not in known]
        known.update(new)
        async_add_entities(WhatsGPSTracker(coordinator, car_id) for car_id in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WhatsGPSTracker(WhatsGPSEntity, TrackerEntity):
    _attr_name = None
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: WhatsGPSCoordinator, car_id: str) -> None:
        super().__init__(coordinator, car_id, "location")

    @property
    def latitude(self) -> float | None:
        return self.tracker.latitude

    @property
    def longitude(self) -> float | None:
        return self.tracker.longitude

    @property
    def location_accuracy(self) -> float:
        # Bij een positie via basisstation of wifi een grotere marge, zodat zones niet
        # ten onrechte schakelen.
        return ACCURACY_BY_SOURCE.get(self.tracker.position_source or "not_located", 1000)
