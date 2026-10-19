"""Alarmen als events: elk alarm een keer, ook na een herstart."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store

from .alarms import EVENT_TYPES, event_type, label
from .api import Alarm
from .const import DOMAIN
from .coordinator import WhatsGPSConfigEntry, WhatsGPSCoordinator
from .entity import WhatsGPSEntity

PARALLEL_UPDATES = 0
STORAGE_VERSION = 1
# Zoveel gemelde alarm-ID's per tracker onthouden; ruim meer dan een pagina (20).
MAX_SEEN = 500


async def async_setup_entry(
    hass: HomeAssistant, entry: WhatsGPSConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [car_id for car_id in coordinator.data if car_id not in known]
        known.update(new)
        if new:
            async_add_entities(WhatsGPSAlarmEvent(coordinator, car_id) for car_id in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class WhatsGPSAlarmEvent(WhatsGPSEntity, EventEntity):
    """Een event per nieuw alarm.

    Bij de eerste keer (nog niets opgeslagen) gelden de alarmen die er al zijn als gemeld:
    oude alarmen komen dan niet alsnog binnen. Daarna wordt elk alarm-ID een keer gemeld.
    """

    _attr_translation_key = "alarm"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: WhatsGPSCoordinator, car_id: str) -> None:
        super().__init__(coordinator, car_id, "alarm")
        self._store: Store[dict[str, Any]] = Store(
            coordinator.hass, STORAGE_VERSION, f"{DOMAIN}.alarms.{car_id}", private=True
        )
        self._seen: list[str] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        stored = await self._store.async_load()
        if stored is not None:
            self._seen = list(stored.get("seen", []))
        self._handle_alarms()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_alarms()
        super()._handle_coordinator_update()

    @callback
    def _handle_alarms(self) -> None:
        alarms = self.coordinator.alarms.get(self._car_id)
        if alarms is None:
            return
        if self._seen is None:
            # Eerste keer: alles wat er al is, geldt als gemeld.
            self._seen = [alarm.alarm_id for alarm in alarms]
            self._save()
            return
        seen = set(self._seen)
        new = [alarm for alarm in alarms if alarm.alarm_id not in seen]
        if not new:
            return
        for alarm in sorted(new, key=_sort_key):
            self._trigger_event(event_type(alarm.code), _event_data(alarm))
            self._seen.append(alarm.alarm_id)
        self._seen = self._seen[-MAX_SEEN:]
        self._save()
        self.async_write_ha_state()

    @callback
    def _save(self) -> None:
        seen = list(self._seen or [])
        self._store.async_delay_save(lambda: {"seen": seen}, 1)


def _sort_key(alarm: Alarm) -> tuple[float, str]:
    return (alarm.time.timestamp() if alarm.time else 0.0, alarm.alarm_id)


def _event_data(alarm: Alarm) -> dict[str, Any]:
    return {
        "code": alarm.code,
        "description": label(alarm.code),
        "alarm_time": alarm.time.isoformat() if alarm.time else None,
        "speed": alarm.speed,
    }
