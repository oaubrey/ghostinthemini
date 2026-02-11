"""Shared configuration for ghostinthemini."""

from zoneinfo import ZoneInfo

# Google Calendar OAuth
SCOPES = ["https://www.googleapis.com/auth/calendar"]
KEYRING_SERVICE = "ghostinthemini"
KEYRING_CREDENTIALS_KEY = "google_client_credentials"
KEYRING_TOKEN_KEY = "google_oauth_token"

# Model used by the Ghost
MODEL = "qwen3-coder:30b-a3b-q4_K_M"

# Timezone - Pacific Time (handles PST/PDT automatically)
TIMEZONE_NAME = "America/Los_Angeles"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
