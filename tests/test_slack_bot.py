"""Tests for the Slack bot module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ghostinthemini import slack_bot
from ghostinthemini.slack_bot import (
    create_app,
    get_allowed_user_ids,
    store_allowed_users,
    store_secret,
)


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------


def test_store_secret_writes_to_keyring():
    """store_secret calls keyring.set_password with the correct args."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        store_secret("slack_bot_token", "xoxb-fake")
        mock_keyring.set_password.assert_called_once_with(
            "ghostinthemini", "slack_bot_token", "xoxb-fake"
        )


def test_store_allowed_users_writes_json_list():
    """store_allowed_users serialises user IDs as JSON in keyring."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        store_allowed_users(["U01AAA", "U02BBB"])
        mock_keyring.set_password.assert_called_once_with(
            "ghostinthemini",
            "slack_allowed_user_ids",
            json.dumps(["U01AAA", "U02BBB"]),
        )


def test_get_allowed_user_ids_returns_set():
    """get_allowed_user_ids parses the stored JSON into a set."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = json.dumps(["U01AAA", "U02BBB"])
        result = get_allowed_user_ids()
        assert result == {"U01AAA", "U02BBB"}


def test_get_allowed_user_ids_returns_empty_when_unset():
    """get_allowed_user_ids returns an empty set when nothing is stored."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        result = get_allowed_user_ids()
        assert result == set()


# ---------------------------------------------------------------------------
# create_app — startup validation
# ---------------------------------------------------------------------------


def test_create_app_raises_without_bot_token():
    """create_app raises RuntimeError if bot token is missing from keyring."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        with pytest.raises(RuntimeError, match="Slack bot token"):
            create_app()


def test_create_app_raises_without_allowed_users():
    """create_app raises RuntimeError if no allowed users are configured."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        def side_effect(service, key):
            if key == "slack_bot_token":
                return "xoxb-fake-token"
            return None  # no allowed users
        mock_keyring.get_password.side_effect = side_effect

        with pytest.raises(RuntimeError, match="No allowed Slack user IDs"):
            create_app()


# ---------------------------------------------------------------------------
# Authorisation middleware
# ---------------------------------------------------------------------------


def test_authorised_user_passes_middleware():
    """Messages from allowlisted users are forwarded to handlers."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        def side_effect(service, key):
            if key == "slack_bot_token":
                return "xoxb-fake-token"
            if key == "slack_allowed_user_ids":
                return json.dumps(["U_ALLOWED"])
            return None
        mock_keyring.get_password.side_effect = side_effect

        with patch("ghostinthemini.slack_bot.App") as mock_app_cls:
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app

            create_app()

            # Find the middleware function that was registered
            middleware_call = [
                c for c in mock_app.middleware.call_args_list
            ]
            assert len(middleware_call) == 1

            middleware_fn = middleware_call[0][0][0]

            # Simulate an authorised user event
            mock_next = MagicMock()
            mock_logger = MagicMock()
            body = {"event": {"user": "U_ALLOWED"}}

            middleware_fn(body, mock_next, mock_logger)
            mock_next.assert_called_once()


def test_unauthorised_user_blocked_by_middleware():
    """Messages from non-allowlisted users are silently dropped."""
    with patch("ghostinthemini.slack_bot.keyring") as mock_keyring:
        def side_effect(service, key):
            if key == "slack_bot_token":
                return "xoxb-fake-token"
            if key == "slack_allowed_user_ids":
                return json.dumps(["U_ALLOWED"])
            return None
        mock_keyring.get_password.side_effect = side_effect

        with patch("ghostinthemini.slack_bot.App") as mock_app_cls:
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app

            create_app()

            middleware_fn = mock_app.middleware.call_args_list[0][0][0]

            # Simulate an UNauthorised user event
            mock_next = MagicMock()
            mock_logger = MagicMock()
            body = {"event": {"user": "U_INTRUDER"}}

            middleware_fn(body, mock_next, mock_logger)
            mock_next.assert_not_called()
            mock_logger.warning.assert_called_once()
