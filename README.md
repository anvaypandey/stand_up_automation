# Standup Bot

Automatically collects your daily activity from GitHub, Jira, Slack, Notion, Google Calendar, and local git repos — then uses an LLM to write your standup and post it to your Slack DM every morning.

Supports any model via [LiteLLM](https://github.com/BerriAI/litellm): Anthropic Claude, OpenAI GPT, Google Gemini, Ollama cloud, local Ollama, and more.

**Requires Python 3.10+.** The project pins 3.12 via `.python-version`.

## Example Output

> *🤖 Your Daily Standup — Monday, April 21*
>
> *✅ Done*
> • Merged <https://github.com/...|auth token refresh logic> (PR #412)
> • Resolved <https://yourco.atlassian.net/browse/ENG-204|ENG-204: Fix race condition in queue processor>
>
> *🔄 In Progress*
> • Investigating flaky CI test in `payments-service` — narrowed to a timing issue
> • Updated <https://notion.so/...|API Design Doc> with new endpoint specs
>
> *🚧 Blockers / Waiting*
> • Waiting on design sign-off for <https://yourco.atlassian.net/browse/ENG-198|onboarding flow redesign>

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env with your API keys
```

The bot loads `.env` automatically at startup. All integrations except the LLM provider key are optional — the bot skips any source whose credentials are absent.

### 3. Choose a model

Set `LLM_MODEL` in your `.env`. Defaults to `claude-sonnet-4-6` (Anthropic) if not set.

| Provider | `LLM_MODEL` value | Required env vars |
|---|---|---|
| Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Google Gemini | `gemini/gemini-1.5-pro` | `GEMINI_API_KEY` |
| Ollama cloud | `ollama_chat/gemma3:4b` | `OLLAMA_API_KEY`, `OLLAMA_API_BASE` |
| Local Ollama | `ollama/llama3` | *(none)* |

#### Using Ollama cloud (ollama.com)

1. Sign up at [ollama.com](https://ollama.com) and copy your API key
2. Set in `.env`:
   ```
   OLLAMA_API_KEY=your-key
   OLLAMA_API_BASE=https://api.ollama.com
   LLM_MODEL=ollama_chat/gemma3:4b
   ```
3. To see all available models, run:
   ```bash
   curl https://api.ollama.com/api/tags \
     -H "Authorization: Bearer $OLLAMA_API_KEY" | python3 -m json.tool
   ```
   Free/small models include `gemma3:4b` and `ministral-3:3b`.

### 4. Create a Slack Bot (optional — for posting and Slack data collection)

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Under **OAuth & Permissions → Bot Token Scopes**, add:
   - `channels:history`, `groups:history` — read channel messages
   - `channels:read`, `groups:read` — list channels you belong to
   - `im:write`, `chat:write` — send DMs and post/update/delete messages
   - `reactions:read` — read emoji reactions (required for the Slack feedback loop)
   - `users:read` — look up user info
3. Click **Install to Workspace** and copy the **Bot User OAuth Token** (`xoxb-...`) into `SLACK_BOT_TOKEN`
4. Find your personal Slack user ID: click your profile → **⋮** → **Copy member ID**. Set it as `SLACK_USER_ID` so the bot DMs you (not itself)

> **Note:** `auth:test` is not a scope you add manually — it is available to all bot tokens by default.

### 5. Set up local git repos (optional)

Add these two variables to your `.env`:

```
GIT_REPO_PATHS=/Users/you/projects/myapp,/Users/you/projects/scripts
GIT_AUTHOR=Your Name
```

- `GIT_REPO_PATHS` — comma-separated absolute paths to repos you want scanned
- `GIT_AUTHOR` — name or email passed to `git log --author`; matches however your commits are attributed

The collector runs `git log --since --author --oneline --no-merges` per repo. No API key or network access needed — it reads your local history directly. Repos that are not valid git directories are skipped with a warning.

### 7. Set up Google Calendar (optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project → enable the **Google Calendar API**
2. **Option A — Service account** (recommended for automated runs):
   - Create a service account, download the JSON key, and set `GOOGLE_CALENDAR_CREDENTIALS=/path/to/key.json`
   - Share your calendar with the service account email (give it read access)
3. **Option B — OAuth2 credentials**:
   - Create an OAuth2 desktop client, download `credentials.json`, and set `GOOGLE_CALENDAR_CREDENTIALS=/path/to/credentials.json`
   - On first run the bot opens a browser for authorisation and saves `token.json` alongside the credentials file

```bash
pip install google-api-python-client google-auth-oauthlib
```

> All-day events and declined invites are automatically excluded.

### 9. Set up Notion (optional)

1. Go to https://www.notion.so/profile/integrations → **New integration**
2. Copy the **Internal Integration Secret** (`secret_...`) into `NOTION_TOKEN`
3. Open each Notion page/database you want tracked → **...** → **Connect to** → select your integration

> Without step 3, the token won't have access to any pages even if it's valid.

### 10. Run

```bash
python main.py
```

The bot validates all configured tokens (see [Startup Healthcheck](#startup-healthcheck)), fetches activity, generates a draft, posts it to your Slack DM, and waits for your reaction. See [Feedback Loop](#feedback-loop) below.

**Dry run** — generate and print the standup without posting to Slack or saving feedback:

```bash
python main.py --dry-run
```

### 11. Schedule it daily (runs at 9 am on weekdays)

```bash
crontab -e
```

Add:

```
0 9 * * 1-5 cd /path/to/standup-bot && source .env && python main.py
```

---

## Running Context

After each approved standup, a dated entry is saved to `context_log.jsonl`. On the next run, the last 5 entries are injected into the LLM prompt so the model can write "continued work on X" instead of re-describing the same task fresh every day.

```
2026-04-22 INFO Generating standup...
# LLM receives context: "2026-04-21: Investigated flaky CI test in payments-service..."
```

The context file grows by one line per approved standup and is gitignored.

---

## Prompt Caching

When using an Anthropic model, the static system prompt is sent with `cache_control: ephemeral`. On the second and subsequent runs within the 5-minute cache TTL, Anthropic returns the prompt tokens from cache, reducing cost by up to 90% on the system prompt prefix.

Cache usage is logged after each LLM call:

```
2026-04-22 09:00:05 INFO Prompt cache — created: 487 tokens  read: 0 tokens
2026-04-23 09:00:05 INFO Prompt cache — created: 0 tokens  read: 487 tokens
```

This works transparently — no configuration needed. Non-Anthropic models ignore the cache hint.

---

## Startup Healthcheck

Before collecting any activity, the bot validates every configured integration token with a lightweight auth call. A summary is printed at startup:

```
2026-04-22 09:00:01 INFO Healthcheck — ✅ github  ✅ jira  ⚠️  slack  ✅ notion
```

- Sources that fail the check are skipped — the rest still run.
- If **every** configured source fails, the bot exits immediately with an error rather than generating an empty standup.

This catches expired or missing tokens before the pipeline begins rather than mid-run.

---

## Fault Isolation

Each collector is wrapped independently. If one source throws an unexpected error (network blip, API change, rate limit), it is logged as a warning and skipped — the bot generates a partial standup from whichever sources succeeded rather than failing entirely.

```
2026-04-22 09:00:04 WARNING Jira collector failed — skipping: Connection timeout
2026-04-22 09:00:05 INFO Fetching Notion activity...
```

---

## Logging

Every run appends to `standup.log` in the project root. Log lines include timestamps and severity:

```
2026-04-22 09:00:01 INFO Standup Bot starting...
2026-04-22 09:00:02 INFO Fetching activity since 2026-04-21 09:00 UTC
2026-04-22 09:00:02 INFO Healthcheck — ✅ github  ✅ jira  ✅ slack  ✅ notion
2026-04-22 09:00:03 INFO Fetching GitHub activity...
2026-04-22 09:00:06 INFO Posting draft to Slack DM (reaction timeout: 300s)...
2026-04-22 09:05:07 INFO Standup approved.
```

`standup.log` is gitignored. To watch logs live: `tail -f standup.log`

---

## Activity Window

All collectors look back **24 hours** by default. On **Mondays**, the window automatically extends to **last Friday at the same time**, so weekend work is not missed.

```
Mon 9 am run  →  fetches since Fri 9 am  (72 h)
Tue–Fri 9 am  →  fetches since yesterday 9 am  (24 h)
```

To override the default timeout for Slack reaction polling, set `SLACK_FEEDBACK_TIMEOUT` (seconds) in your `.env`:

```
SLACK_FEEDBACK_TIMEOUT=180   # 3 minutes
```

---

## Feedback Loop

When `SLACK_BOT_TOKEN` is set, the entire feedback loop happens inside Slack. The bot posts the draft to your DM with a reaction prompt at the bottom:

> *React to respond: ✅ approve · 🔁 regenerate (reply in thread with reason) · ⏭️ skip · Waiting 300s…*

| Reaction | What happens |
|---|---|
| ✅ | Saves the standup as a positive example, removes the prompt footer |
| 🔁 | Deletes the draft, regenerates (reply in the thread first to give a reason), reposts |
| ⏭️ | Deletes the draft, exits without saving |
| *(no reaction within timeout)* | Removes the prompt footer and leaves the message posted |

You get up to 3 regenerations. Approved standups are stored in `feedback_log.jsonl` and used as few-shot examples on the next run, so output improves over time.

**Without a Slack token**, the bot falls back to a terminal prompt:

```
👍 Approve (u) / 👎 Regenerate (d) / ⏭️  Skip (s):
```

---

## Project Structure

```
standup-bot/
├── main.py                    # Entry point and orchestration
├── collectors/
│   ├── git.py                 # Local git log collector (commits by author)
│   ├── github.py              # GitHub merged PRs, open PRs, and code reviews
│   ├── google_calendar.py     # Google Calendar meetings (service account or OAuth2)
│   ├── jira.py                # Jira ticket activity and comments
│   ├── slack.py               # Slack messages sent and mentions received
│   ├── notion.py              # Recently edited Notion pages
│   └── utils.py               # Shared activity_since() time-window helper
├── core/
│   ├── summariser.py          # LLM call via LiteLLM + prompt construction
│   ├── slack_delivery.py      # Posts drafts, polls reactions, finalises or deletes
│   ├── feedback.py            # Feedback log read/write
│   └── healthcheck.py         # Startup token validation for all integrations
├── tests/
│   ├── helpers.py             # Shared mock_response helper
│   ├── test_context.py
│   ├── test_git.py
│   ├── test_github.py
│   ├── test_google_calendar.py
│   ├── test_jira.py
│   ├── test_slack.py
│   ├── test_notion.py
│   ├── test_summariser.py
│   ├── test_slack_delivery.py
│   └── test_feedback.py
├── standup.log                # Created on first run — gitignored
├── feedback_log.jsonl         # Created on first run — gitignored
├── context_log.jsonl          # Created on first run — gitignored
├── .env                       # Your credentials (gitignored)
├── .env.example               # Credential and model configuration template
├── .python-version            # Pins Python 3.12 for pyenv
└── requirements.txt
```

---

## Customisation

**Change the summary style** — edit `SYSTEM_PROMPT` in [core/summariser.py](core/summariser.py)

**Add or remove sources** — comment out the relevant block in [main.py](main.py)

**Change the reaction timeout** — set `SLACK_FEEDBACK_TIMEOUT` (seconds) in `.env`

**Preview without posting** — run `python main.py --dry-run` to print the standup to stdout without touching Slack or `feedback_log.jsonl`

**Adjust the Slack message layout** — edit `_build_blocks()` in [core/slack_delivery.py](core/slack_delivery.py) to change the Block Kit structure; the plain-text `text` field is always kept as a notification fallback

**Post to a channel instead of a DM** — in [core/slack_delivery.py](core/slack_delivery.py), replace the `conversations.open` call with a hardcoded channel ID passed directly to `chat.postMessage`

**Use a different model per environment** — set `LLM_MODEL` in your `.env`; no code changes required

---

## Running Tests

```bash
python -m pytest tests/
```

All integrations are fully mocked — no API keys or network access needed.

```bash
python -m pytest tests/ -v          # verbose output
python -m pytest tests/test_jira.py # single file
```

---

## Known Limitations

- **Slack channel scan**: requires `channels:read` and `groups:read` scopes. Without them, Slack activity is skipped but the standup still generates from other sources.
- **Notion page limit**: Notion's search API returns at most 20 results. If teammates are very active, pages you edited may be pushed out of the first page of results.
- **GitHub date granularity**: GitHub's search API filters by date, not exact time, so the effective window is midnight-to-now on the calculated start date.
- **Jira**: placeholder credentials (`yourcompany.atlassian.net`) will be skipped automatically with a 410 warning.
