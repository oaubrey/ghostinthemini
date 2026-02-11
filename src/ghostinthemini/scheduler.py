"""Scheduler module - uses LangChain + Ollama to manage Google Calendar."""

import datetime
import json

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from ghostinthemini.config import (
    KEYRING_CREDENTIALS_KEY,
    KEYRING_SERVICE,
    KEYRING_TOKEN_KEY,
    MODEL,
    SCOPES,
    TIMEZONE,
    TIMEZONE_NAME,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SchedulingError(Exception):
    """Raised when the scheduling pipeline fails."""


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------

def import_credentials(filepath: str) -> None:
    """Read a Google OAuth client-secrets JSON file and store it in keyring.

    This is a one-time migration step.  After importing, the JSON file
    can (and should) be deleted.
    """
    with open(filepath) as f:
        data = f.read()

    # Validate that it's parseable JSON with expected structure
    parsed = json.loads(data)
    if "installed" not in parsed and "web" not in parsed:
        raise ValueError(
            "Invalid credentials file — expected an 'installed' or 'web' key. "
            "Download the correct OAuth client JSON from Google Cloud Console."
        )

    keyring.set_password(KEYRING_SERVICE, KEYRING_CREDENTIALS_KEY, data)
    print(f"✅ Client credentials stored in keyring (service={KEYRING_SERVICE!r}).")
    print("   You can now delete the JSON file.")


def import_token(filepath: str) -> None:
    """Read an existing token.json file and store it in keyring.

    This is a one-time migration step for users who already have a
    token.json from a previous run.
    """
    with open(filepath) as f:
        data = f.read()

    # Quick sanity check
    parsed = json.loads(data)
    if "token" not in parsed and "refresh_token" not in parsed:
        raise ValueError("File does not look like a Google OAuth token.")

    keyring.set_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY, data)
    print(f"✅ OAuth token stored in keyring (service={KEYRING_SERVICE!r}).")
    print("   You can now delete the JSON file.")


# ---------------------------------------------------------------------------
# Google Calendar helpers
# ---------------------------------------------------------------------------

def get_calendar_service():
    """Authenticate with Google and return a Calendar API service object.

    Credentials and tokens are stored in the system keyring instead of
    plain-text JSON files.  On first run this opens a browser for OAuth
    consent; after that the refresh token in keyring is reused
    automatically.
    """
    creds = None

    # Try to load an existing token from keyring
    token_json = keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
    if token_json:
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Need to run the OAuth flow — fetch client credentials from keyring
            client_json = keyring.get_password(
                KEYRING_SERVICE, KEYRING_CREDENTIALS_KEY
            )
            if not client_json:
                raise RuntimeError(
                    "No Google OAuth client credentials found in keyring.\n"
                    "Download the JSON from Google Cloud Console → "
                    "APIs & Services → Credentials:\n"
                    "  https://console.cloud.google.com/apis/credentials\n\n"
                    "Then import it with:\n"
                    "  python -m ghostinthemini.scheduler --import-credentials "
                    "<path/to/credentials.json>"
                )
            client_config = json.loads(client_json)
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist the (possibly refreshed) token in keyring
        keyring.set_password(
            KEYRING_SERVICE, KEYRING_TOKEN_KEY, creds.to_json()
        )

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

    if len(sys.argv) > 1 and sys.argv[1] == "--import-credentials":
        if len(sys.argv) < 3:
            print("Usage: python -m ghostinthemini.scheduler "
                  "--import-credentials <path/to/credentials.json>")
            sys.exit(1)
        import_credentials(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "--import-token":
        if len(sys.argv) < 3:
            print("Usage: python -m ghostinthemini.scheduler "
                  "--import-token <path/to/token.json>")
            sys.exit(1)
        import_token(sys.argv[2])
    else:
        if len(sys.argv) > 1:
            task = " ".join(sys.argv[1:])
        else:
            task = input("What do you want to schedule? ")
        schedule_task(task)
