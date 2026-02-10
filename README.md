# ghostinthemini

ahhhh! there's a ghost! and it's in my mac mini!!!

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Set up Google Calendar credentials

The scheduler needs OAuth credentials to access your Google Calendar.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the **Google Calendar API** (APIs & Services → Library)
4. Configure the **OAuth consent screen** (APIs & Services → OAuth consent screen)
   - Set the user type to **External**
   - Add yourself as a **test user** under Audience
5. Create **OAuth 2.0 credentials** (APIs & Services → Credentials → Create Credentials → OAuth client ID)
   - Application type: **Desktop app**
   - Add the scope: `https://www.googleapis.com/auth/calendar`
6. Download the JSON file and save it as `credentials.json` in the project root

> **Note:** `credentials.json` and `token.json` are gitignored and will not be committed.

On first run, a browser window will open asking you to authorize access. After you approve, a `token.json` file is saved and reused automatically.

### 4. Make sure Ollama is running

The ghost runs on a local Qwen model via [Ollama](https://ollama.com/). Make sure Ollama is running with the model pulled before using the scheduler.

## Run

```bash
# Pulse check — verify the ghost is awake
python3 -m ghostinthemini.main

# Schedule a task via Google Calendar
python3 -m ghostinthemini.scheduler

# Or pass the task directly
python3 -m ghostinthemini.scheduler "2 hour deep work session"
```

## Test

```bash
pytest
```
