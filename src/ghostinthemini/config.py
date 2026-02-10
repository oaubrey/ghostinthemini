"""Shared configuration for ghostinthemini."""

import os
from zoneinfo import ZoneInfo

# Project root (two levels up from this file: config.py -> ghostinthemini/ -> src/ -> root)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Google Calendar OAuth
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_PATH = os.path.join(PROJECT_ROOT, "credentials.json")
TOKEN_PATH = os.path.join(PROJECT_ROOT, "token.json")

# Model used by the Ghost
MODEL = "qwen3-coder:30b-a3b-q4_K_M"

# Timezone - Pacific Time (handles PST/PDT automatically)
TIMEZONE_NAME = "America/Los_Angeles"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
