# Changelog

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
