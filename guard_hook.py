#!/usr/bin/env python3
"""PreToolUse guard for the Slack listener's headless Claude runs.

Second line of defence behind --allowedTools/--disallowedTools:
  * Slack: only read/search tools and slack_send_message_draft, and the draft
    may only target the one thread this job is about (SLACK_DRAFT_TARGET).
    Nothing that sends, schedules, reacts or edits canvases ever passes.
  * Files: Read/Glob/Grep/Bash may only touch the workspace root, and never
    secrets (.env, keys, credentials).
  * Chrome: on Slack tabs only look (screenshot/read/scroll) and drop an image
    into the composer; never click, type, press keys or run JS there. Anywhere
    else, block clicks whose summary says save/submit/delete/send etc.

Exit code 2 + stderr = deny (Claude sees the reason).
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("LISTENER_ROOT") or str(Path(__file__).resolve().parent.parent)).resolve()
STATE_DIR = Path(__file__).resolve().parent / "state"
TABS_FILE = STATE_DIR / f"chrome_tabs_{os.environ.get('SLACK_JOB_ID', 'adhoc')}.json"

SLACK_ALLOWED = re.compile(
    r"^slack_(read_[a-z_]+|search_[a-z_]+|list_channel_members|list_user_channels|get_reactions|send_message_draft)$"
)
SECRET_PATH = re.compile(
    r"(^|/)(\.env[^/]*|.*\.pem|.*\.key|id_rsa[^/]*|id_ed25519[^/]*|credentials[^/]*|\.aws|\.ssh|\.netrc|"
    r"secrets?\.(json|ya?ml|toml)|.*\.p12|.*\.keystore)$",
    re.I,
)
DANGEROUS_CLICK = re.compile(
    r"\b(save|submit|send|post|publish|delete|remove|confirm|apply|update|create|disable|enable|"
    r"toggle|approve|merge|deploy|invite|pay|purchase|sign ?out|log ?out|archive|reset)\b",
    re.I,
)


def deny(reason: str) -> None:
    print(f"slack-listener guard: {reason}", file=sys.stderr)
    sys.exit(2)


def inside_root(p: str) -> bool:
    if not p:
        return True
    path = Path(os.path.expanduser(p))
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def check_path(p: str) -> None:
    if not inside_root(p):
        deny(f"path {p!r} is outside {ROOT}; this service only investigates {ROOT}")
    if SECRET_PATH.search(p.rstrip("/")):
        deny(f"{p!r} looks like a secrets file; never read or quote secrets")


# Bash is allowed wholesale in the -p run; this allowlist is the real boundary.
SAFE_CMDS = {
    "cd", "ls", "pwd", "whoami", "date", "echo", "printf", "true", "false", "test", "[",
    "grep", "egrep", "rg", "find", "head", "tail", "wc", "cat", "less", "sed", "sort", "uniq",
    "awk", "cut", "tr", "jq", "xargs", "diff", "file", "stat", "tree", "basename", "dirname",
    "realpath", "git", "column", "nl", "comm", "fold", "rev", "tac", "md5", "shasum",
    "for", "do", "done", "while", "if", "then", "else", "elif", "fi", "read", "in",
}


def check_segments(cmd: str) -> None:
    # Strip quoted strings so separators inside patterns don't split commands.
    bare = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", cmd)
    for seg in re.split(r"\|\||&&|[;|\n]|\bdo\b|\bthen\b|\belse\b", bare):
        words = seg.strip().split()
        while words and re.match(r"^\w+=", words[0]):   # VAR=value prefix
            words = words[1:]
        if not words:
            continue
        head = words[0].lstrip("({")
        if head not in SAFE_CMDS:
            deny(f"'{head}' is not an allowed read-only command here")
        if head == "xargs":
            rest = [w for w in words[1:] if not w.startswith("-")]
            if rest and rest[0] not in SAFE_CMDS:
                deny(f"xargs {rest[0]} is not allowed")
    if re.search(r"\bsed\b[^|;&]*\s-[a-zA-Z]*i", bare):
        deny("sed -i edits files; read-only here")
    if re.search(r"\bfind\b[^|;&]*\s-(delete|exec|execdir|ok|fprint)", bare):
        deny("find -delete/-exec is not allowed")
    if re.search(r"\bawk\b.*\b(system|getline)\b|print\s*>", cmd):
        deny("awk system()/getline/redirection is not allowed")


def check_bash(cmd: str) -> None:
    check_segments(cmd)
    if re.search(r"\$HOME|\$\{HOME\}|\$\(|`", cmd):
        deny("no $HOME, command substitution or backticks in Bash")
    # Any absolute or ~ path must be inside the root.
    fs_roots = r"/(?:Users|home|root|etc|private|var|opt|usr|bin|sbin|tmp|Volumes|System|Library|Applications)\b"
    for tok in re.findall(r"(?:(?<=\s)|(?<=^)|(?<=[=:'\"]))(~[^\s'\";|&<>)]*|" + fs_roots + r"[^\s'\";|&<>)]*)", cmd):
        if tok.startswith("/") and re.match(r"^/(dev/null|tmp/claude|private/tmp/claude)", tok):
            continue
        check_path(tok)
    if re.search(r"(^|[\s/])\.\.(/|\s|$)", cmd):
        deny("no '..' path escapes in Bash")
    if re.search(r"\b(curl|wget|ssh|scp|rsync|nc|kubectl|aws|gh|psql|mysql|open|osascript|rm|mv|cp|tee)\b", cmd) or re.search(
        r"\bgit\s+(?:-[Cc]\s+\S+\s+|--?[\w-]+(?:=\S+)?\s+)*(push|commit|checkout|reset|fetch|pull|merge|rebase|stash|clean|switch|restore|"
        r"add|rm|mv|tag|worktree|config|remote|gc|apply|am|cherry-pick|revert|update-ref|branch\s+(?:-\S*[dDmMf]|--(?:delete|move|force)))\b", cmd):
        deny("Bash is read-only here (no network, no writes, no git state changes)")
    if re.search(r"(^|[^<>])>{1,2}(?!&)", cmd.replace("2>/dev/null", "").replace("2>&1", "")):
        deny("no output redirection; Bash is read-only here")
    if re.search(r"\b(env|printenv|security|eval|exec|source|sh|bash|zsh|python3?|node|perl|ruby)\b", cmd):
        deny("no reading environment variables or keychain")


def load_tabs() -> dict:
    try:
        return json.loads(TABS_FILE.read_text())
    except Exception:
        return {}


def save_tabs(tabs: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TABS_FILE.write_text(json.dumps(tabs))


def is_slack_url(url: str) -> bool:
    return bool(re.search(r"(^|//|\.)slack\.com", url or "", re.I))


def check_chrome(short: str, inp: dict) -> None:
    tabs = load_tabs()
    tab = str(inp.get("tabId", ""))
    tab_is_slack = tabs.get(tab, "") in ("slack", "unknown")

    if short in ("javascript_tool", "form_input", "shortcuts_execute", "browser_batch", "file_upload"):
        deny(f"{short} is not allowed for the Slack listener (browsing is read-only)")

    if short == "navigate":
        url = inp.get("url", "")
        if url in ("back", "forward"):
            if tab:
                tabs[tab] = "unknown"
                save_tabs(tabs)
            return
        if is_slack_url(url) and not tab:
            deny("pass an explicit tabId when opening Slack")
        if tab:
            tabs[tab] = "slack" if is_slack_url(url) else "other"
            save_tabs(tabs)
        return

    if short == "computer":
        action = inp.get("action", "")
        if action in ("screenshot", "zoom", "scroll", "scroll_to", "wait", "hover"):
            return
        if tab_is_slack:
            deny(f"computer:{action} on a Slack tab is blocked; only look, and use upload_image to attach a screenshot")
        if action == "key" and re.search(r"\b(return|enter)\b", inp.get("text", ""), re.I) and DANGEROUS_CLICK.search(inp.get("action_summary", "")):
            deny("pressing Enter to submit something is blocked")
        return check_click_summary(inp)

    # upload_image (allowed on Slack: it only drops into the composer), read_page,
    # find, get_page_text, tabs_*, gif_creator, read_console/network: read-only.
    return


def check_click_summary(inp: dict) -> None:
    summary = inp.get("action_summary", "") or ""
    if DANGEROUS_CLICK.search(summary):
        deny(f"action looks like it changes something ({summary!r}); browsing is read-only, only look and screenshot")


def main() -> None:
    data = json.load(sys.stdin)
    name = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}

    # ---- Slack -------------------------------------------------------------
    if "slack" in name.lower() and name.startswith("mcp__"):
        if name.startswith("mcp__claude_ai_Slack__"):
            deny("the shared claude.ai Slack connector is never used; use your own Slack MCP server")
        short = name.split("__")[-1]
        if not SLACK_ALLOWED.match(short):
            deny(f"{short} is blocked: this service only reads Slack and creates drafts, it never sends")
        if short == "slack_send_message_draft":
            target = os.environ.get("SLACK_DRAFT_TARGET", "")
            if not target:
                deny("drafting is not enabled for this run")
            chan, _, thread = target.partition(":")
            if str(inp.get("channel_id", "")) != chan or str(inp.get("thread_ts", "")) != thread:
                deny(f"draft must go to channel_id={chan} thread_ts={thread} (the thread you were tagged in)")
        return

    # ---- Chrome ------------------------------------------------------------
    if name.startswith("mcp__claude-in-chrome__"):
        return check_chrome(name.split("__")[-1], inp)

    # ---- Files / shell -------------------------------------------------------
    if name in ("Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"):
        deny(f"{name} is not allowed for the Slack listener")
    if name == "Read":
        return check_path(inp.get("file_path", ""))
    if name in ("Glob", "Grep"):
        check_path(inp.get("path", "") or os.getcwd())
        pat = inp.get("pattern", "") if name == "Glob" else inp.get("glob", "")
        if pat and (pat.startswith("/") or pat.startswith("~") or ".." in pat):
            check_path(pat)
        return
    if name == "Bash":
        return check_bash(inp.get("command", ""))


if __name__ == "__main__":
    main()
