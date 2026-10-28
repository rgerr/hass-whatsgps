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

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._car_id not in self.coordinator.alarm_seen:
            await self._async_migrate_old_store()
        self._handle_alarms()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Een nieuwe entity_id kan ter plekke: niets hier hangt van de entity_id af.

        Vanaf Home Assistant 2026.11. Zonder deze methode verwijdert HA de entiteit bij
        hernoemen en voegt hem opnieuw toe. De basisklasse doet hier niets, dus geen super().
        """

    async def _async_migrate_old_store(self) -> None:
        """Versie 0.3.0 bewaarde het geheugen per tracker; overnemen en opruimen."""
        old: Store[dict[str, Any]] = Store(self.hass, STORAGE_VERSION, f"{DOMAIN}.alarms.{self._car_id}", private=True)
        stored = await old.async_load()
        if stored is None:
            return
        self.coordinator.alarm_seen[self._car_id] = list(stored.get("seen", []))
        self.coordinator.async_save_alarm_memory()
        await old.async_remove()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_alarms()
        super()._handle_coordinator_update()

    @callback
    def _handle_alarms(self) -> None:
        alarms = self.coordinator.alarms.get(self._car_id)
        if alarms is None:
            return
        memory = self.coordinator.alarm_seen
        if self._car_id not in memory:
            # Eerste keer: alles wat er al is, geldt als gemeld.
            memory[self._car_id] = [alarm.alarm_id for alarm in alarms]
            self.coordinator.async_save_alarm_memory()
            return
        seen_ids = memory[self._car_id]
        seen = set(seen_ids)
        new = [alarm for alarm in alarms if alarm.alarm_id not in seen]
        if not new:
            return
        for alarm in sorted(new, key=_sort_key):
            self._trigger_event(event_type(alarm.code), _event_data(alarm))
            # Elk alarm een eigen toestand; anders ziet een automatisering alleen het laatste.
            self.async_write_ha_state()
            seen_ids.append(alarm.alarm_id)
        memory[self._car_id] = seen_ids[-MAX_SEEN:]
        self.coordinator.async_save_alarm_memory()


def _sort_key(alarm: Alarm) -> tuple[float, str]:
    return (alarm.time.timestamp() if alarm.time else 0.0, alarm.alarm_id)


def _event_data(alarm: Alarm) -> dict[str, Any]:
    return {
        "code": alarm.code,
        "description": label(alarm.code),
        "alarm_time": alarm.time.isoformat() if alarm.time else None,
        "speed": alarm.speed,
    }
