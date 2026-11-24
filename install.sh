#!/bin/zsh
# Install / reinstall the Slack draft listener for this Mac user.
#   ./install.sh                  login agent (runs while you're logged in to the desktop)
#   ./install.sh daemon           boot LaunchDaemon as this user: starts at boot, no login
#                                 needed (asks for sudo). Use on a headless Mac mini.
#   ./install.sh uninstall        remove the login agent
#   ./install.sh daemon-uninstall remove the boot daemon
# Only one of the two may be installed; each mode removes the other's agent file.
set -eu
HERE="${0:A:h}"
LABEL="${SLACK_LISTENER_LABEL:-io.slack-draft-listener}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DPLIST="/Library/LaunchDaemons/$LABEL.plist"
MODE="${1:-agent}"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
case "$MODE" in
  uninstall) rm -f "$PLIST"; echo "removed agent $LABEL"; exit 0 ;;
  daemon-uninstall)
    sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
    sudo rm -f "$DPLIST"; echo "removed daemon $LABEL"; exit 0 ;;
  agent|daemon) ;;
  *) echo "unknown mode: $MODE"; exit 1 ;;
esac

if [[ ! -f "$HERE/config.json" ]]; then
  echo "config.json is missing: copy config.example.json to config.json and fill it in (see SETUP.md)"; exit 1
fi
ROOT="$(/usr/bin/python3 -I -c 'import json,os,sys; c=json.load(open(sys.argv[1])); print(os.path.realpath(os.path.expanduser(c.get("workspace_root") or sys.argv[2])))' "$HERE/config.json" "${HERE:h}")"
mkdir -p "$HERE/state" "$HERE/drafts" "$HOME/.local/bin"

# Hook settings with this checkout's absolute path.
sed "s#__HERE__#$HERE#g" "$HERE/claude-settings.template.json" > "$HERE/claude-settings.json"

# The drafting skill must live in the workspace's .claude/skills to be found by `claude -p`.
SKILL_DST="$ROOT/.claude/skills/slack-reply"
if [[ ! -e "$SKILL_DST" ]]; then
  mkdir -p "$ROOT/.claude/skills"
  ln -s "$HERE/skill/slack-reply" "$SKILL_DST"
  echo "linked skill -> $SKILL_DST"
fi

# Full Disk Access is granted to this one launcher binary (not to python3), so the
# service can read folders like ~/Desktop. Rebuilding changes its signature and drops
# the grant, so only rebuild when launcher.c or the checkout path changed.
BIN="$HOME/.local/bin/slack-draft-listener"
SRC_HASH="$( (cat "$HERE/launcher/launcher.c"; echo "$HERE") | shasum -a 256 | cut -c1-16)"
if [[ ! -x "$BIN" || "$(cat "$BIN.srchash" 2>/dev/null)" != "$SRC_HASH" ]]; then
  clang -O2 -Wall -DLISTENER_PY="\"$HERE/listener.py\"" -o "$BIN" "$HERE/launcher/launcher.c"
  codesign --force --sign - --identifier "$LABEL" "$BIN"
  echo "$SRC_HASH" > "$BIN.srchash"
  echo "built $BIN — if the workspace is under ~/Desktop or ~/Documents, grant it Full Disk Access"
  echo "(System Settings → Privacy & Security → Full Disk Access → + → Cmd+Shift+G → $BIN)"
fi

write_plist() {  # $1 = extra keys, $2 = extra env
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>$1
  <key>ProgramArguments</key><array>
    <string>$BIN</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>USER</key><string>$(id -un)</string>$2
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$HERE/state/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$HERE/state/launchd.err.log</string>
</dict></plist>
PLIST
}

if [[ "$MODE" == "daemon" ]]; then
  rm -f "$PLIST"  # never run the login agent alongside the daemon
  sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
  write_plist "
  <key>UserName</key><string>$(id -un)</string>
  <key>GroupName</key><string>staff</string>" "
    <key>SLACK_LISTENER_HEADLESS</key><string>1</string>" | sudo tee "$DPLIST" >/dev/null
  sudo chown root:wheel "$DPLIST"; sudo chmod 644 "$DPLIST"
  sudo launchctl bootstrap system "$DPLIST"
  echo "started daemon $LABEL (boot, no login) — logs: $HERE/state/listener.log"
else
  if [[ -f "$DPLIST" ]]; then echo "a boot daemon is installed; run ./install.sh daemon-uninstall first"; exit 1; fi
  mkdir -p "$HOME/Library/LaunchAgents"
  write_plist "" "" > "$PLIST"
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "started agent $LABEL — logs: $HERE/state/listener.log"
fi
