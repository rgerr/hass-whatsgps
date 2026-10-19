# Changelog

## 0.3.0 (2026-10-19)

First public release.

- Device tracker, sensors (speed, direction, tracker battery, charging, temperature,
  humidity, external voltage, distance today, tracker odometer, stationary since,
  position source, status, last fix, last contact) and binary sensors (online, moving,
  ignition when reported).
- Alarm event entity: every new alarm once, also across restarts.
- Config flow with sign-in check, re-authentication and poll interval option.
- Exponential back-off up to 15 minutes; entities unavailable after three failed rounds.
- New trackers are added without a reload; trackers that left the account can be removed.
- Diagnostics without secrets or personal data.
