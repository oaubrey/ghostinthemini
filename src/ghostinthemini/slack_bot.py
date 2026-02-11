"""Slack bot — Socket Mode interface to the Ghost scheduler.

Lets you DM the bot or @-mention it in a channel to schedule tasks
from your phone (or anywhere Slack runs).

Security:
    - Runs via Socket Mode (no public URL / inbound ports required).
    - Bot token and app-level token are stored in the system keyring.
    - Only Slack user IDs in the allowlist can trigger scheduling.
"""

import json
import logging
import sys

import keyring
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from ghostinthemini.config import (
    KEYRING_SERVICE,
    KEYRING_SLACK_ALLOWED_USERS_KEY,
    KEYRING_SLACK_APP_TOKEN_KEY,
    KEYRING_SLACK_BOT_TOKEN_KEY,
)
from ghostinthemini.scheduler import SchedulingError, schedule_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------

def _get_required_token(key: str, label: str) -> str:
    """Fetch a token from keyring or raise with a helpful message."""
    value = keyring.get_password(KEYRING_SERVICE, key)
    if not value:
        raise RuntimeError(
            f"No {label} found in keyring.\n"
            f"Store it with:\n"
            f"  python -m ghostinthemini.slack_bot --store {key} <token>"
        )
    return value


def get_allowed_user_ids() -> set[str]:
    """Return the set of Slack user IDs allowed to use the bot."""
    raw = keyring.get_password(KEYRING_SERVICE, KEYRING_SLACK_ALLOWED_USERS_KEY)
    if not raw:
        return set()
    return set(json.loads(raw))


def store_secret(key: str, value: str) -> None:
    """Write a single secret into the keyring."""
    keyring.set_password(KEYRING_SERVICE, key, value)
    # Don't echo the value — just confirm storage
    print(f"✅ Stored in keyring: service={KEYRING_SERVICE!r}, key={key!r}")


def store_allowed_users(user_ids: list[str]) -> None:
    """Store the Slack user-ID allowlist in keyring (replaces existing)."""
    keyring.set_password(
        KEYRING_SERVICE,
        KEYRING_SLACK_ALLOWED_USERS_KEY,
        json.dumps(user_ids),
    )
    print(f"✅ Allowed user IDs stored: {user_ids}")


# ---------------------------------------------------------------------------
# Bot construction
# ---------------------------------------------------------------------------

def create_app() -> App:
    """Build and return the Slack Bolt app (does NOT start it)."""
    bot_token = _get_required_token(
        KEYRING_SLACK_BOT_TOKEN_KEY, "Slack bot token (xoxb-…)"
    )
    allowed_users = get_allowed_user_ids()
    if not allowed_users:
        raise RuntimeError(
            "No allowed Slack user IDs configured.\n"
            "Add at least your own user ID:\n"
            "  python -m ghostinthemini.slack_bot "
            "--allow-users U01ABCDEF,U02XYZABC"
        )

    app = App(token=bot_token)

    # -- Middleware: reject unauthorised users early -------------------------

    @app.middleware
    def authorize_user(body, next, logger):  # noqa: A002
        """Drop events from users not on the allowlist."""
        event = body.get("event", {})
        user_id = event.get("user")
        # Let non-event payloads (like healthchecks) through
        if not user_id:
            next()
            return
        if user_id not in allowed_users:
            logger.warning("Blocked request from unauthorised user %s", user_id)
            return
        next()

    # -- Direct messages ----------------------------------------------------

    @app.event("message")
    def handle_dm(event, say):
        """Respond to a direct message with a scheduling attempt."""
        text = (event.get("text") or "").strip()
        if not text:
            return

        # Ignore bot's own messages and message_changed subtypes
        if event.get("bot_id") or event.get("subtype"):
            return

        say("👻 On it — let me check your calendar…")

        try:
            result = schedule_task(text)
            say(
                f"✅ *{result.get('summary', text)}* scheduled!\n"
                f">  Start: {result['start']}\n"
                f">  End:   {result['end']}\n"
                f">  Reason: {result.get('reasoning', 'N/A')}"
            )
        except SchedulingError as exc:
            say(f"⚠️ Couldn't schedule that: {exc}")
        except Exception:
            logger.exception("Unexpected error in handle_dm")
            say("❌ Something went wrong. Check the Ghost's logs.")

    # -- @mentions in channels ----------------------------------------------

    @app.event("app_mention")
    def handle_mention(event, say):
        """Respond to an @ghost mention in a channel."""
        raw = (event.get("text") or "").strip()
        # Strip the bot mention prefix (e.g. "<@U0ABC> schedule …")
        parts = raw.split(">", 1)
        text = parts[1].strip() if len(parts) > 1 else raw

        if not text:
            say("👻 You rang? Tell me what to schedule.")
            return

        say("👻 On it — let me check your calendar…")

        try:
            result = schedule_task(text)
            say(
                f"✅ *{result.get('summary', text)}* scheduled!\n"
                f">  Start: {result['start']}\n"
                f">  End:   {result['end']}\n"
                f">  Reason: {result.get('reasoning', 'N/A')}"
            )
        except SchedulingError as exc:
            say(f"⚠️ Couldn't schedule that: {exc}")
        except Exception:
            logger.exception("Unexpected error in handle_mention")
            say("❌ Something went wrong. Check the Ghost's logs.")

    return app


def start() -> None:
    """Start the Slack bot in Socket Mode (blocking)."""
    app = create_app()
    app_token = _get_required_token(
        KEYRING_SLACK_APP_TOKEN_KEY, "Slack app-level token (xapp-…)"
    )
    print("👻 Ghost Slack bot starting in Socket Mode…")
    handler = SocketModeHandler(app, app_token)
    handler.start()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_usage() -> None:
    print(
        "Usage:\n"
        "  python -m ghostinthemini.slack_bot                   "
        "  # start the bot\n"
        "  python -m ghostinthemini.slack_bot --store KEY VALUE "
        "  # store a secret\n"
        "  python -m ghostinthemini.slack_bot --allow-users ID[,ID…]"
        "  # set allowed users"
    )


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        start()
    elif args[0] == "--store" and len(args) == 3:
        store_secret(args[1], args[2])
    elif args[0] == "--allow-users" and len(args) == 2:
        ids = [uid.strip() for uid in args[1].split(",") if uid.strip()]
        store_allowed_users(ids)
    else:
        _print_usage()
        sys.exit(1)
