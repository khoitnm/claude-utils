# claude-sessions-usage

Every time you chat with Claude Code, it writes a log of that chat on your own computer. There
are two scripts here that read those logs and tell you what the chats would have cost.

**They are free to run.** They never talk to Claude, so they use **zero Claude tokens** and
never eat into your usage limits. They only read files already on your disk (plus one small
web request to look up today's published prices). They never change or delete your logs.

Open a terminal in this folder and run one of these.

## 1. The monthly bill

```bash
python claude-sessions-usage.py
```

Answers: *"How much did I use Claude this month?"*

You get a grand total for the month on screen. The line-by-line detail — one row per chat, with
its date, a reminder of what it was about, its estimated cost and its token counts — goes into a
spreadsheet file (`.csv`) next to the report, so the reminder text is long enough to actually
recognise the chat.

## 2. The single-chat breakdown

```bash
python claude-session-analyze.py <session-id>
```

Answers: *"Why was that one chat so expensive, and what should I do differently?"*

The `<session-id>` is the long ID in the first column of the monthly report's `.csv` — copy and
paste it.

You get a short list of the biggest reasons that chat cost what it did (for example: a huge file
was read early on and then re-sent on every later message), each with a dollar figure and a
suggested fix, plus the best places you could have started a fresh chat to save money. The full
message-by-message detail goes into a spreadsheet file (`.csv`) instead of the screen.

## Notes

Both scripts print their report on screen *and* save a copy in the `reports/` folder, so you can
come back to it later. Nothing is ever overwritten.

**This is not a real bill.** On a Pro or Max subscription you pay a flat monthly fee, not per
message. The dollar figures answer "what would this have cost at Anthropic's public pay-per-use
prices" — useful for spotting waste, not for accounting.
