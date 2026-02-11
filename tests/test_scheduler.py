"""Tests for the scheduler module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ghostinthemini import scheduler
from ghostinthemini.scheduler import (
    SchedulingError,
    import_credentials,
    import_token,
    validate_llm_result,
)


# ---------------------------------------------------------------------------
# get_calendar_service
# ---------------------------------------------------------------------------


def test_get_calendar_service_missing_credentials():
    """Raises RuntimeError when no client credentials exist in keyring."""
    with patch("ghostinthemini.scheduler.keyring") as mock_keyring:
        # No token, no credentials in keyring
        mock_keyring.get_password.return_value = None
        with pytest.raises(RuntimeError, match="No Google OAuth client credentials"):
            scheduler.get_calendar_service()


def test_get_calendar_service_uses_existing_token():
    """Loads credentials from keyring when a valid token exists."""
    fake_creds = MagicMock()
    fake_creds.valid = True

    fake_token_data = json.dumps({
        "token": "ya29.fake",
        "refresh_token": "1//fake",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "fake.apps.googleusercontent.com",
        "client_secret": "fake-secret",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
    })

    with (
        patch("ghostinthemini.scheduler.keyring") as mock_keyring,
        patch(
            "ghostinthemini.scheduler.Credentials.from_authorized_user_info",
            return_value=fake_creds,
        ),
        patch("ghostinthemini.scheduler.build") as mock_build,
    ):
        mock_keyring.get_password.return_value = fake_token_data
        scheduler.get_calendar_service()
        mock_build.assert_called_once_with("calendar", "v3", credentials=fake_creds)


# ---------------------------------------------------------------------------
# import_credentials / import_token
# ---------------------------------------------------------------------------


def test_import_credentials_stores_in_keyring(tmp_path):
    """import_credentials reads a JSON file and stores it in keyring."""
    creds_file = tmp_path / "credentials.json"
    creds_data = json.dumps({"installed": {"client_id": "test", "client_secret": "s"}})
    creds_file.write_text(creds_data)

    with patch("ghostinthemini.scheduler.keyring") as mock_keyring:
        import_credentials(str(creds_file))
        mock_keyring.set_password.assert_called_once_with(
            "ghostinthemini", "google_client_credentials", creds_data
        )


def test_import_credentials_rejects_bad_json(tmp_path):
    """import_credentials raises ValueError for invalid credential files."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"not_right": True}))

    with patch("ghostinthemini.scheduler.keyring"):
        with pytest.raises(ValueError, match="Invalid credentials file"):
            import_credentials(str(bad_file))


def test_import_token_stores_in_keyring(tmp_path):
    """import_token reads a token JSON file and stores it in keyring."""
    token_file = tmp_path / "token.json"
    token_data = json.dumps({"token": "ya29.fake", "refresh_token": "1//fake"})
    token_file.write_text(token_data)

    with patch("ghostinthemini.scheduler.keyring") as mock_keyring:
        import_token(str(token_file))
        mock_keyring.set_password.assert_called_once_with(
            "ghostinthemini", "google_oauth_token", token_data
        )


# ---------------------------------------------------------------------------
# get_schedule
# ---------------------------------------------------------------------------


FAKE_EVENTS = {
    "items": [
        {
            "summary": "Team standup",
            "start": {"dateTime": "2026-02-09T09:00:00-05:00"},
            "end": {"dateTime": "2026-02-09T09:30:00-05:00"},
            "description": "Daily sync",
        },
        {
            "summary": "Lunch",
            "start": {"dateTime": "2026-02-09T12:00:00-05:00"},
            "end": {"dateTime": "2026-02-09T13:00:00-05:00"},
        },
    ]
}


def mock_calendar_service(fake_events):
    """Return a MagicMock that behaves like the Calendar API service."""
    service = MagicMock()
    service.events().list().execute.return_value = fake_events
    return service


def test_get_schedule_returns_formatted_events():
    """get_schedule returns a list of dicts with expected keys."""
    service = mock_calendar_service(FAKE_EVENTS)

    with patch.object(scheduler, "get_calendar_service", return_value=service):
        result = scheduler.get_schedule(days_ahead=7)

    assert len(result) == 2
    assert result[0]["summary"] == "Team standup"
    assert result[0]["start"] == "2026-02-09T09:00:00-05:00"
    assert result[0]["end"] == "2026-02-09T09:30:00-05:00"
    assert result[0]["description"] == "Daily sync"
    assert result[1]["summary"] == "Lunch"
    assert result[1]["description"] == ""


def test_get_schedule_empty_calendar():
    """get_schedule returns an empty list when no events exist."""
    service = mock_calendar_service({"items": []})

    with patch.object(scheduler, "get_calendar_service", return_value=service):
        result = scheduler.get_schedule(days_ahead=7)

    assert result == []


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


def test_create_event_sends_correct_body():
    """create_event passes the right data to the Google Calendar API."""
    service = MagicMock()
    service.events().insert().execute.return_value = {
        "htmlLink": "https://calendar.google.com/event/abc123",
    }

    with patch.object(scheduler, "get_calendar_service", return_value=service):
        result = scheduler.create_event(
            summary="Deep work",
            start="2026-02-10T09:00:00",
            end="2026-02-10T11:00:00",
            description="Focus time",
        )

    # Verify insert was called with the correct arguments
    insert_calls = service.events().insert.call_args_list
    real_call = [c for c in insert_calls if c.kwargs.get("calendarId")][0]

    assert real_call.kwargs["calendarId"] == "primary"
    body = real_call.kwargs["body"]
    assert body["summary"] == "Deep work"
    assert body["description"] == "Focus time"
    assert body["start"]["dateTime"] == "2026-02-10T09:00:00"
    assert body["start"]["timeZone"] == "America/Los_Angeles"
    assert body["end"]["dateTime"] == "2026-02-10T11:00:00"
    assert body["end"]["timeZone"] == "America/Los_Angeles"
    assert result["htmlLink"] == "https://calendar.google.com/event/abc123"


# ---------------------------------------------------------------------------
# validate_llm_result
# ---------------------------------------------------------------------------


def testvalidate_llm_result_valid():
    """A well-formed result passes validation without error."""
    validate_llm_result(
        {
            "summary": "Focus time",
            "start": "2026-02-10T09:00:00",
            "end": "2026-02-10T10:00:00",
            "reasoning": "Morning is free.",
        }
    )


def testvalidate_llm_result_missing_key():
    """Raises SchedulingError when a required key is absent."""
    with pytest.raises(SchedulingError, match="missing required key.*start"):
        validate_llm_result({"summary": "Oops", "end": "2026-02-10T10:00:00"})


def testvalidate_llm_result_bad_datetime():
    """Raises SchedulingError when a datetime value is not valid ISO-8601."""
    with pytest.raises(SchedulingError, match="invalid datetime.*start"):
        validate_llm_result(
            {"summary": "Bad", "start": "not-a-date", "end": "2026-02-10T10:00:00"}
        )


def testvalidate_llm_result_end_before_start():
    """Raises SchedulingError when end is not after start."""
    with pytest.raises(SchedulingError, match="end time.*not after"):
        validate_llm_result(
            {
                "summary": "Backwards",
                "start": "2026-02-10T11:00:00",
                "end": "2026-02-10T09:00:00",
            }
        )


# ---------------------------------------------------------------------------
# schedule_task
# ---------------------------------------------------------------------------


def test_schedule_task_end_to_end(capsys):
    """schedule_task chains get_schedule → LLM → create_event correctly."""
    fake_schedule = [
        {
            "summary": "Meeting",
            "start": "2026-02-10T10:00:00",
            "end": "2026-02-10T11:00:00",
            "description": "",
        }
    ]

    llm_result = {
        "summary": "Write docs",
        "start": "2026-02-10T14:00:00",
        "end": "2026-02-10T15:00:00",
        "reasoning": "Afternoon is free after the meeting.",
    }

    fake_created_event = {
        "htmlLink": "https://calendar.google.com/event/xyz",
    }

    with (
        patch.object(scheduler, "get_schedule", return_value=fake_schedule),
        patch.object(scheduler, "create_event", return_value=fake_created_event) as mock_create,
        patch("ghostinthemini.scheduler.ChatOllama") as mock_llm_cls,
    ):
        # Make the LangChain chain return our fake result
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = llm_result
        # The chain is built as: prompt | llm | parser
        # We mock __or__ so the pipe operator returns our mock chain
        mock_llm_cls.return_value.__or__ = MagicMock(return_value=mock_chain)
        mock_prompt_pipe = MagicMock()
        mock_prompt_pipe.__or__ = MagicMock(return_value=mock_chain)

        with patch("ghostinthemini.scheduler.ChatPromptTemplate") as mock_prompt_cls:
            mock_prompt_cls.from_messages.return_value.__or__ = MagicMock(
                return_value=mock_prompt_pipe
            )
            mock_prompt_pipe.__or__ = MagicMock(return_value=mock_chain)

            result = scheduler.schedule_task("Write docs", duration_minutes=60)

    # Verify the LLM was called
    mock_chain.invoke.assert_called_once()

    # Verify create_event got the LLM's suggested times
    mock_create.assert_called_once_with(
        summary="Write docs",
        start="2026-02-10T14:00:00",
        end="2026-02-10T15:00:00",
        description="Scheduled by GhostInTheMini\nReasoning: Afternoon is free after the meeting.",
    )

    # Verify output
    out, _ = capsys.readouterr()
    assert "Event created" in out
    assert "Write docs" in out

    # Verify return value
    assert result["summary"] == "Write docs"
    assert result["reasoning"] == "Afternoon is free after the meeting."


def test_schedule_task_llm_failure_raises_scheduling_error():
    """schedule_task wraps LLM failures in a SchedulingError."""
    with (
        patch.object(scheduler, "get_schedule", return_value=[]),
        patch("ghostinthemini.scheduler.ChatOllama") as mock_llm_cls,
    ):
        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = ConnectionError("Ollama is not running")
        mock_llm_cls.return_value.__or__ = MagicMock(return_value=mock_chain)
        mock_prompt_pipe = MagicMock()
        mock_prompt_pipe.__or__ = MagicMock(return_value=mock_chain)

        with patch("ghostinthemini.scheduler.ChatPromptTemplate") as mock_prompt_cls:
            mock_prompt_cls.from_messages.return_value.__or__ = MagicMock(
                return_value=mock_prompt_pipe
            )
            mock_prompt_pipe.__or__ = MagicMock(return_value=mock_chain)

            with pytest.raises(SchedulingError, match="LLM call failed"):
                scheduler.schedule_task("some task")


def test_schedule_task_bad_llm_output_raises_scheduling_error():
    """schedule_task raises SchedulingError when the LLM returns invalid data."""
    bad_result = {"summary": "No times"}  # missing start and end

    with (
        patch.object(scheduler, "get_schedule", return_value=[]),
        patch("ghostinthemini.scheduler.ChatOllama") as mock_llm_cls,
    ):
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = bad_result
        mock_llm_cls.return_value.__or__ = MagicMock(return_value=mock_chain)
        mock_prompt_pipe = MagicMock()
        mock_prompt_pipe.__or__ = MagicMock(return_value=mock_chain)

        with patch("ghostinthemini.scheduler.ChatPromptTemplate") as mock_prompt_cls:
            mock_prompt_cls.from_messages.return_value.__or__ = MagicMock(
                return_value=mock_prompt_pipe
            )
            mock_prompt_pipe.__or__ = MagicMock(return_value=mock_chain)

            with pytest.raises(SchedulingError, match="missing required key"):
                scheduler.schedule_task("some task")
