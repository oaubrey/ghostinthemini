# ghostinthemini

ahhhh! there's a ghost! and it's in my mac mini!!!

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Set up Google Calendar credentials

The scheduler needs OAuth credentials to access your Google Calendar.
All secrets are stored in your **system keyring** (macOS Keychain) — never as plain-text files or environment variables.

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

> **Migrating from an older version?** If you already have `credentials.json` and `token.json` files, import them both:
>
> ```bash
> python -m ghostinthemini.scheduler --import-credentials credentials.json
> python -m ghostinthemini.scheduler --import-token token.json
> ```
>
> Then delete both files — they're now in your keyring.

### 4. Make sure Ollama is running

The ghost runs on a local Qwen model via [Ollama](https://ollama.com/). Make sure Ollama is running with the model pulled before using the scheduler.

### 5. Set up Slack integration (optional)

The bot connects via **Socket Mode** — no public URL or inbound ports on your Mac Mini. Only allowlisted Slack user IDs can trigger scheduling.

#### Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it whatever you like and pick your workspace

#### Enable Socket Mode and generate the app-level token

3. In the sidebar, go to **Socket Mode** and toggle it **on**
4. You'll be prompted to generate an **app-level token** — give it a name (e.g. "ghostinthemini") and select the `connections:write` scope
5. Copy the generated `xapp-…` token

#### Add bot scopes

6. In the sidebar, go to **OAuth & Permissions**
7. Scroll down to **Bot Token Scopes** and click **Add an OAuth Scope** for each of:
   - `chat:write`
   - `app_mentions:read`
   - `im:history`
   - `im:read`

#### Subscribe to events

8. In the sidebar, go to **Event Subscriptions** and toggle it **on**
9. Under **Subscribe to bot events**, click **Add Bot User Event** and add:
   - `message.im` — so the bot receives your direct messages
   - `app_mention` — so the bot responds to @-mentions in channels
10. Click **Save Changes**

#### Enable DMs on the messages tab

11. In the sidebar, go to **App Home**
12. Scroll to **Show Tabs** and check **Allow users to send Slash commands and messages from the messages tab**

#### Install the app and get the bot token

13. In the sidebar, go to **Install App** and click **Install to Workspace**
14. Authorize on the consent screen
15. Copy the **Bot User OAuth Token** (`xoxb-…`) shown after installation

> **Note:** If you add new scopes or event subscriptions later, Slack will ask you to **reinstall** the app for them to take effect.

#### Store tokens in keyring

```bash
# App-level token (xapp-…) — from step 5
python -m ghostinthemini.slack_bot --store slack_app_token xapp-YOUR-TOKEN

# Bot token (xoxb-…) — from step 15
python -m ghostinthemini.slack_bot --store slack_bot_token xoxb-YOUR-TOKEN
```

#### Add allowed users

Only Slack user IDs on the allowlist can interact with the bot — messages from anyone else are silently dropped.

To find your Slack user ID:

1. Open Slack
2. Click your **profile picture** (bottom-left on desktop, top-right on mobile)
3. Click **Profile**
4. Click the **three dots** (**...**) menu next to "Edit Profile" / "Set Status"
5. Click **Copy member ID**

Your member ID will look something like `U07AB12CDEF` — it is **not** your display name or username.

Then store it:

```bash
python -m ghostinthemini.slack_bot --allow-users U07AB12CDEF
```

To allow multiple users, pass a comma-separated list:

```bash
python -m ghostinthemini.slack_bot --allow-users U07AB12CDEF,U04XY98GHIJ
```

> **Security:** All tokens and the allowlist live in your system keyring (macOS Keychain) — never in files or environment variables.

## Run

```bash
# Pulse check — verify the ghost is awake
python -m ghostinthemini.main

# Schedule a task via the CLI
python -m ghostinthemini.scheduler "2 hour deep work session"

# Start the Slack bot (Socket Mode, runs in foreground)
python -m ghostinthemini.slack_bot
```

Once the Slack bot is running, DM it from your phone or desktop:

> "Schedule a 30 minute standup at 10am on Friday"

The ghost will check your calendar, find the best slot, and create the event.

## Test

```bash
pytest
```
