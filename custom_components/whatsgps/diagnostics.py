"""Diagnose, zonder wachtwoord, token, IMEI, ID's, kenteken, simkaart of coordinaten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import WhatsGPSConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "token",
    "unique_id",
    "imei",
    "carId",
    "entId",
    "userId",
    "userName",
    "nickName",
    "machineName",
    "carNO",
    "simNO",
    "iccid",
    "lat",
    "lon",
    "latc",
    "lonc",
    "latitude",
    "longitude",
    "customInfoList",
    "carGroupName",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: WhatsGPSConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "consecutive_failures": coordinator.failures,
        "update_interval_s": coordinator.update_interval.total_seconds() if coordinator.update_interval else None,
        "trackers": [async_redact_data(tracker.raw, TO_REDACT) for tracker in (coordinator.data or {}).values()],
    }
