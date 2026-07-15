"""Constants for the Hargassner Control integration."""
from __future__ import annotations

DOMAIN = "hargassner_control"

# Config entry keys
CONF_INSTALLATION_ID = "installation_id"

# Coordinator update interval (minutes)
SCAN_INTERVAL_MINUTES = 15

# --- Portal / API endpoints ---
PORTAL_URL = "https://web.hargassner.at"
API_URL = f"{PORTAL_URL}/api"
TOKEN_URL = f"{PORTAL_URL}/oauth/token"
MANIFEST_URL = f"{PORTAL_URL}/build/manifest.json"

# --- Public OAuth *client* credentials ---
# These are NOT user secrets. They are the OAuth client_id/client_secret shipped
# inside every copy of the Hargassner Connect web app and Android app, used
# together with the user's own email + password (ROPC "password" grant).
#
# They are hardcoded here on purpose: the previous approach scraped them from
# `/js/app.js` on every startup, which broke completely when Hargassner migrated
# the portal to a hashed Vite build (GitHub issues #3 and #4). Hardcoding the
# public values makes the integration resilient to frontend rebuilds.
#
# If Hargassner ever *rotate* these values, `api_client` automatically falls back
# to re-extracting them from the live JS bundle (see `_async_scrape_credentials`).
DEFAULT_CLIENT_ID = "1"
DEFAULT_CLIENT_SECRET = "aSYsAYj7Gsl5v9tPEDdS1hhXTUezgJk1NhOZ1bHR"

# Headers sent on every request.
# Branding matches the official client; User-Agent avoids non-browser WAF
# heuristics on the portal edge.
APP_BRANDING = "BRANDING_HARGASSNER"
USER_AGENT = "hargassner-ha/0.1.2 (+https://github.com/knirzinger/hargassner-ha)"

# Widget type prefixes (the API suffixes some, e.g. HEATING_CIRCUIT_RADIATOR).
WIDGET_HEATER = "HEATER"
WIDGET_BOILER = "BOILER"
WIDGET_BUFFER = "BUFFER"
WIDGET_HEATING_CIRCUIT = "HEATING_CIRCUIT"
WIDGET_EVENTS = "EVENTS"
