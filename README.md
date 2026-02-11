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
Credentials are stored securely in your system keyring (macOS Keychain, Windows Credential Locker, etc.) — **not** as plain-text JSON files.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the **Google Calendar API** (APIs & Services → Library)
4. Configure the **OAuth consent screen** (APIs & Services → OAuth consent screen)
   - Set the user type to **External**
   - Add yourself as a **test user** under Audience
5. Create **OAuth 2.0 credentials** (APIs & Services → Credentials → Create Credentials → OAuth client ID)
   - Application type: **Desktop app**
   - Add the scope: `https://www.googleapis.com/auth/calendar`
6. Download the JSON file, then import it into your system keyring:

```bash
python -m ghostinthemini.scheduler --import-credentials path/to/credentials.json
```

7. **Delete the downloaded JSON file** — it's now safely stored in your keyring

On first run, a browser window will open asking you to authorize access. After you approve, the OAuth token is saved to your system keyring and reused automatically.

> **Migrating from an older version?** If you already have a `token.json`, import it too:
>
> ```bash
> python -m ghostinthemini.scheduler --import-token token.json
> ```
>
> Then delete both `credentials.json` and `token.json`.

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
