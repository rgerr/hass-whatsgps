"""Omrekening van GCJ-02 (China) naar WGS-84.

Chinese platforms leveren soms GCJ-02. Buiten China passen ze die verschuiving
normaal niet toe; daarom geldt de omrekening hier alleen binnen een ruwe begrenzing
van China. De inverse is iteratief, nauwkeurig tot ruim onder een meter.
"""

from __future__ import annotations

import math

_A = 6378245.0
_EE = 0.00669342162296594323


def in_china(lat: float, lon: float) -> bool:
    return 73.66 < lon < 135.05 and 3.86 < lat < 53.55


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if not in_china(lat, lon):
        return lat, lon
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return lat + d_lat, lon + d_lon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    if not in_china(lat, lon):
        return lat, lon
    w_lat, w_lon = lat, lon
    for _ in range(10):
        g_lat, g_lon = wgs84_to_gcj02(w_lat, w_lon)
        w_lat -= g_lat - lat
        w_lon -= g_lon - lon
    return w_lat, w_lon
