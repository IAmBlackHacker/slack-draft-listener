# Slack draft listener

When someone tags you in Slack, this prepares your reply as a **Slack draft in that
thread**. It never sends anything: you review the draft in Slack and send it yourself.

- Polls Slack every 30s for messages that tag you, with no AI involved
  (`slack_mcp.py` talks to Slack's official MCP server using your Claude Code
  sign-in).
- For each new mention it runs Claude Code headless (`claude -p`) in your workspace
  folder with the `slack-reply` skill. Claude reads the thread, looks into your repos
  and docs (read-only), optionally takes a screenshot in Chrome, then saves a draft
  with `slack_send_message_draft`.
- **Tag yourself** in a thread to ask for a draft on purpose; your note in that
  message is treated as instructions for the reply.
- **Thread watching:** threads you were tagged in are re-read every 60s for 48h. New
  replies that don't tag you again still get a follow-up draft, but only once the
  thread has been quiet for 90s and only if the replies need your input.
- `guard_hook.py` (a PreToolUse hook) enforces the rules for every headless run:
  - Slack: read/search, plus a draft into the one thread the job is about.
  - Files: read-only, inside the workspace folder only, never secrets.
  - Chrome: read-only browsing.
- Runs as a launchd **agent** (while you're logged in) or a boot **daemon** (starts
  at boot with nobody logged in, e.g. on a headless Mac mini).

**Setup:** follow [SETUP.md](SETUP.md), or open Claude Code in this folder and say
"set up the Slack listener". `CLAUDE.md` points Claude at SETUP.md.

## Files

| File | What it is |
|---|---|
| `listener.py` | The loop: poll → filter → draft → log. `run`, `once`, `setup`, `draft <permalink> ["question"]` |
| `slack_mcp.py` | Minimal read-only client for `mcp.slack.com` |
| `guard_hook.py` | Safety hook for the headless Claude runs |
| `skill/slack-reply/SKILL.md` | How Claude investigates and writes the draft (linked into `<workspace>/.claude/skills`) |
| `install.sh` | Installs the agent or daemon; builds the tiny launcher binary |
| `launcher/launcher.c` | Launcher that gets Full Disk Access instead of python3 |
| `config.example.json` | Copy to `config.json` (git-ignored) and fill in |

## Use

- **Log:** `state/listener.log`. Each draft's result and screenshots: `drafts/<channel_ts>/`.
- **One-off draft:** `python3 listener.py draft <slack permalink>`. **One poll cycle:** `python3 listener.py once`.
- **Tuning** (`config.json`): `poll_interval_seconds`, `quiet_hours` (e.g. `[0, 8]`),
  `use_chrome`, `draft_model`, `language_mix`.
- **Run it on one Mac per person.** Two copies with the same Slack sign-in will both
  draft every mention.
