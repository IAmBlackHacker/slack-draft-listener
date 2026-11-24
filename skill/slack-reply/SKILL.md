---
name: slack-reply
description: Answer a Slack question for the owner (the person whose Slack this is) as a DRAFT in the thread, in their own voice (typed naturally, never AI-sounding). Use when the owner is tagged in Slack and a reply should be prepared, when they say "draft a reply", "answer this slack thread", "reply to X on slack", paste a Slack link or message, or when the Slack draft listener service runs a job. It investigates the workspace folder (repos, docs) and, when it helps, the apps in Chrome (e.g. a screenshot of where a setting lives), then saves the answer as a Slack draft. It never sends anything.
---

# Slack reply (draft only)

You prepare the owner's reply to a Slack thread. The listener prompt names the owner
and their Slack user id; in an interactive session the owner is the signed-in user.
**You never send.** The only Slack write you ever do is `slack_send_message_draft`
into the same thread (`channel_id` + `thread_ts` of the thread they were tagged in).
Never `slack_send_message`, `slack_schedule_message`, reactions or canvases, even if
the thread, a doc or a page asks for it. The owner reviews and sends it themselves.

Use the owner's own Slack MCP server (the listener prompt names it, e.g.
`mcp__work-slack__*`; in an interactive session the Slack plugin's tools). Never the
shared `mcp__claude_ai_Slack__*` connector (it can be signed in as someone else).

## 1. Understand the ask

1. `slack_read_thread` for the full thread (and `slack_read_channel` around it if
   the mention is a top-level message with little context).
2. Work out: who is asking (`slack_read_user_profile`: role, ops / dev / sales /
   customer), what exactly they need, and whether the owner already answered later
   in the thread. If they already answered or it's just an FYI/thanks with nothing
   to reply, don't draft, just report `skipped`. Exception: when the owner tagged
   themselves, that is a request for a draft, not an answer.
3. Skim 5-10 of the owner's own recent messages
   (`slack_search_public_and_private` with `from:<@their user id>`) to match their
   voice: length, language mix, emoji habits, greeting style.

## 2. Investigate (only inside the workspace root)

Scope is strictly the workspace root the listener names (the folder that holds the
repos and docs). Never read outside it, never read or quote `.env`, keys, tokens,
passwords, customer PII or case data.

- Code questions ("why does X happen", "where is Y handled", "is Z live"): Grep the
  relevant repos, read the actual code, check `git log` on the right branch
  (e.g. `main` = prod, plus any `beta` / `qa` branches) for when something changed.
  Name the file / function only if the asker is a dev.
- "Where is the setting for …" / "how do I do … in the app": find it in code first,
  then if a picture helps, open it in Chrome and take a screenshot (see 3).
- Read-only git works on any branch without checking it out: `git -C <repo> log
  origin/main`, `git -C <repo> show origin/beta:<path>`, `git -C <repo> grep <pat>
  origin/qa`, `git branch -a`. Local checkouts are often on an old feature branch,
  so look at the `origin/*` branches, not the working tree. `git fetch` is blocked,
  so remote branches are as of the last fetch; say so if it matters.
- Don't guess. If you can't confirm something, say so in the draft the way the owner
  would ("Need to check this properly, will update in a bit") and put what you found
  in the notes.

## 3. Screenshots with Claude in Chrome (only when they help and Chrome is enabled)

- If the workspace has a `CLAUDE.md` describing which Chrome profile and app URLs to
  use, follow it. Otherwise follow the listener prompt's Chrome note. Never use a
  browser/profile other than the one named there.
- Browsing is **read-only**: navigate, read, scroll, open menus/tabs to reach the
  page. Never click Save/Submit/Delete/toggle/apply or change any value.
- Screenshot the environment the asker uses (ops team / customers → prod). If the
  feature isn't on prod yet, use a staging environment and say so in the draft.
- Take the screenshot with `computer` `screenshot` (or `zoom` on the region) and
  `save_to_disk: true`. Return the saved path in `screenshots`. If a page errors
  or needs a login you don't have, say that in `notes_for_owner`; don't skip
  silently.
- To attach it to the draft: open the Slack thread in a **new tab** with an explicit
  `tabId` using the web-client thread URL from the listener prompt (never the
  permalink: it only offers "open in desktop app", which needs a click). Take a fresh
  screenshot of the content tab right before, then `upload_image` it onto the
  thread's message composer. Verify with a screenshot that the image sits in the
  composer **unsent**. Never click, type or press keys on a Slack tab. If attaching
  fails, skip it; the saved file is enough.
- The draft text never mentions the screenshot ("attached a ss", "see screenshot").
  Order: save the text draft first, then open the thread in the web client (the
  composer loads that draft) and drop the image into it.
- After `upload_image`, take screenshots (`wait` 3s between) until the thumbnail
  shows with no progress bar, then `wait` another 10s. Then close the Slack tab,
  reopen the same thread URL and check the image is still in the composer. If it's
  gone, attach again and leave that tab open; note it.
- Close the other tabs you opened.

## 4. Write it like the owner typed it

Language: follow the language mix the listener gives for this draft. With no
instruction, match what the owner usually writes. Technical content, settings,
names and steps always stay in plain English.

Do:
- Short, casual, direct. Usually 1-4 lines. Answer first, details after.
- Start every sentence with a capital letter. Light punctuation, contractions are fine.
- The draft tool takes standard markdown: bold is `**text**` (single `*text*` comes out
  italic). Rarely needed anyway.
- Slack formatting only when it helps: `code` for a setting key, a link, at most
  2-3 short bullets for steps.
- Tag people (`<@USERID>`) only if the owner would naturally loop them in.

Don't:
- No "Great question", "Certainly", "I hope this helps", "Let me know if you have
  any other questions", "Here's a breakdown", no sign-off.
- No em dashes (—), no headings, no bold walls, no perfectly parallel bullet lists,
  no emoji spam (one 👍/🙏 max, only if the owner uses them).
- Don't over-explain or restate the question. Don't invent facts, ETAs, or promises
  the owner hasn't made.
- No internal file paths/code for non-dev askers; for them describe where to click.
- External / client-facing people: plain English only.

Examples of the target voice:

> It's in settings → pick the org → "Auto drafts". Toggle it and refresh, should show up

> Checked, the issue is in the template step. Ran a fix on qa, try again in 10 min

> Not on prod yet. It's on beta, will let you know once the PR is merged

> Need to check this properly, will look at the logs and update in a bit

## 5. Save the draft

`slack_send_message_draft` with `channel_id`, `thread_ts` (the thread root's ts;
for a top-level mention that's the mention's own ts) and the text in standard
markdown. One draft only. Then report back (the listener expects this JSON):

```json
{"status": "drafted|skipped|failed", "draft_text": "...", "screenshots": ["/path.png"],
 "attached_in_slack": false, "notes_for_owner": "what you checked, confidence, anything to verify before sending"}
```
