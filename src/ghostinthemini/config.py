"""Shared configuration for ghostinthemini."""

from zoneinfo import ZoneInfo

# Google Calendar OAuth
SCOPES = ["https://www.googleapis.com/auth/calendar"]
KEYRING_SERVICE = "ghostinthemini"
KEYRING_CREDENTIALS_KEY = "google_client_credentials"
KEYRING_TOKEN_KEY = "google_oauth_token"

# Slack (Socket Mode)
KEYRING_SLACK_BOT_TOKEN_KEY = "slack_bot_token"
KEYRING_SLACK_APP_TOKEN_KEY = "slack_app_token"
KEYRING_SLACK_ALLOWED_USERS_KEY = "slack_allowed_user_ids"

# Model used by the Ghost
MODEL = "qwen3-coder:30b-a3b-q4_K_M"

# Timezone - Pacific Time (handles PST/PDT automatically)
TIMEZONE_NAME = "America/Los_Angeles"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
