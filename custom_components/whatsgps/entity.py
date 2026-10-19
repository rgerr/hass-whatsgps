"""Basisentiteit: een device per tracker."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TrackerStatus
from .const import DOMAIN, MANUFACTURER
from .coordinator import WhatsGPSCoordinator


class WhatsGPSEntity(CoordinatorEntity[WhatsGPSCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: WhatsGPSCoordinator, car_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._car_id = car_id
        tracker = coordinator.data[car_id]
        # Het interne carId van WhatsGPS, niet het IMEI.
        self._attr_unique_id = f"{car_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, car_id)},
            manufacturer=MANUFACTURER,
            model=f"GPS-tracker type {tracker.model_code}" if tracker.model_code else "GPS-tracker",
            name=tracker.name,
            serial_number=tracker.imei or None,
        )

    @property
    def tracker(self) -> TrackerStatus:
        return self.coordinator.data[self._car_id]

    @property
    def available(self) -> bool:
        return super().available and self._car_id in (self.coordinator.data or {})
