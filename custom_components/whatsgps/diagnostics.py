"""Diagnose, zonder wachtwoord, token, IMEI, ID's, kenteken, simkaart of coordinaten.

Van de trackers gaan alleen velden mee die op een lijst van bekende, onschuldige velden
staan. Van alle andere velden alleen de naam, zodat nieuwe velden nooit ongemerkt
persoonsgegevens meenemen.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import WhatsGPSConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "unique_id"}

TRACKER_FIELDS = {
    "active",
    "carType",
    "dataStatus",
    "deviceType",
    "machineType",
    "machineTypeAscription",
    "packVersion",
    "serviceState",
}
STATUS_FIELDS = {
    "accStatus",
    "alarm",
    "dir",
    "distance",
    "exData",
    "heartTime",
    "online",
    "pointTime",
    "pointType",
    "runStatus",
    "show",
    "snapshotStatus",
    "speed",
    "staticTime",
    "status",
    "wireless",
}


def _tracker_view(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("carStatus")
    status = status if isinstance(status, dict) else {}
    return {
        **{key: raw[key] for key in sorted(TRACKER_FIELDS) if key in raw},
        "carStatus": {key: status[key] for key in sorted(STATUS_FIELDS) if key in status},
        "other_fields": sorted(set(raw) - TRACKER_FIELDS - {"carStatus"}),
        "other_status_fields": sorted(set(status) - STATUS_FIELDS),
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: WhatsGPSConfigEntry) -> dict[str, Any]:
    info: dict[str, Any] = {"entry": async_redact_data(entry.as_dict(), TO_REDACT)}
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {**info, "loaded": False}
    trackers = list((coordinator.data or {}).values())
    return {
        **info,
        "loaded": True,
        "consecutive_failures": coordinator.failures,
        "update_interval_s": coordinator.update_interval.total_seconds() if coordinator.update_interval else None,
        "trackers": [_tracker_view(tracker.raw) for tracker in trackers],
        # Per tracker (zelfde volgorde) alleen de alarmcodes, geen ID's of posities.
        "alarm_codes": [[alarm.code for alarm in coordinator.alarms.get(t.car_id, [])] for t in trackers],
    }
