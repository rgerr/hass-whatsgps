#!/usr/bin/env python3
"""Geredigeerd overzicht van een HAR-opname van het WhatsGPS-webportaal.

Het script laat zien welke verzoeken het portaal doet en hoe de antwoorden zijn
opgebouwd, zonder geheimen of persoonsgegevens te tonen:

- per verzoek: methode, host, pad, parameternamen, HTTP-status en inhoudstype;
- per JSON-antwoord: de structuur, met per veld de vorm in plaats van de waarde;
- letterlijke waarden alleen voor velden met een onschuldige naam, zoals
  resultaatcode, melding, status, modus en accu;
- ID's, IMEI, accountnamen, tokens en cookies als vaste plaatshouders (IMEI_1,
  TOKEN_1), zodat zichtbaar blijft waar dezelfde waarde terugkomt;
- wachtwoorden alleen met lengte en tekenset;
- coordinaten nooit. Met WHATSGPS_HOME_LAT en WHATSGPS_HOME_LON toont het
  script per coordinatenpaar alleen de afstand tot huis, gelezen als WGS-84,
  als GCJ-02 en als BD-09.

De uitvoer gaat alleen naar stdout. Met --extract-js schrijft het script de
JavaScript-bestanden uit de opname naar een map buiten de repository.

Vereist Python 3.11 of nieuwer, alleen de standaardbibliotheek.

Gebruik:
    python3 scripts/har_inspect.py ~/Downloads/whatsgps.har
    python3 scripts/har_inspect.py ~/Downloads/whatsgps.har --extract-js ~/whatsgps-js
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import math
import os
import re
import statistics
import sys
import traceback
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

# Waarden korter dan dit worden niet over velden heen gekoppeld, om toevallige
# overeenkomsten (zoals "1" of "true") te voorkomen.
MIN_MATCH_LEN = 6

STATIC_EXTENSIONS = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".map", ".webp", ".mp3", ".mp4",
)  # fmt: skip

SECRET_KEYS = {
    "sid", "jsessionid", "ticket", "auth", "authorization", "secret",
    "appsecret", "secretkey", "cookie", "credential", "credentials",
}  # fmt: skip
APPKEY_KEYS = {"appkey", "appid", "apikey", "accesskey", "key", "clientid", "clientsecret"}
# Parameters waarvan wordt bijgehouden of de waarde per verzoek wisselt.
SIGNATURE_KEYS = {"sign", "signature", "sig", "nonce", "timestamp", "ts", "t", "random", "rand"}
SIGNATURE_KEYS |= APPKEY_KEYS
ACCOUNT_KEYS = {
    "account": "ACCOUNT", "user": "ACCOUNT", "username": "ACCOUNT", "loginname": "ACCOUNT",
    "sim": "SIM", "simno": "SIM", "simnum": "SIM", "simcard": "SIM", "iccid": "SIM", "imsi": "SIM",
    "plate": "PLATE", "platenumber": "PLATE", "platenum": "PLATE", "carno": "PLATE",
    "carnum": "PLATE", "vin": "PLATE", "contact": "PII", "remark": "PII", "idcard": "PII",
    "owner": "PII", "tel": "PHONE", "telephone": "PHONE",
}  # fmt: skip
ACCOUNT_SUFFIXES = {
    "account": "ACCOUNT", "name": "NAME", "phone": "PHONE", "mobile": "PHONE",
    "email": "EMAIL", "mail": "EMAIL", "address": "ADDRESS", "addr": "ADDRESS",
}  # fmt: skip
# Velden waarvan de waarde letterlijk getoond mag worden (na maskering).
LITERAL_KEYS = {
    "code", "ret", "result", "retcode", "errcode", "errorcode", "errno", "status", "state",
    "success", "ok", "msg", "message", "errmsg", "errormsg", "error", "mode", "workmode",
    "type", "postype", "positiontype", "locationtype", "loctype", "gpstype", "datatype",
    "alarmtype", "alarmcode", "online", "isonline", "onlinestatus", "acc", "accstatus",
    "moving", "ismoving", "lang", "language", "timezone", "tz", "version", "ver", "total",
    "count", "size", "page", "pageno", "pagesize", "pagenum", "speed", "direction", "course",
    "dir", "angle", "battery", "batterylevel", "power", "electricity", "elec", "voltage",
    "signal", "gsm", "gsmsignal", "rssi", "csq", "satellite", "satellites", "sat", "gpsnum",
    "satnum", "valid", "isvalid", "gpsvalid", "model", "modelname", "devicemodel",
    "devicetype", "producttype", "protocol",
    # Enum-achtige velden van WhatsGPS (gezien in de opname van 19 oktober 2026).
    "pointtype", "runstatus", "maptype", "subflag", "ordertype", "isquerydeviceimage",
    "show", "snapshotstatus", "wireless", "datastatus", "servicestate", "machinetype",
    "machinetypeascription", "cartype", "objecttype", "usertype", "clienttype", "buztype",
    "mileageunit", "speedunit", "timescale", "mapstatus", "timeformat", "active",
    "packversion", "timezonesecond", "terminalchargingstatus", "humidity", "temperature",
}  # fmt: skip
# Headers waarvan de waarde getoond mag worden: versie en soort client, geen geheimen.
HEADER_LITERALS = {"clienttype", "appversion", "lang", "language"}
# Tekstvelden met sleutel=waarde-paren, zoals exData van WhatsGPS.
KV_TEXT_KEYS = {"exdata"}
# Binnen zo'n tekstveld: sleutels waarvan de waarde getoond mag worden.
KV_LITERAL_KEYS = {
    "t", "v", "humidity", "power", "battery", "terminalchargingstatus", "signal", "gsm",
    "csq", "acc", "voltage", "temperature", "temp",
}  # fmt: skip
KV_PAIR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)[=:](.*)$")
VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){0,3}$")

LAT_RE = re.compile(r"^([a-z]{0,6})(lat|latitude)([a-z0-9]{0,3})$")
LON_RE = re.compile(r"^([a-z]{0,6})(lng|lon|long|longitude)([a-z0-9]{0,3})$")
TIME_KEY_RE = re.compile(r"time|date|stamp|^ts$|^t$|at$|updated|created|expire")
DT_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
DECIMAL_RE = re.compile(r"^-?\d+\.\d+$")
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
ALNUM_RE = re.compile(r"^[A-Za-z0-9]+$")
TOKENLIKE_RE = re.compile(r"^[A-Za-z0-9+/=_\-.]+$")
EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
JSONP_RE = re.compile(r"^\s*[\w$.]+\s*\((.*)\)\s*;?\s*$", re.DOTALL)

Home = tuple[float, float]


def norm(key: str) -> str:
    """Maak een veldnaam vergelijkbaar: kleine letters, alleen letters en cijfers."""
    return re.sub(r"[^a-z0-9]", "", key.lower())


def classify(key: str) -> tuple[str, str]:
    """Bepaal hoe een veld behandeld wordt: (klasse, soort plaatshouder)."""
    k = norm(key)
    if "pwd" in k or "pass" in k or "psw" in k:
        return "password", "PASSWORD"
    if "token" in k:
        return "secret", "TOKEN"
    if "session" in k or k in {"sid", "jsessionid"}:
        return "secret", "SESSION"
    if k in SECRET_KEYS:
        return "secret", "SECRET"
    if "imei" in k:
        return "secret", "IMEI"
    if not k.startswith("plat") and (LAT_RE.match(k) or LON_RE.match(k)):
        return "coord", "COORD"
    if k in APPKEY_KEYS:
        return "secret", "APPKEY"
    if k in LITERAL_KEYS:
        return "literal", ""
    if k.endswith("id") or k.endswith("ids"):
        base = k[: -3 if k.endswith("ids") else -2].upper()[:10]
        return "secret", base or "ID"
    if k in ACCOUNT_KEYS:
        return "secret", ACCOUNT_KEYS[k]
    for suffix, kind in ACCOUNT_SUFFIXES.items():
        if k.endswith(suffix):
            return "secret", kind
    return "plain", ""


def password_shape(value: str) -> str:
    n = len(value)
    if HEX_RE.match(value):
        charset = "hex-klein" if value == value.lower() else "hex-groot"
        if value.isascii() and value.isdigit():
            charset = "cijfers"
    elif ALNUM_RE.match(value):
        charset = "alfanumeriek"
    elif TOKENLIKE_RE.match(value):
        charset = "base64-achtig"
    else:
        charset = "overig"
    hint = {32: " (MD5?)", 40: " (SHA-1?)", 64: " (SHA-256?)"}.get(n, "") if "hex" in charset else ""
    return f"len={n} {charset}{hint}"


def fmt_delta(seconds: float) -> str:
    sign = "+" if seconds >= 0 else "-"
    s = abs(seconds)
    if s < 90:
        return f"{sign}{s:.0f}s"
    if s < 5400:
        return f"{sign}{s / 60:.0f}m"
    return f"{sign}{s / 3600:.1f}h"


def parse_har_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def mask_text(text: str) -> str:
    text = EMAIL_RE.sub("<email>", text)
    text = re.sub(r"\d+\.\d+", "#.#", text)
    return re.sub(r"\d{5,}", "#####", text)


# Coordinatenstelsels. De omrekening van GCJ-02 kent hier bewust geen
# uitzondering voor punten buiten China: anders is het verschil altijd nul.

_GCJ_A = 6378245.0
_GCJ_EE = 0.00669342162296594323


def _gcj_offset(lat: float, lon: float) -> tuple[float, float]:
    x = lon - 105.0
    y = lat - 35.0
    dlat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    dlat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    dlat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    dlat += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    dlon = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    dlon += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    dlon += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    dlon += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    rad = lat / 180.0 * math.pi
    magic = 1 - _GCJ_EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (_GCJ_A / sqrt_magic * math.cos(rad) * math.pi)
    return dlat, dlon


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    dlat, dlon = _gcj_offset(lat, lon)
    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """Inverse van wgs84_to_gcj02, iteratief tot ruim onder een meter."""
    w_lat, w_lon = lat, lon
    for _ in range(20):
        g_lat, g_lon = wgs84_to_gcj02(w_lat, w_lon)
        d_lat, d_lon = lat - g_lat, lon - g_lon
        w_lat += d_lat
        w_lon += d_lon
        if abs(d_lat) < 1e-9 and abs(d_lon) < 1e-9:
            break
    return w_lat, w_lon


def bd09_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    x_pi = math.pi * 3000.0 / 180.0
    x = lon - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    return z * math.sin(theta), z * math.cos(theta)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_coord_pairs(mapping: dict[str, Any]) -> list[tuple[str, str]]:
    lats: dict[tuple[str, str], str] = {}
    lons: dict[tuple[str, str], str] = {}
    for key in mapping:
        k = norm(str(key))
        if k.startswith("plat"):
            continue
        if m := LAT_RE.match(k):
            lats[(m.group(1), m.group(3))] = key
        elif m := LON_RE.match(k):
            lons[(m.group(1), m.group(3))] = key
    return [(lats[a], lons[a]) for a in lats if a in lons]


def host_of(url: Any) -> str:
    """Host en poort, zonder eventuele gebruikersnaam en wachtwoord uit de URL."""
    host = url.hostname or ""
    try:
        port = url.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port else host


def try_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def key_paths(obj: Any, prefix: str = "") -> set[str]:
    """Verzameling veldpaden, om antwoorden met dezelfde structuur te groeperen."""
    paths: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}"
            paths.add(path)
            paths |= key_paths(value, path)
    elif isinstance(obj, list):
        for item in obj[:20]:
            paths |= key_paths(item, prefix + "[]")
    return paths


class Registry:
    """Koppelt gevoelige waarden aan vaste plaatshouders zoals TOKEN_1."""

    def __init__(self) -> None:
        self._by_value: dict[str, str] = {}
        self._counters: dict[str, int] = defaultdict(int)
        self._long_values: dict[str, str] = {}
        self.uses: dict[str, list[str]] = defaultdict(list)

    def register(self, kind: str, value: str) -> str:
        key = value if len(value) >= MIN_MATCH_LEN else f"{kind}\0{value}"
        placeholder = self._by_value.get(key)
        if placeholder is None:
            self._counters[kind] += 1
            placeholder = f"{kind}_{self._counters[kind]}"
            self._by_value[key] = placeholder
            if len(value) >= MIN_MATCH_LEN:
                self._long_values[value] = placeholder
        return placeholder

    def lookup(self, value: str) -> str | None:
        if len(value) < MIN_MATCH_LEN:
            return None
        return self._by_value.get(value)

    def find_in(self, text: str) -> list[str]:
        """Plaatshouders van bekende waarden die in een langere tekst voorkomen."""
        found = [ph for value, ph in self._long_values.items() if value in text]
        return sorted(set(found))

    def use(self, placeholder: str, where: str) -> None:
        if where not in self.uses[placeholder]:
            self.uses[placeholder].append(where)


class Inspector:
    def __init__(self, home: Home | None) -> None:
        self.home = home
        self.registry = Registry()
        self.now: datetime | None = None
        self.coord_results: dict[tuple[int, str], list[tuple[float, float, float]]] = defaultdict(list)
        self.entry_labels: dict[int, str] = {}
        self.signature_values: dict[str, list[str]] = defaultdict(list)
        self.signature_shapes: dict[str, str] = {}

    # Vorm van waarden

    def shape(self, key: str, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return self._int_shape(key, value)
        if isinstance(value, float):
            return "<float>"
        if isinstance(value, str):
            return self._str_shape(key, value)
        return f"<{type(value).__name__}>"

    def _epoch_delta(self, key: str, seconds: float) -> str:
        # Alleen bij tijdachtige veldnamen: anders zou de delta een getal verraden.
        if self.now is None or not TIME_KEY_RE.search(norm(key)):
            return ""
        return f" t.o.v. verzoek {fmt_delta(seconds - self.now.timestamp())}"

    def _int_shape(self, key: str, value: int) -> str:
        if 10**12 <= value < 10**13:
            return f"<epoch-ms?{self._epoch_delta(key, value / 1000)}>"
        if 10**9 <= value < 4 * 10**9:
            return f"<epoch-s?{self._epoch_delta(key, value)}>"
        return "<int>"

    def _str_shape(self, key: str, value: str) -> str:
        n = len(value)
        if n == 0:
            return "<str leeg>"
        if m := DT_RE.match(value):
            return self._datetime_shape(value, m.group(1))
        if value.isascii() and value.isdigit():
            if n == 13:
                return f"<str epoch-ms?{self._epoch_delta(key, int(value) / 1000)}>"
            return f"<str len={n} cijfers>"
        if DECIMAL_RE.match(value):
            return "<str decimaal>"
        if HEX_RE.match(value) and n >= 8:
            return f"<str len={n} hex>"
        if ALNUM_RE.match(value):
            return f"<str len={n} alfanumeriek>"
        if TOKENLIKE_RE.match(value):
            return f"<str len={n} token-achtig>"
        return f"<str len={n} tekst>"

    def _datetime_shape(self, value: str, zone: str | None) -> str:
        label = "met zone" if zone else "zonder zone"
        if self.now is None:
            return f"<datetime {label}>"
        text = value.replace("/", "-").replace("T", " ")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return f"<datetime {label}>"
        if parsed.tzinfo is None:
            # Gelezen als UTC: een delta van ongeveer +2h of +8h wijst op lokale tijd.
            parsed = parsed.replace(tzinfo=UTC)
        delta = (parsed - self.now).total_seconds()
        return f"<datetime {label}, als UTC t.o.v. verzoek {fmt_delta(delta)}>"

    def literal(self, value: Any) -> str | None:
        if value is None or isinstance(value, bool):
            return self.shape("", value)
        if isinstance(value, (int, float)):
            return repr(value) if abs(value) <= 100000 else None
        if isinstance(value, str):
            if len(value) > 80:
                return None
            if len(value) >= 16 and TOKENLIKE_RE.match(value):
                return None
            return json.dumps(mask_text(value), ensure_ascii=False)
        return None

    # Velden

    def describe(self, key: str, value: Any, where: str) -> str:
        cls, kind = classify(key)
        if value is None or isinstance(value, bool):
            return self.shape(key, value)
        text = str(value)
        if cls == "password":
            if not text:
                return "<wachtwoord leeg>"
            ph = self.registry.register("PASSWORD", text)
            self.registry.use(ph, where)
            return f"<{ph}: wachtwoord {password_shape(text)}>"
        if cls == "secret":
            if not text:
                return "<leeg>"
            ph = self.registry.register(kind, text)
            self.registry.use(ph, where)
            return f"<{ph}: {self.shape(key, value).strip('<>')}>"
        if cls == "coord":
            return f"<coordinaat {type(value).__name__}>"
        if norm(key) in KV_TEXT_KEYS and isinstance(value, str) and value:
            pairs = self.kv_text(value, where)
            if pairs is not None:
                return pairs
        known = self.registry.lookup(text)
        if known:
            self.registry.use(known, where)
            return f"<{known}: {self.shape(key, value).strip('<>')}>"
        if cls == "literal":
            shown = self.literal(value)
            if shown is not None:
                return shown
            if isinstance(value, str) and len(value) >= 16 and TOKENLIKE_RE.match(value):
                ph = self.registry.register("SECRET", value)
                self.registry.use(ph, where)
                return f"<{ph}: {self.shape(key, value).strip('<>')}>"
        return self.shape(key, value)

    def kv_text(self, text: str, where: str) -> str | None:
        """Een tekstveld met sleutel=waarde-paren: namen tonen, waarden alleen als ze onschuldig zijn."""
        parts = [p for p in re.split(r"[;,&|]", text) if p]
        shown = []
        for part in parts:
            match = KV_PAIR_RE.match(part)
            if not match:
                return None
            name, raw = match.groups()
            value: Any = int(raw) if raw.isdigit() and len(raw) < 8 else raw
            literal = self.literal(value) if norm(name) in KV_LITERAL_KEYS else None
            shown.append(f"{name}={literal if literal is not None else self.describe(name, value, f'{where}.{name}')}")
        return f"<sleutel=waarde: {'; '.join(shown)}>"

    def redact_key(self, key: str, where: str = "") -> str:
        """Veldnamen kunnen zelf een IMEI of ID zijn, bijvoorbeeld als sleutel per apparaat."""
        if DECIMAL_RE.match(key):
            return "<getal als sleutel>"
        return self._redact_segment(key, "KEY", f"{where} (veldnaam)" if where else "")

    def render_mapping(self, mapping: dict[str, Any], where: str, depth: int, out: list[str]) -> None:
        for raw_key, value in mapping.items():
            key = self.redact_key(str(raw_key), where)
            self.render_field(key, value, f"{where}.{key}", depth, out)
        for lat_key, lon_key in find_coord_pairs(mapping):
            out.append("  " * depth + self.coord_line(mapping, lat_key, lon_key, where))

    def render_field(self, key: str, value: Any, where: str, depth: int, out: list[str]) -> None:
        pad = "  " * depth
        if isinstance(value, dict):
            if not value:
                out.append(f"{pad}{key}: {{}}")
                return
            out.append(f"{pad}{key}: {{")
            self.render_mapping(value, where, depth + 1, out)
            out.append(f"{pad}}}")
            return
        if isinstance(value, list):
            self.render_list(key, value, where, depth, out)
            return
        if isinstance(value, str):
            nested = try_json(value)
            if nested is not None:
                self.render_field(f"{key} (JSON in string)", nested, where, depth, out)
                return
        out.append(f"{pad}{key}: {self.describe(key, value, where)}")

    def render_list(self, key: str, value: list[Any], where: str, depth: int, out: list[str]) -> None:
        pad = "  " * depth
        if not value:
            out.append(f"{pad}{key}: []")
            return
        first = value[0]
        if isinstance(first, dict):
            out.append(f"{pad}{key}: [{len(value)} {_elements(len(value))}, eerste:] {{")
            self.render_mapping(first, f"{where}[0]", depth + 1, out)
            first_keys = set(first)
            extra = {k for item in value[1:] if isinstance(item, dict) for k in item} - first_keys
            if extra:
                names = sorted({self.redact_key(str(k)) for k in extra})
                out.append(f"{pad}  (alleen in latere elementen: {', '.join(names)})")
            out.append(f"{pad}}}")
        elif isinstance(first, list):
            out.append(f"{pad}{key}: [{len(value)} {_elements(len(value))}, eerste:]")
            self.render_field("[0]", first, f"{where}[0]", depth + 1, out)
        else:
            out.append(f"{pad}{key}: [{len(value)} x {self.describe(key, first, f'{where}[0]')}]")
        # Overige elementen alleen registreren, zodat koppelingen kloppen.
        scratch: list[str] = []
        for i, item in enumerate(value[1:], 1):
            self.render_field(key, item, f"{where}[{i}]", 0, scratch)

    def coord_line(self, mapping: dict[str, Any], lat_key: str, lon_key: str, where: str) -> str:
        label = f"coordinatenpaar {lat_key}/{lon_key}"
        try:
            lat = float(mapping[lat_key])
            lon = float(mapping[lon_key])
        except (TypeError, ValueError):
            return f"[{label}: geen getal]"
        if lat == 0 and lon == 0:
            return f"[{label}: beide nul]"
        if abs(lat) > 90 or abs(lon) > 180:
            return f"[{label}: buiten bereik, mogelijk geschaald of verwisseld]"
        if self.home is None:
            return f"[{label}: zet WHATSGPS_HOME_LAT/LON voor de afstandstest]"
        h_lat, h_lon = self.home
        as_wgs = distance_m(lat, lon, h_lat, h_lon)
        as_gcj = distance_m(*gcj02_to_wgs84(lat, lon), h_lat, h_lon)
        as_bd = distance_m(*gcj02_to_wgs84(*bd09_to_gcj02(lat, lon)), h_lat, h_lon)
        entry, _, field = where.partition(" ")
        idx = int(entry.lstrip("#")) if entry.lstrip("#").isdigit() else 0
        generic = re.sub(r"\[\d+\]", "[]", field)
        self.coord_results[(idx, f"{generic} {lat_key}/{lon_key}")].append((as_wgs, as_gcj, as_bd))
        return (
            f"[{label}: afstand tot huis gelezen als WGS-84 {as_wgs:.0f} m,"
            f" als GCJ-02 {as_gcj:.0f} m, als BD-09 {as_bd:.0f} m]"
        )

    # Verzoeken

    def redact_path(self, path: str, where: str = "") -> str:
        parts = []
        for segment in path.split("/"):
            base, _, matrix = segment.partition(";")
            parts.append(self._redact_segment(base, "PATH", where) + self._redact_matrix(matrix))
        return "/".join(parts)

    def _redact_segment(self, segment: str, kind: str = "PATH", where: str = "") -> str:
        ph = self.registry.lookup(segment)
        digits = sum(c.isdigit() for c in segment)
        if ph is None and (
            re.fullmatch(r"\d{5,}", segment)
            or (len(segment) >= 16 and (HEX_RE.match(segment) or (digits >= 4 and TOKENLIKE_RE.match(segment))))
        ):
            ph = self.registry.register(kind, segment)
        if ph is None:
            return segment
        if where:
            self.registry.use(ph, where)
        return f"<{ph}>"

    def _redact_matrix(self, matrix: str) -> str:
        if not matrix:
            return ""
        out = []
        for item in matrix.split(";"):
            name, _, value = item.partition("=")
            out.append(f"{name}=<{self.registry.register('SESSION', value)}>" if value else name)
        return ";" + ";".join(out)

    def params_to_dict(self, pairs: list[tuple[str, str]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                existing = result[name]
                result[name] = (existing if isinstance(existing, list) else [existing]) + [value]
            else:
                result[name] = value
        return result

    def track_signature(self, params: dict[str, Any], where: str) -> None:
        for name, value in params.items():
            if norm(name) in SIGNATURE_KEYS and not isinstance(value, (dict, list)):
                self.signature_values[name].append(str(value))
                self.signature_shapes.setdefault(name, self.describe(name, value, f"{where}.{name}"))

    def request_body(self, request: dict[str, Any]) -> tuple[str, Any]:
        post = request.get("postData") or {}
        mime = post.get("mimeType", "")
        if post.get("params"):
            pairs = [(p.get("name", ""), p.get("value", "")) for p in post["params"]]
            return mime, self.params_to_dict(pairs)
        text = post.get("text")
        if not text:
            return mime, None
        if "json" in mime or try_json(text) is not None:
            parsed = try_json(text)
            if parsed is not None:
                return mime, parsed
        if "multipart" in mime:
            return mime, f"<multipart, {len(text)} bytes>"
        if "=" in text and " " not in text.strip():
            return mime, self.params_to_dict(parse_qsl(text, keep_blank_values=True))
        return mime, f"<body {len(text)} bytes>"

    def response_body(self, response: dict[str, Any]) -> tuple[str, Any]:
        content = response.get("content") or {}
        mime = content.get("mimeType", "")
        text = content.get("text")
        if text is None:
            return mime, "<geen inhoud in de opname>"
        if content.get("encoding") == "base64":
            try:
                text = base64.b64decode(text).decode("utf-8", errors="replace")
            except ValueError:
                return mime, "<base64, niet te decoderen>"
        parsed = try_json(text)
        if parsed is None and (m := JSONP_RE.match(text)):
            parsed = try_json(m.group(1))
        if parsed is not None:
            return mime, parsed
        if "html" in mime:
            return mime, f"<html, {len(text)} bytes>"
        return mime, f"<tekst, {len(text)} bytes>"

    def header_summary(self, headers: list[dict[str, str]], where: str) -> str:
        names = []
        for header in headers:
            name = header.get("name", "").lower()
            value = header.get("value", "")
            if name.startswith(":") or name in {"cookie", "set-cookie"}:
                continue
            if name == "content-type":
                names.append(f"{name}={value}")
                continue
            if name in HEADER_LITERALS:
                # Een versienummer is geen coordinaat; literal() zou "1.2" maskeren.
                shown = json.dumps(value) if VERSION_RE.match(value) else self.literal(value)
                if shown is not None:
                    names.append(f"{name}={shown}")
                    continue
            cls, kind = classify(name)
            if cls in {"secret", "password"} and value:
                credential = re.sub(r"^(Bearer|Basic|Token)\s+", "", value, flags=re.IGNORECASE)
                ph = self.registry.lookup(credential) or self.registry.register(kind, credential)
                self.registry.use(ph, f"{where} header {name}")
                names.append(f"{name}=<{ph}>")
                continue
            found = self.registry.find_in(value)
            for ph in found:
                self.registry.use(ph, f"{where} header {name}")
            names.append(f"{name}=<bevat {', '.join(found)}>" if found else name)
        return ", ".join(sorted(set(names))) or "(geen)"

    def cookie_summary(self, cookies: list[dict[str, Any]], where: str) -> str:
        items = []
        for cookie in cookies:
            name = cookie.get("name", "")
            items.append(f"{name}={self._cookie_placeholder(str(cookie.get('value', '')), f'{where} cookie {name}')}")
        return ", ".join(items)

    def set_cookie_lines(self, response: dict[str, Any], where: str) -> list[str]:
        raw = [h.get("value", "") for h in response.get("headers", []) if h.get("name", "").lower() == "set-cookie"]
        lines = []
        for header in raw:
            for cookie in header.split("\n"):
                first, _, attributes = cookie.partition(";")
                name, _, value = first.strip().partition("=")
                ph = self._cookie_placeholder(value, f"{where} set-cookie {name}")
                attrs = "; ".join(self._cookie_attribute(a.strip()) for a in attributes.split(";") if a.strip())
                lines.append(f"  set-cookie: {name}={ph} {attrs}".rstrip())
        if not raw:
            for cookie in response.get("cookies", []):
                name = cookie.get("name", "")
                ph = self._cookie_placeholder(str(cookie.get("value", "")), f"{where} set-cookie {name}")
                parts = [f"path={self.redact_path(cookie['path'])}"] if cookie.get("path") else []
                parts += [f"{k}={cookie[k]}" for k in ("domain", "expires") if cookie.get(k)]
                parts += [k for k in ("httpOnly", "secure") if cookie.get(k)]
                lines.append(f"  set-cookie: {name}={ph} {'; '.join(parts)}".rstrip())
        return lines

    def _cookie_placeholder(self, value: str, where: str) -> str:
        if not value:
            return "<leeg>"
        ph = self.registry.lookup(value) or self.registry.register("COOKIE", value)
        self.registry.use(ph, where)
        return f"<{ph}>"

    def _cookie_attribute(self, attribute: str) -> str:
        name, sep, value = attribute.partition("=")
        if name.strip().lower() == "path":
            return f"{name}{sep}{self.redact_path(value)}"
        return attribute

    def render_entry(self, idx: int, entry: dict[str, Any], t0: datetime | None) -> tuple[tuple[Any, ...], list[str]]:
        request = entry.get("request", {})
        response = entry.get("response", {})
        self.now = parse_har_time(entry.get("startedDateTime", ""))
        where = f"#{idx}"
        body: list[str] = []

        url = urlsplit(request.get("url", ""))
        query = self.params_to_dict(parse_qsl(url.query, keep_blank_values=True))
        if query:
            self.track_signature(query, f"{where} query")
            body.append("  query: {")
            self.render_mapping(query, f"{where} query", 2, body)
            body.append("  }")
        mime, req_body = self.request_body(request)
        if isinstance(req_body, dict):
            self.track_signature(req_body, f"{where} body")
        if req_body is not None:
            if isinstance(req_body, (dict, list)):
                self.render_field(f"body ({mime or '?'})", req_body, f"{where} body", 1, body)
            else:
                body.append(f"  body ({mime or '?'}): {req_body}")
        if request.get("cookies"):
            body.append(f"  cookies: {self.cookie_summary(request['cookies'], where)}")
        body.append(f"  request-headers: {self.header_summary(request.get('headers', []), where)}")
        body.extend(self.set_cookie_lines(response, where))
        body.append(f"  response-headers: {self.header_summary(response.get('headers', []), where + ' antwoord')}")
        if response.get("redirectURL"):
            target = urlsplit(response["redirectURL"])
            names = ", ".join(sorted({self.redact_key(n) for n, _ in parse_qsl(target.query, keep_blank_values=True)}))
            body.append(f"  redirect: {host_of(target)}{self.redact_path(target.path)} query-namen: {names or '-'}")
        resp_mime, resp_body = self.response_body(response)
        if isinstance(resp_body, (dict, list)):
            self.render_field(f"antwoord ({resp_mime})", resp_body, f"{where} antwoord", 1, body)
        else:
            body.append(f"  antwoord ({resp_mime}): {resp_body}")
        body.extend(self.websocket_lines(entry, where))

        path = self.redact_path(url.path, f"{where} pad")
        self.entry_labels[idx] = f"{request.get('method', '?')} {host_of(url)}{path}"
        status = response.get("status")
        offset = ""
        if t0 and self.now:
            offset = f" t={fmt_delta((self.now - t0).total_seconds())}"
        header = f"#{idx} {request.get('method', '?')} {host_of(url)}{path} -> {status} {resp_mime}{offset}"
        signature = (
            request.get("method"), host_of(url), path, status,
            tuple(sorted(query)), tuple(sorted(key_paths(req_body))), tuple(sorted(key_paths(resp_body))),
        )  # fmt: skip
        return signature, [header, *body]

    def websocket_lines(self, entry: dict[str, Any], where: str) -> list[str]:
        messages = entry.get("_webSocketMessages") or []
        if not messages:
            return []
        lines = [f"  websocket: {len(messages)} berichten"]
        seen: dict[tuple[Any, ...], int] = {}
        for i, message in enumerate(messages):
            data = message.get("data", "")
            parsed = try_json(data) if isinstance(data, str) else None
            sig = (message.get("type"), tuple(sorted(key_paths(parsed))) if parsed is not None else len(data) > 0)
            out: list[str] = []
            label = str(message.get("type", "?"))
            if parsed is not None:
                self.render_field(label, parsed, f"{where} ws[{i}]", 2, out)
            else:
                out.append(f"    {label}: <tekst, {len(data)} bytes>")
            if sig not in seen:
                seen[sig] = 1
                lines.extend(out)
            else:
                seen[sig] += 1
        repeats = sum(count - 1 for count in seen.values())
        if repeats:
            lines.append(f"  (nog {repeats} websocketberichten met een al getoonde structuur)")
        return lines

    def render(self, entries: list[dict[str, Any]], show_static: bool, dedupe: bool) -> list[str]:
        self.registry.uses.clear()
        self.coord_results.clear()
        self.entry_labels.clear()
        self.signature_values.clear()
        self.signature_shapes.clear()
        out: list[str] = []
        hosts: dict[str, int] = defaultdict(int)
        groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
        times: dict[int, datetime] = {}
        statics = 0
        no_content = 0
        started = [parse_har_time(e.get("startedDateTime", "")) for e in entries]
        t0 = min((t for t in started if t), default=None)

        for idx, entry in enumerate(entries, 1):
            url = urlsplit(entry.get("request", {}).get("url", ""))
            if url.scheme not in {"http", "https", "ws", "wss"}:
                continue
            hosts[host_of(url)] += 1
            mime = (entry.get("response", {}).get("content") or {}).get("mimeType", "")
            is_static = url.path.lower().endswith(STATIC_EXTENSIONS) or mime.startswith(("image/", "font/", "text/css"))
            if is_static:
                statics += 1
                if show_static:
                    status = entry.get("response", {}).get("status")
                    names = ", ".join(
                        sorted({self.redact_key(n) for n, _ in parse_qsl(url.query, keep_blank_values=True)})
                    )
                    out.append(f"#{idx} statisch {host_of(url)}{self.redact_path(url.path)} -> {status}"
                               f" query-namen: {names or '-'}")  # fmt: skip
                continue
            if (entry.get("response", {}).get("content") or {}).get("text") is None:
                no_content += 1
            signature, lines = self.render_entry(idx, entry, t0)
            entry_time = started[idx - 1]
            if entry_time is not None:
                times[idx] = entry_time
            groups[signature].append(idx)
            if dedupe and len(groups[signature]) > 1:
                continue
            out.extend(lines)
            out.append("")

        out.extend(self.summary(hosts, groups, times, statics, no_content))
        return out

    def summary(
        self,
        hosts: dict[str, int],
        groups: dict[tuple[Any, ...], list[int]],
        times: dict[int, datetime],
        statics: int,
        no_content: int,
    ) -> list[str]:
        out = ["== Samenvatting ==", "Hosts (alle verzoeken, ook statisch):"]
        out += [f"  {host}: {count}" for host, count in sorted(hosts.items(), key=lambda i: -i[1])]
        out.append(f"Statische bestanden overgeslagen: {statics} (toon ze met --static)")
        if no_content:
            out.append(f"Verzoeken zonder antwoordinhoud in de opname: {no_content}")

        repeated = [(sig, ids) for sig, ids in groups.items() if len(ids) > 1]
        if repeated:
            out.append("Herhaalde verzoeken met dezelfde structuur (alleen de eerste is getoond):")
            for sig, ids in repeated:
                stamps = [times[i] for i in ids if i in times]
                gaps = [(b - a).total_seconds() for a, b in itertools.pairwise(stamps)]
                interval = f", mediaan interval {statistics.median(gaps):.0f} s" if gaps else ""
                out.append(f"  {sig[0]} {sig[1]}{sig[2]} -> {sig[3]}: {len(ids)} keer (#{ids[0]}){interval}")

        if self.signature_values:
            out.append("Handtekening- of sleutelachtige parameters:")
            for name, values in self.signature_values.items():
                changes = "ja" if len(set(values)) > 1 else "nee"
                out.append(
                    f"  {name}: {len(values)} keer, {len(set(values))} verschillende waarden,"
                    f" wisselt per verzoek: {changes}, vorm {self.signature_shapes.get(name, '?')}"
                )
        else:
            out.append("Handtekening- of sleutelachtige parameters: geen gevonden")

        if self.registry.uses:
            out.append("Plaatshouders en waar ze voorkomen:")
            for ph in sorted(self.registry.uses, key=_placeholder_sort_key):
                places = self.registry.uses[ph]
                shown = "; ".join(places[:8]) + (f"; en nog {len(places) - 8}" if len(places) > 8 else "")
                out.append(f"  {ph}: {shown}")

        if self.coord_results:
            grouped: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
            for (idx, field), results in self.coord_results.items():
                grouped[f"{self.entry_labels.get(idx, '?')} {field}"].extend(results)
            out.append("Coordinaten, kleinste afstand tot huis per endpoint en veldpaar (WGS-84 / GCJ-02 / BD-09):")
            for name, results in grouped.items():
                best = [min(r[i] for r in results) for i in range(3)]
                out.append(f"  {name}: {best[0]:.0f} m / {best[1]:.0f} m / {best[2]:.0f} m ({len(results)} keer)")
        elif self.home is None:
            out.append("Coordinaten: geen afstandstest, WHATSGPS_HOME_LAT/LON niet gezet")
        return out


def _elements(count: int) -> str:
    return "element" if count == 1 else "elementen"


def _placeholder_sort_key(placeholder: str) -> tuple[str, int]:
    kind, _, number = placeholder.rpartition("_")
    return kind, int(number) if number.isdigit() else 0


def read_home() -> Home | None:
    lat = os.environ.get("WHATSGPS_HOME_LAT")
    lon = os.environ.get("WHATSGPS_HOME_LON")
    if not lat or not lon:
        return None
    try:
        home = (float(lat), float(lon))
    except ValueError:
        sys.exit("WHATSGPS_HOME_LAT/LON zijn geen getallen.")
    if abs(home[0]) > 90 or abs(home[1]) > 180:
        sys.exit("WHATSGPS_HOME_LAT/LON liggen buiten het geldige bereik.")
    return home


def extract_js(entries: list[dict[str, Any]], target: Path) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    target = target.expanduser().resolve()
    if target == repo_root or repo_root in target.parents:
        sys.exit("Kies voor --extract-js een map buiten de repository.")
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for entry in entries:
        url = urlsplit(entry.get("request", {}).get("url", ""))
        content = entry.get("response", {}).get("content") or {}
        # Alleen op extensie: API-antwoorden komen soms als application/javascript
        # terug en bevatten dan IMEI en coordinaten.
        if not url.path.lower().endswith(".js"):
            continue
        text = content.get("text")
        if text is None:
            continue
        data = base64.b64decode(text) if content.get("encoding") == "base64" else text.encode("utf-8")
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", url.path.rsplit("/", 1)[-1]) or "script.js"
        (target / name).write_bytes(data)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Geredigeerd overzicht van een WhatsGPS-HAR-opname.")
    parser.add_argument("har", type=Path, help="pad naar het HAR-bestand (buiten de repository)")
    parser.add_argument("--static", action="store_true", help="toon ook statische bestanden (alleen pad)")
    parser.add_argument("--no-dedupe", action="store_true", help="toon ook herhaalde verzoeken volledig")
    parser.add_argument("--extract-js", type=Path, metavar="MAP", help="schrijf de JavaScript uit de opname naar MAP")
    args = parser.parse_args(argv)

    har_path = args.har.expanduser()
    if not har_path.is_file():
        sys.exit(f"HAR-bestand niet gevonden: {har_path}")
    try:
        with har_path.open(encoding="utf-8") as handle:
            har = json.load(handle)
    except ValueError:
        sys.exit("Het bestand is geen geldige JSON. Is het een HAR-export uit Chrome?")
    entries = har.get("log", {}).get("entries", [])
    entries.sort(key=lambda e: e.get("startedDateTime", ""))

    if args.extract_js:
        count = extract_js(entries, args.extract_js)
        print(f"{count} JavaScript-bestanden geschreven naar {args.extract_js}")
        return 0

    inspector = Inspector(read_home())
    # Eerste ronde alleen om plaatshouders te verzamelen, zodat een waarde ook
    # herkend wordt in velden die eerder in de opname staan dan het veld waar
    # ze een naam krijgt.
    inspector.render(entries, args.static, not args.no_dedupe)
    lines = inspector.render(entries, args.static, not args.no_dedupe)
    print(
        "Legenda: <SOORT_n> is een plaatshouder voor een gevoelige waarde. Een delta 't.o.v. verzoek'"
        " is het verschil met het tijdstip van het verzoek; een datetime zonder zone wordt als UTC gelezen."
    )
    print(f"Verzoeken in de opname: {len(entries)}\n")
    print("\n".join(lines))
    return 0


def run() -> int:
    try:
        return main()
    except Exception as err:
        # Een foutmelding kan een waarde uit de opname bevatten, dus alleen soort en plek.
        frame = traceback.extract_tb(err.__traceback__)[-1]
        print(
            f"Interne fout {type(err).__name__} in regel {frame.lineno} ({frame.name})."
            " De melding zelf is weggelaten omdat die waarden uit de opname kan bevatten.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(run())
