# Changelog

## 0.3.3 (2026-10-29)

Ready for Home Assistant 2026.11. Update through HACS (the Marketplace from 2026.11) and
restart Home Assistant; nothing needs to be set up again.

- README: installation now starts with searching for WhatsGPS in HACS (built in as the
  Marketplace from Home Assistant 2026.11), which lists it by default. Adding it as a
  custom repository is the fallback.
- Renaming an entity ID in Home Assistant 2026.11 and later happens in place, also for the
  alarm entity (before, Home Assistant removed and re-added it).

## 0.3.2 (2026-10-20)

- The integration has its own icon (`custom_components/whatsgps/brand/`), shown by Home
  Assistant 2026.3 and later. It is a neutral location pin, not the WhatsGPS logo.
- Validation runs the HACS action without exceptions.

## 0.3.1 (2026-10-19)

- Several alarms in one round now each become an event (before, only the last one did).
- Only a sign-in refused with HTTP 200 starts re-authentication; rate limiting (429),
  blocks (403) and a rejected appId/appKey are retried later. A refused password is
  remembered, so the integration never retries it (account lockout).
- No second sign-in when a token from a fresh sign-in is rejected.
- The alarm memory is stored per config entry and removed with it: removing and re-adding
  the integration does not replay old alarms. Memory from 0.3.0 is taken over.
- Options use Home Assistant's reload flow (the update-listener route stops working in
  2026.12).
- Odd values from the cloud count as a normal failed round instead of crashing the update.
- Diagnostics include only known, harmless fields (other fields by name only), also when
  the integration is not loaded; device removal is refused while it is not loaded.
- A warning in the log when the alarm list has an unexpected shape.
- The time zone is determined at every sign-in (daylight saving time).
- Unique ID falls back to the account name if the cloud sends no user ID.

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
