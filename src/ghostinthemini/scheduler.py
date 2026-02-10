"""Scheduler module - uses LangChain + Ollama to manage Google Calendar."""

import datetime
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from ghostinthemini.config import (
    CREDENTIALS_PATH,
    MODEL,
    SCOPES,
    TIMEZONE,
    TIMEZONE_NAME,
    TOKEN_PATH,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SchedulingError(Exception):
    """Raised when the scheduling pipeline fails."""


# ---------------------------------------------------------------------------
# Google Calendar helpers
# ---------------------------------------------------------------------------

def get_calendar_service():
    """Authenticate with Google and return a Calendar API service object.

    On first run this opens a browser for OAuth consent.  After that,
    the refresh token in token.json is reused automatically.
    """
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    "credentials.json not found at project root.\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials:\n"
                    "https://console.cloud.google.com/apis/credentials\n"
                    "Then place it at: " + CREDENTIALS_PATH
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_schedule(days_ahead: int = 7) -> list[dict]:
    """Fetch upcoming calendar events for the next *days_ahead* days.

    Returns a list of dicts with keys: summary, start, end, description.
    """
    service = get_calendar_service()

    now = datetime.datetime.now(TIMEZONE)
    time_min = now.isoformat()
    time_max = (now + datetime.timedelta(days=days_ahead)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])

    schedule = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        end = event["end"].get("dateTime", event["end"].get("date"))
        schedule.append(
            {
                "summary": event.get("summary", "(No title)"),
                "start": start,
                "end": end,
                "description": event.get("description", ""),
            }
        )

    return schedule


def create_event(summary: str, start: str, end: str, description: str = "") -> dict:
    """Create a new event on the primary Google Calendar.

    *start* and *end* should be ISO-8601 datetime strings.
    Returns the created event resource from the API.
    """
    service = get_calendar_service()

    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": TIMEZONE_NAME},
        "end": {"dateTime": end, "timeZone": TIMEZONE_NAME},
    }

    created = (
        service.events()
        .insert(calendarId="primary", body=event_body)
        .execute()
    )
    return created


# ---------------------------------------------------------------------------
# LLM result validation
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"summary", "start", "end"}


def validate_llm_result(result: dict) -> None:
    """Raise SchedulingError if the LLM result is missing keys or has bad datetimes."""
    missing = REQUIRED_KEYS - result.keys()
    if missing:
        raise SchedulingError(
            f"LLM response missing required key(s): {', '.join(sorted(missing))}. "
            f"Got: {result}"
        )

    for key in ("start", "end"):
        value = result[key]
        try:
            datetime.datetime.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise SchedulingError(
                f"LLM returned an invalid datetime for '{key}': {value!r}"
            ) from exc

    start_dt = datetime.datetime.fromisoformat(result["start"])
    end_dt = datetime.datetime.fromisoformat(result["end"])
    if end_dt <= start_dt:
        raise SchedulingError(
            f"LLM returned an end time ({result['end']}) that is not after "
            f"the start time ({result['start']})"
        )


# ---------------------------------------------------------------------------
# LangChain scheduling chain
# ---------------------------------------------------------------------------

def schedule_task(
    task_description: str,
    duration_minutes: int = 60,
    days_ahead: int = 7,
) -> dict:
    """Ask the Ghost to find the best time slot and create the calendar event.

    1. Pulls the current schedule from Google Calendar.
    2. Sends schedule + task to the local LLM via LangChain.
    3. Validates the LLM response.
    4. Creates the event on Google Calendar.

    *duration_minutes* is used as a fallback when the user's task
    description does not include explicit start/end times or a duration.

    Returns the parsed scheduling result dict.

    Raises
    ------
    SchedulingError
        If the LLM is unreachable, returns bad data, or the event
        cannot be created.
    """
    # 1 ── Fetch current schedule
    try:
        current_schedule = get_schedule(days_ahead=days_ahead)
    except Exception as exc:
        raise SchedulingError(
            "Failed to fetch your calendar. Is your Google token valid?"
        ) from exc

    now = datetime.datetime.now(TIMEZONE)

    # 2 ── Build the LangChain chain
    llm = ChatOllama(model=MODEL, temperature=0)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a scheduling assistant running locally on a Mac Mini. "
                "Given the user's current calendar and a new task to schedule, "
                "find the best available time slot.\n\n"
                "Rules:\n"
                "- If the user specifies exact times or a duration, use them\n"
                "- Otherwise, default to a {duration}-minute event\n"
                "- Schedule during reasonable hours (9:00 AM – 6:00 PM)\n"
                "- Never overlap with existing events\n"
                "- Prefer the earliest available slot\n"
                "- Use ISO-8601 datetime format (YYYY-MM-DDTHH:MM:SS)\n\n"
                "Respond ONLY with valid JSON in this exact format:\n"
                '{{"summary": "task name", '
                '"start": "YYYY-MM-DDTHH:MM:SS", '
                '"end": "YYYY-MM-DDTHH:MM:SS", '
                '"reasoning": "one-sentence explanation"}}',
            ),
            (
                "user",
                "Current date/time: {current_time}\n\n"
                "My schedule for the next {days_ahead} days:\n{schedule}\n\n"
                "Please schedule this task: {task}",
            ),
        ]
    )

    parser = JsonOutputParser()
    chain = prompt | llm | parser

    # Format the schedule for the prompt
    if current_schedule:
        schedule_text = "\n".join(
            f"  - {e['summary']}: {e['start']} → {e['end']}"
            for e in current_schedule
        )
    else:
        schedule_text = "  (No events scheduled)"

    # 3 ── Run the chain
    try:
        result = chain.invoke(
            {
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "days_ahead": days_ahead,
                "schedule": schedule_text,
                "duration": duration_minutes,
                "task": task_description,
            }
        )
    except Exception as exc:
        raise SchedulingError(
            "LLM call failed. Is Ollama running with the "
            f"'{MODEL}' model pulled?"
        ) from exc

    # 4 ── Validate the LLM response
    validate_llm_result(result)

    # 5 ── Create the event on Google Calendar
    try:
        created_event = create_event(
            summary=result.get("summary", task_description),
            start=result["start"],
            end=result["end"],
            description=(
                "Scheduled by GhostInTheMini\n"
                f"Reasoning: {result.get('reasoning', '')}"
            ),
        )
    except SchedulingError:
        raise
    except Exception as exc:
        raise SchedulingError(
            "Google Calendar rejected the event. Check the start/end times."
        ) from exc

    print(f"✅ Event created: {result.get('summary', task_description)}")
    print(f"   Start:  {result['start']}")
    print(f"   End:    {result['end']}")
    print(f"   Reason: {result.get('reasoning', 'N/A')}")
    print(f"   Link:   {created_event.get('htmlLink', 'N/A')}")

    return result


# ---------------------------------------------------------------------------
# Quick CLI usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = input("What do you want to schedule? ")

    schedule_task(task)
