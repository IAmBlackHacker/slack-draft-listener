# Setup (macOS)

Written so a person or Claude Code can follow it top to bottom. Steps marked
**[YOU]** need a human: a browser sign-in, a sudo password or System Settings.

Placeholders:
- `WORKSPACE`: the folder holding the repos and docs Claude may read, e.g. `~/Desktop/Work`
- `LISTENER`: this repo's checkout, e.g. `WORKSPACE/_slack-listener`

## 0. Prerequisites

- macOS with Xcode Command Line Tools: `xcode-select -p` prints a path; if not, run
  `xcode-select --install` **[YOU]**. This provides `clang` and `/usr/bin/python3`.
- Claude Code installed and signed in: `claude --version`, then `claude` → `/login` **[YOU]**.
- Decide the mode:
  - **agent:** the Mac user is normally logged in at the desktop (laptop, or a Mac mini you log in to).
  - **daemon:** start at boot with nobody logged in (headless Mac mini, or this user
    isn't the auto-login user). Chrome screenshots and notifications are off in this mode.

## 1. Clone

```sh
git clone <repo-url> WORKSPACE/_slack-listener
```

By default the workspace is the parent folder of the checkout. To keep the checkout
elsewhere, set `workspace_root` in step 3.

## 2. Add your Slack MCP server and sign in

```sh
cd WORKSPACE
claude mcp add-json work-slack '{"type":"http","url":"https://mcp.slack.com/mcp","oauth":{"clientId":"1601185624273.8899143856786","callbackPort":3118}}' --scope local
```

The `clientId` is the public Slack MCP app used by Claude Code's Slack plugin; it is
not a secret. The server name `work-slack` must match `slack_mcp_server` in config.json.

**[YOU]** Sign in. Run `claude` in `WORKSPACE`, type `/mcp`, pick `work-slack`,
choose Authenticate and sign in to **your own** Slack account. If the browser can't
reach the Mac, paste the final redirect URL back into the prompt.

- **daemon mode:** do this sign-in from an SSH session (`ssh <user>@localhost`), not
  the desktop. With the Keychain locked, Claude Code saves the sign-in to
  `~/.claude/.credentials.json` (readable only by you), which is the only place a
  boot service can read it. Check it worked:
  ```sh
  cd LISTENER && cp -n config.example.json config.json
  /usr/bin/python3 -c "import slack_mcp; slack_mcp._token(); print('sign-in OK')"
  ```

## 3. Configure

```sh
cd LISTENER
cp -n config.example.json config.json
```

Edit `config.json`:
- `owner_name`: your first name. It's used in the prompts.
- `workspace_root`: leave `""` if the checkout is inside WORKSPACE; otherwise the full path.
- `language_mix`: how drafts should sound. Each entry is `[instruction, weight]`, e.g.
  `[["Plain English.", 80], ["English with a light Hinglish touch.", 20]]`.
- `use_chrome`: `true` only in agent mode with the Claude in Chrome extension set up.
  `chrome_note` then says which profile to use, e.g. `"Use the Work profile (profile dir Default)."`.
- `quiet_hours`: e.g. `[0, 8]` to pause overnight.

Then look up your Slack ids. This fills `slack_user_id`, `slack_team_id` and
`started_at_ts`, so mentions from before now are never drafted:

```sh
/usr/bin/python3 listener.py setup
```

## 4. Install

```sh
./install.sh          # agent mode
./install.sh daemon   # daemon mode (asks for your sudo password) [YOU]
```

The installer:
- generates `claude-settings.json`, which wires up the safety hook;
- links the skill into `WORKSPACE/.claude/skills/slack-reply`;
- builds `~/.local/bin/slack-draft-listener`;
- starts the service.

**[YOU] Full Disk Access.** Needed when WORKSPACE is under `~/Desktop`, `~/Documents`
or `~/Downloads`. Open System Settings → Privacy & Security → Full Disk Access → `+`,
press Cmd+Shift+G and add `~/.local/bin/slack-draft-listener`. Grant it to that
binary, not to python3. Then restart the service:
- agent: `./install.sh`
- daemon: `sudo launchctl kickstart -k system/io.slack-draft-listener`

## 5. Verify

```sh
tail -f LISTENER/state/listener.log
```

- You should see `listener started (poll every 30s)` and no `cycle error` lines.
- `state/launchd.err.log` must not show `Operation not permitted`. If it does, Full
  Disk Access is missing (step 4).
- Status:
  - agent: `launchctl print gui/$(id -u)/io.slack-draft-listener | grep state`
  - daemon: `launchctl print system/io.slack-draft-listener | grep state`
- End-to-end test: **[YOU]** tag yourself in a Slack thread with a question. Within a
  minute or two the log shows `-> drafted` and the draft appears in that thread, unsent.

## Troubleshooting

- **`sign-in problem (HTTP 401)` repeating:** the Slack sign-in expired. Redo the
  sign-in in step 2 (from SSH in daemon mode).
- **`claude exited ...: not logged in`:** run `claude` → `/login` again (in daemon
  mode, from SSH so it's saved to the file).
- **Nothing happens after a reboot (agent mode):** this user isn't logged in at the
  desktop. Switch to daemon mode with `./install.sh uninstall && ./install.sh daemon`.
- **Uninstall:** `./install.sh uninstall` or `./install.sh daemon-uninstall`.
- **Only one Mac per Slack account.** Two copies would draft every mention twice.
