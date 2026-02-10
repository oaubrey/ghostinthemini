"""Tests for the scheduler module."""

from unittest.mock import MagicMock, patch

import pytest

from ghostinthemini import scheduler
from ghostinthemini.scheduler import SchedulingError, validate_llm_result


# ---------------------------------------------------------------------------
# get_calendar_service
# ---------------------------------------------------------------------------


def test_get_calendar_service_missing_credentials(tmp_path):
    """Raises FileNotFoundError when credentials.json does not exist."""
    with (
        patch.object(scheduler, "TOKEN_PATH", str(tmp_path / "token.json")),
        patch.object(scheduler, "CREDENTIALS_PATH", str(tmp_path / "nope.json")),
    ):
        with pytest.raises(FileNotFoundError, match="credentials.json not found"):
            scheduler.get_calendar_service()


def test_get_calendar_service_uses_existing_token(tmp_path):
    """Loads credentials from token.json when it exists and is valid."""
    fake_creds = MagicMock()
    fake_creds.valid = True

    with (
        patch.object(scheduler, "TOKEN_PATH", str(tmp_path / "token.json")),
        patch("os.path.exists", return_value=True),
        patch(
            "ghostinthemini.scheduler.Credentials.from_authorized_user_file",
            return_value=fake_creds,
        ),
        patch("ghostinthemini.scheduler.build") as mock_build,
    ):
        scheduler.get_calendar_service()
        mock_build.assert_called_once_with("calendar", "v3", credentials=fake_creds)


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
