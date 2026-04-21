# Standup Bot

Automatically collects your daily activity from GitHub, Jira, Slack, and Notion — then uses an LLM to write your standup and post it to your Slack DM every morning.

Supports any model via [LiteLLM](https://github.com/BerriAI/litellm): Anthropic Claude, OpenAI GPT, Google Gemini, local Ollama, and more.

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

All integrations except the LLM provider key are optional. The bot skips any source whose credentials are absent.

### 3. Choose a model

Set `LLM_MODEL` in your `.env`. It defaults to `claude-sonnet-4-6` (Anthropic).

| Provider | `LLM_MODEL` value | API key env var |
|---|---|---|
| Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Google Gemini | `gemini/gemini-1.5-pro` | `GEMINI_API_KEY` |
| Local Ollama | `ollama/llama3` | *(none)* |

### 4. Create a Slack Bot (optional — for posting and Slack data collection)

1. Go to https://api.slack.com/apps → **Create New App**
2. Under **OAuth & Permissions**, add these scopes:
   - `channels:history`, `groups:history` — read channel messages
   - `channels:read`, `groups:read` — list channels you belong to
   - `im:write`, `chat:write` — send DMs
   - `users:read`, `auth:test` — identify yourself
3. Install the app to your workspace and copy the **Bot User OAuth Token** into `SLACK_BOT_TOKEN`

### 5. Run

```bash
python main.py
```

The bot fetches activity, generates a draft, and prompts you to approve or regenerate before posting.

### 6. Schedule it daily (runs at 9 am on weekdays)

```bash
crontab -e
```

Add:

```
0 9 * * 1-5 cd /path/to/standup-bot && python main.py
```

`python-dotenv` loads `.env` automatically — no manual `export` needed.

---

## Feedback Loop

After each draft you'll see a prompt:

```
👍 Approve and post (u) / 👎 Regenerate (d) / ⏭️  Skip posting (s):
```

- **u** — saves the standup as a positive example and posts it to Slack
- **d** — asks for an optional reason, then regenerates using a multi-turn conversation so the model knows exactly what was wrong. You get up to 3 regenerations; once the limit is reached, the prompt changes to only offer approve or skip (you can still approve the final draft)
- **s** — exits without saving or posting

Approved standups are stored in `feedback_log.jsonl`. The next run automatically loads the three most recent approvals as few-shot examples, so the output improves to match your preferences over time.

---

## Project Structure

```
standup-bot/
├── main.py                    # Entry point and orchestration
├── collectors/
│   ├── github.py              # GitHub merged PRs, open PRs, and code reviews
│   ├── jira.py                # Jira ticket activity and comments
│   ├── slack.py               # Slack messages sent and mentions received
│   └── notion.py              # Recently edited Notion pages
├── core/
│   ├── summariser.py          # LLM call via LiteLLM + prompt construction
│   ├── slack_delivery.py      # Posts the standup to your Slack DM
│   └── feedback.py            # Feedback log read/write
├── tests/
│   ├── helpers.py             # Shared mock_response helper
│   ├── test_github.py
│   ├── test_jira.py
│   ├── test_slack.py
│   ├── test_notion.py
│   ├── test_summariser.py
│   ├── test_slack_delivery.py
│   └── test_feedback.py
├── feedback_log.jsonl         # Created on first run — gitignored
├── .env.example               # Credential and model configuration template
├── .python-version            # Pins Python 3.12 for pyenv
└── requirements.txt
```

---

## Customisation

**Change the summary style** — edit `SYSTEM_PROMPT` in [core/summariser.py](core/summariser.py)

**Add or remove sources** — comment out the relevant block in [main.py](main.py)

**Adjust the lookback window** — pass `hours=48` to any collector for a longer window:

```python
activity["github"] = fetch_github_activity(github_token, github_username, hours=48)
```

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
