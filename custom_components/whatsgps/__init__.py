"""WhatsGPS: locatie en status van een tracker op het WhatsGPS-platform (alleen lezen)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import WhatsGPSClient
from .const import DOMAIN
from .coordinator import ALARM_STORE_VERSION, WhatsGPSConfigEntry, WhatsGPSCoordinator, alarm_store_key

PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.EVENT, Platform.SENSOR]


def timezone_seconds() -> int:
    offset = dt_util.now().utcoffset()
    return int(offset.total_seconds()) if offset else 0


async def async_setup_entry(hass: HomeAssistant, entry: WhatsGPSConfigEntry) -> bool:
    client = WhatsGPSClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        # Bij elke login opnieuw bepaald, zodat zomer- en wintertijd kloppen.
        timezone_seconds=timezone_seconds,
    )
    coordinator = WhatsGPSCoordinator(hass, entry, client)
    await coordinator.async_load_alarm_memory()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WhatsGPSConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: WhatsGPSConfigEntry) -> None:
    """Het alarmgeheugen gaat mee weg; opnieuw toevoegen meldt geen oude alarmen."""
    await Store[dict[str, object]](
        hass, ALARM_STORE_VERSION, alarm_store_key(entry.entry_id), private=True
    ).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: WhatsGPSConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Een apparaat mag weg als de tracker niet meer bij het account hoort.

    Alleen als de integratie geladen is: anders is niet bekend welke trackers er zijn.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if entry.state is not ConfigEntryState.LOADED or coordinator is None:
        return False
    trackers = coordinator.data or {}
    return not any(identifier[0] == DOMAIN and identifier[1] in trackers for identifier in device.identifiers)
