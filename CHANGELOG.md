# Changelog

## [0.1.2] - 2026-07-15

Fixes-only release. Restores the integration after Hargassner rebuilt the Connect
portal, and realigns the parameter mapping with the current API. Feature requests
(French translation #2, fresh-water circulation #5) are deferred to v0.2.0.

### Fixed
- **Integration broken for all users (#3, #4).** Hargassner migrated the Connect
  portal to a hashed Vite build, so the old credential source `/js/app.js` now
  returns HTTP 404 and both setup and startup failed. The OAuth *client*
  credentials (public application identifiers, not user secrets) are now built in,
  removing the dependency on scraping a frontend that can be rebuilt at any time.
- **Self-healing fallback fixed for the new portal.** If a built-in client
  credential is ever rejected, the integration re-extracts it from the live JS
  bundle, discovered via the Vite manifest (`/build/manifest.json`) with HTML and
  legacy fallbacks, and extracted by call-site anchor rather than minified name.
- **Silent setup failures (#4).** Actual HTTP status codes and exceptions are now
  logged. A browser `User-Agent` and the `Branding: BRANDING_HARGASSNER` header
  are sent on every request.
- **Incorrect / defaulted readings.** The widget parser was rewritten to match the
  current API payload. Pellet stock is now read from the `HEATER` widget (was
  looking under `BOILER`) with the correct maximum (7874 kg), and boiler/DHW
  temperature is read from `boiler_temperature_target`.
- **Translation state keys** for select entities are now consistently lowercase in
  both `en` and `de` (the German file previously used uppercase `MODE_*` keys that
  would not resolve).

### Changed
- **Entities are now created dynamically** from the live `parameters` of each
  widget, with range/step/options taken from the API. Controls a device does not
  expose are no longer created (so no writes to non-existent endpoints), and
  advanced parameters reappear automatically on devices that do expose them.
- Writes now target each parameter's own `resource` URL returned by the API,
  instead of hardcoded paths.

### Added
- **Number** — Hot Water Temperature (domestic hot-water target, 10–84 °C).
- **Select** — Heater Program (Off / Boiler / Automatic / Stop firing).
- **Select** — Heating Mode now includes the one-time bridge modes
  (`One-time Heating`, `One-time Reduction`).
- **Button** — Acknowledge Events (confirm all pending events/warnings).

### Removed / retired
- The advanced heating-circuit controls (`room_temperature_heating`,
  `room_temperature_reduction`, `steepness`, and the three `deactivation_limit_*`
  numbers) and the `bathroom_heating` select are now created only when the device
  actually exposes them. On boilers that do not (e.g. Classic 40), they no longer
  appear; existing stale entities can be deleted from the entity registry.

### Thanks
- [@lithium73fr](https://github.com/lithium73fr) — the
  [lithium73fr/hargassner-ha](https://github.com/lithium73fr/hargassner-ha)
  integration was an invaluable reference for the current API shape, the
  dynamic-entity approach, and the auth/branding details.
- Everyone who reported and discussed issues: [@karlspace](https://github.com/karlspace),
  [@vanouzbek](https://github.com/vanouzbek), [@Offerel](https://github.com/Offerel),
  [@abarwirsch](https://github.com/abarwirsch), and [@eltron02](https://github.com/eltron02).

---

## [0.1.1] - 2026-03-01

### Fixed
- Translation keys for `heating_mode`, `solar_mode`, and `bathroom_heating` select entities changed to lowercase (`mode_automatic`, `mode_heating`, etc.) to comply with Home Assistant translation key rules (`[a-z0-9-_]+`)
- `manifest.json` keys re-ordered to comply with Hassfest requirements (`domain`, `name`, then alphabetical)
- Hassfest GitHub Actions workflow corrected to include `actions/checkout@v4` step (was failing due to missing repo checkout)

### Added
- HACS Validation GitHub Action (`.github/workflows/validate.yaml`)
- Hassfest GitHub Action (`.github/workflows/hassfest.yaml`)
- Brand icon (`custom_components/hargassner_control/brand/icon.png`) — 256×256 iOS-style fire icon for HACS store display

---

## [0.1.0] - 2026-03-01

### Initial Release

#### Features
- OAuth 2.0 ROPC authentication — credentials extracted automatically from the Hargassner Connect web portal (`/js/app.js`), no hardcoded secrets
- Auto-discovery of installations linked to the account
- Config flow UI with multi-installation support
- Options flow to update credentials without re-adding the integration

#### Entities
- **Select** — Heating Mode (`Automatic`, `Heating`, `Reduction`, `Off`)
- **Select** — Solar Mode (`On`, `Off`)
- **Select** — Bathroom Heating (`On`, `Off`)
- **Number** — Room Temperature (Heating setpoint)
- **Number** — Room Temperature (Reduction setpoint)
- **Number** — Temperature Correction
- **Number** — Heating Curve Steepness
- **Number** — Heating Off Temperature
- **Number** — Day Setback Off Temperature
- **Number** — Night Setback Off Temperature
- **Number** — Pellet Stock (kg)
- **Button** — Force Hot Water Charge
- **Sensor** — Last Sync timestamp
- **Sensor** — Connection Status

#### Notes
- Boiler telemetry sensors (temperatures, states) are intentionally omitted — use the companion [BauerGroup IP-HargassnerIntegration](https://github.com/BauerGroup/IP-HargassnerIntegration) which provides 228 live sensors via local polling
- All writes go directly to the Hargassner Connect cloud API
