"""Constanten voor de WhatsGPS-integratie."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "whatsgps"
LOGGER = logging.getLogger(__package__)

BASE_URL: Final = "https://www.whatsgps.com/web/api"
# Vaste headers van het internationale webportaal, letterlijk uit de openbare JavaScript
# van www.whatsgps.com (zie docs/api.md). Geen geheimen en niet per klant verschillend.
APP_ID: Final = "ABROAD_WHATSGPS"
APP_KEY: Final = "ljdw-abroad"
APP_VERSION: Final = "1.0.0"
CLIENT_TYPE: Final = "pc"
LANGUAGE: Final = "nl"
REQUEST_TIMEOUT: Final = 15

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 600
MAX_BACKOFF: Final = 900
# Kilometers (mileageSta) veranderen langzaam: hooguit eens per 10 minuten ophalen.
MILEAGE_INTERVAL: Final = 600
# Alarmen hooguit eens per 2 minuten, of eerder als de status een alarm meldt.
ALARM_INTERVAL: Final = 120
# Na zoveel mislukte rondes op rij worden de entiteiten onbeschikbaar.
FAILURES_BEFORE_UNAVAILABLE: Final = 3

MANUFACTURER: Final = "Protectly/WhatsGPS"

# Coordinatenstelsel van lat/lon in het statusantwoord: WGS-84, bevestigd op 19 oktober 2026
# (docs/api.md, vraag 1). "gcj02" rekent om naar WGS-84.
COORDINATE_SYSTEM: Final[str] = "wgs84"

# pointType: bron van de positie, met een realistische nauwkeurigheid in meters zodat
# zones in Home Assistant niet ten onrechte schakelen.
POSITION_SOURCES: Final[dict[int, str]] = {
    0: "not_located",
    1: "satellite",
    2: "compass",
    3: "cell_tower",
    4: "wifi",
    5: "differential",
}
ACCURACY_BY_SOURCE: Final[dict[str, int]] = {
    "satellite": 20,
    "differential": 10,
    "wifi": 100,
    "cell_tower": 500,
    "compass": 500,
    "not_located": 1000,
}

# runStatus volgens de JavaScript van het portaal; "offline" als het apparaat offline of
# niet actief is.
RUN_STATUSES: Final[dict[int, str]] = {
    0: "not_located",
    1: "stationary",
    2: "moving",
    3: "speeding",
    4: "idling",
}
TRACKER_STATUSES: Final = ["offline", *RUN_STATUSES.values()]
