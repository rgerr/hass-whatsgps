"""Coordinator: een statusverzoek per ronde voor alle trackers van het account."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Alarm, Mileage, TrackerStatus, WhatsGPSAuthError, WhatsGPSClient, WhatsGPSError
from .const import (
    ALARM_INTERVAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAILURES_BEFORE_UNAVAILABLE,
    LOGGER,
    MAX_BACKOFF,
    MILEAGE_INTERVAL,
)

type WhatsGPSConfigEntry = ConfigEntry[WhatsGPSCoordinator]

ALARM_STORE_VERSION = 1


def alarm_store_key(entry_id: str) -> str:
    """Een opslag per integratie, zodat verwijderen ook het alarmgeheugen wist."""
    return f"{DOMAIN}.alarms.{entry_id}"


class WhatsGPSCoordinator(DataUpdateCoordinator[dict[str, TrackerStatus]]):
    """Haalt de status op; bij fouten exponentieel langzamer, tot 15 minuten.

    Een of twee mislukte rondes houden de laatste waarden vast. Pas na de derde
    mislukte ronde op rij worden de entiteiten onbeschikbaar. Een geweigerde login
    start de reauth-flow en wordt niet herhaald.
    """

    config_entry: WhatsGPSConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WhatsGPSConfigEntry, client: WhatsGPSClient) -> None:
        self.base_interval = timedelta(seconds=int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        super().__init__(hass, LOGGER, config_entry=entry, name=DOMAIN, update_interval=self.base_interval)
        self.client = client
        self.failures = 0
        self.mileage: dict[str, Mileage] = {}
        self._mileage_at: datetime | None = None
        # Laatst opgehaalde alarmen per tracker; de event-entiteit kiest de nieuwe eruit.
        self.alarms: dict[str, list[Alarm]] = {}
        # Gemelde alarm-ID's per tracker; ontbreekt een tracker, dan is er nog niets gemeld.
        self.alarm_seen: dict[str, list[str]] = {}
        self._alarm_store: Store[dict[str, Any]] = Store(
            hass, ALARM_STORE_VERSION, alarm_store_key(entry.entry_id), private=True
        )
        self._alarms_at: datetime | None = None
        self._alarm_text: dict[str, str] = {}

    async def async_load_alarm_memory(self) -> None:
        stored = await self._alarm_store.async_load()
        seen = (stored or {}).get("seen") or {}
        self.alarm_seen = {str(car_id): list(ids) for car_id, ids in seen.items()}

    @callback
    def async_save_alarm_memory(self) -> None:
        snapshot = {car_id: list(ids) for car_id, ids in self.alarm_seen.items()}
        self._alarm_store.async_delay_save(lambda: {"seen": snapshot}, 1)

    async def _async_update_data(self) -> dict[str, TrackerStatus]:
        try:
            trackers = await self.client.async_get_trackers()
        except WhatsGPSAuthError as err:
            raise ConfigEntryAuthFailed("WhatsGPS weigert de inloggegevens") from err
        except WhatsGPSError as err:
            self.failures += 1
            backoff = min(self.base_interval.total_seconds() * 2**self.failures, MAX_BACKOFF)
            self.update_interval = timedelta(seconds=max(backoff, self.base_interval.total_seconds()))
            if self.data is not None and self.failures < FAILURES_BEFORE_UNAVAILABLE:
                LOGGER.warning(
                    "WhatsGPS niet bereikbaar (%s), poging %s; laatste waarden blijven staan", err, self.failures
                )
                return self.data
            raise UpdateFailed(f"WhatsGPS niet bereikbaar: {err}") from err
        if self.failures:
            LOGGER.info("WhatsGPS weer bereikbaar na %s mislukte rondes", self.failures)
        self.failures = 0
        self.update_interval = self.base_interval
        await self._async_refresh_mileage(trackers)
        await self._async_refresh_alarms(trackers)
        return {
            tracker.car_id: dataclasses.replace(
                tracker,
                today_km=self.mileage[tracker.car_id].today_km if tracker.car_id in self.mileage else None,
                total_km=self.mileage[tracker.car_id].total_km if tracker.car_id in self.mileage else None,
            )
            for tracker in trackers
        }

    async def _async_refresh_mileage(self, trackers: list[TrackerStatus]) -> None:
        """Een extra verzoek per tracker, hooguit eens per 10 minuten.

        Mislukt het, dan blijven de vorige kilometers staan; de ronde telt niet als mislukt.
        """
        now = dt_util.utcnow()
        if self._mileage_at is not None and (now - self._mileage_at).total_seconds() < MILEAGE_INTERVAL:
            return
        self._mileage_at = now
        for tracker in trackers:
            try:
                self.mileage[tracker.car_id] = await self.client.async_get_mileage(tracker.car_id)
            except WhatsGPSAuthError as err:
                raise ConfigEntryAuthFailed("WhatsGPS weigert de inloggegevens") from err
            except WhatsGPSError as err:
                LOGGER.debug("Kilometers niet opgehaald: %s", err)

    async def _async_refresh_alarms(self, trackers: list[TrackerStatus]) -> None:
        """Een verzoek per tracker, hooguit eens per 2 minuten.

        Eerder als het alarmveld in de status verandert en niet leeg is. Mislukt het,
        dan blijft de vorige lijst staan; de ronde telt niet als mislukt.
        """
        now = dt_util.utcnow()
        texts = {t.car_id: str((t.raw.get("carStatus") or {}).get("alarm") or "") for t in trackers}
        changed = any(text and text != self._alarm_text.get(car_id) for car_id, text in texts.items())
        due = self._alarms_at is None or (now - self._alarms_at).total_seconds() >= ALARM_INTERVAL
        if not (due or changed):
            return
        self._alarms_at = now
        self._alarm_text = texts
        for tracker in trackers:
            try:
                self.alarms[tracker.car_id] = await self.client.async_get_alarms(tracker.car_id)
            except WhatsGPSAuthError as err:
                raise ConfigEntryAuthFailed("WhatsGPS weigert de inloggegevens") from err
            except WhatsGPSError as err:
                LOGGER.debug("Alarmen niet opgehaald: %s", err)
