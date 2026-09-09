# claude-sessions-usage

Token usage and estimated cost reports built from the local Claude Code session logs.

| File | Role |
| --- | --- |
| `claude-sessions-usage.py` | One row per session, for the current calendar month. |
| `claude-session-analyze.py` | One row per assistant turn, for a single session. |
| `claude_usage.py` | Shared rules. Not run directly. |

Both reports are presentation only — rates, model matching, the billable-turn rule and the
cost arithmetic all live in `claude_usage.py`, so the two cannot disagree about a session.
Anything that changes a number belongs in the shared module; anything that changes a layout
belongs in a script.

## What it does

Walks `~/.claude/projects/**/*.jsonl` (the transcripts Claude Code writes for every session),
sums the token usage reported on each assistant turn, and prices it at standard published
API rates. Sessions with no activity in the current `YYYY-MM` are skipped.

Output is a fixed-width table sorted by session start time, one row per session:

```
Claude Code Session Usage Report (2026-09)
Report Start Date:         2026-09-01 09:14:02
Report End Date:           2026-09-08 16:41:55
Pricing Source:            live from https://platform.claude.com/... (fetched 2026-09-08 19:26:27)
--------------------------------------------------------------------------------------------
Session Hash / ID | Start Date | End Date | Cost | Summary | Input Tok | Output Tok | Cache R | Cache W
--------------------------------------------------------------------------------------------
...
--------------------------------------------------------------------------------------------
Total Sessions This Month: 145
Total Token Usage:         Input: ... | Output: ... | Cache Read: ... | Cache Write: ...
Total Estimated Cost:      $2541.2742

Pricing Table Used (USD per million tokens)
------------------------------------------------------------------------------------------------
Model (rate row)          | Input | 5m Cache Write | 1h Cache Write | Cache Read | Output |  Turns |        Cost | Matched model IDs
------------------------------------------------------------------------------------------------
Opus 5                    | $5.00 |          $6.25 |         $10.00 |      $0.50 | $25.00 | 15,694 | $2,541.1345 | claude-opus-5
Haiku 4.5                 | $1.00 |          $1.25 |          $2.00 |      $0.10 |  $5.00 |      6 |     $0.1397 | claude-haiku-4-5-20251001
Unmatched (default rates) | $2.00 |          $2.50 |          $4.00 |      $0.20 | $10.00 |      8 |     $0.0000 | <synthetic>
------------------------------------------------------------------------------------------------
```

The report ends with the rate rows that actually produced the costs above — one row per
pricing row applied, with the transcript model IDs that matched it, the turn count, and the
cost attributed to it. Only in-month sessions feed it, so the `Cost` column sums to
`Total Estimated Cost`. A row labelled `(nearest)` means the exact model version was not in the
pricing table and the newest version of that family was used instead.

The `Summary` column is the session's conversation summary if one exists, otherwise its first
user prompt, collapsed to a single line and truncated to 40 characters.

Both tables are wide (200+ characters) — use a wide terminal or pipe the output to a file.

## Usage

```bash
python claude-sessions-usage.py                          # this month, one row per session
python claude-session-analyze.py <session-uuid>          # one session, one row per turn
```

Python 3.6+, standard library only. The month report takes no arguments; the per-turn report
takes the session UUID, which is the session's `.jsonl` filename and the first column of the
month report.

`claude-session-analyze.py` prints the same five priced token components per turn, flags any
turn reading more than 100,000 cached tokens with `(!)`, and ends with the same rate table and
Enterprise handling as the month report. Its totals for a session are the same numbers that
session's row shows in the month report.

It reads the session logs without modifying them, but it is not fully offline: it makes one
HTTPS request to the pricing docs (see below) and writes a small rate cache under
`~/.cache/claude-sessions-usage/`. With no network it still runs, using cached or built-in rates.

## Cost estimation

Rates are fetched at runtime from the published pricing page
(`https://platform.claude.com/docs/en/about-claude/pricing.md`) and parsed out of its model
pricing table, so per-model rates stay current without editing the script. There is no
machine-readable pricing endpoint — the Models API returns capabilities, not prices — so that
docs page is the authoritative source available.

The lookup degrades in four steps, and the report header names which one was used:

1. **Fresh cache** — a copy under `~/.cache/claude-sessions-usage/pricing.json` less than 24
   hours old is used without a network call.
2. **Live fetch** — 10-second timeout; on success the result is written to the cache.
3. **Stale cache** — if the fetch fails, an older cached copy is used and the failure reported.
4. **Built-in rates** — hardcoded in `FALLBACK_PRICING`, a snapshot as of 2026-09-08.

Every path prices five components separately: base input, output, 5-minute cache writes,
1-hour cache writes, and cache reads. Sessions that use 1-hour caching cost noticeably more to
write (for Opus, $10/MTok vs $6.25), and transcripts report the split under
`usage.cache_creation` — older transcripts carrying only a flat total are priced at the
5-minute rate.

Usage is counted per API response, not per log line. Claude Code writes one JSONL line per
content block and repeats the entire `usage` object on each, so a turn made of text plus a
tool call appears two or more times under a single message id. Those lines are one billable
response and are counted once; treating them as separate turns nearly doubles every figure on
a tool-heavy session. This rule lives in `read_session()` in `claude_usage.py` and is the one
both reports share.

Model IDs are matched to a rate row by family and version, so `claude-haiku-4-5-20251001`,
`claude-opus-5[1m]`, and `claude-3-5-sonnet-20241022` all resolve correctly. An unrecognized
version falls back to the newest known version in the same family; an unrecognized family
falls back to Sonnet 5 rates.

**This is not a bill.** On a Pro or Max subscription you are not charged per token at all — the
figure is "what these tokens would have cost at API list prices."

## Enterprise pricing

There is no Enterprise column by default, because there is no public number to put in it.
Anthropic does not publish per-token Enterprise rates — the docs state that volume and
enterprise pricing is negotiated case by case, via sales. (Claude Enterprise seats are also
priced per user, not per token, so a seat price cannot be attributed to a session either.)

If you know your organization's contracted discount off list, set it and the report adds a
`Cost (Ent)` column to the session table, a `Cost (Enterprise)` column to the pricing table,
and an Enterprise total:

```bash
CLAUDE_ENTERPRISE_DISCOUNT=30 python claude-sessions-usage.py    # 30% off list
CLAUDE_ENTERPRISE_DISCOUNT=0.30 python claude-sessions-usage.py  # same thing
```

The value is applied uniformly to every rate component. It is your number, not an
Anthropic-published rate, and the report says so under the table.

## Limitations

- Only the current calendar month; there is no flag for other date ranges.
- A session that spans a month boundary is counted in full if *any* of its turns fall in the
  current month, so its cost includes the earlier month's turns.
- Session logs are matched by filename, so a session resumed under a new file counts as two rows.
- Unreadable or malformed `.jsonl` files are skipped silently.
- Live rates are parsed out of a documentation page, not an API. If that page's table changes
  shape the parse yields nothing and the script falls back to cached or built-in rates — check
  the `Pricing Source` line if a total looks off.
