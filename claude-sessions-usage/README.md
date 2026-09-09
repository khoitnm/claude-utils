# claude-sessions-usage

Token usage and estimated cost reports built from the local Claude Code session logs.

| File | Role |
| --- | --- |
| `claude-sessions-usage.py` | One row per session, for the current calendar month. |
| `claude-session-analyze.py` | Ranked findings for a single session, plus a per-turn ledger CSV. |
| `claude_usage.py` | Shared cost rules. Not run directly. |
| `session_insights.py` | Derived findings for one session. Not run directly. |

Three layers, and the boundary between them is the point:

- **`claude_usage.py` owns the numbers.** Rates, model matching, the billable-turn rule and the
  cost arithmetic. If two reports ever disagree about a session, a rule leaked out of here.
- **`session_insights.py` owns the inference.** Carry-cost attribution, growth causes, and the
  conclusions drawn from them. It never prints, so the same analysis could feed a different
  renderer or a cross-session trend later.
- **The two scripts own presentation only.** Layout, column widths, the report shell.

Anything that changes a number belongs in `claude_usage.py`; anything that changes a
*conclusion* belongs in `session_insights.py`; anything that changes a layout belongs in a
script.

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

`claude-session-analyze.py` leads with ranked findings, then two shortlists - the steps worth
fixing and the points the session could have been split at - and ends with the same rate table
and Enterprise handling as the month report. Its totals for a session are the same numbers that
session's row shows in the month report.

The full per-turn ledger is not printed. It goes to a `_steps.csv` beside the report, because on
a long session it is hundreds of rows to scroll past on the way to the conclusions, and it is the
one part of the report a spreadsheet handles better than a fixed-width table.

## Findings

A per-turn ledger prices a turn by what it spent at the moment it ran, which is the wrong
question for a session you want to make cheaper. Prompt tokens are re-sent on every later
turn, so what a turn really costs is what it *added* to the context multiplied by how many
turns were still to come. A 20k-token file read on step 20 of a 160-step session is not a
20k-token expense; it is a 20k × 140 expense.

That figure is **carry cost**, and ranking by it is what turns the ledger into advice:

```
1. [  $12.47] 74% of the bill ($12.47) was re-reading context, not doing work
2. [   $4.01] Starting a fresh session at step 93 was worth $4.01
3. [   $3.38] The static preamble cost $3.38 (20%) just by existing
4. [   $3.38] The 6 costliest single additions account for $3.38
         step  20    $1.58  + 19,651 tok re-read 142x  prompt / system-prompt expansion
         step  22    $0.63  +  7,966 tok re-read 140x  injected:nested_memory + Read(...)
...
```

Each finding carries the dollars at stake, the evidence behind it, and what to do about it.
Findings under 2% of the session, or under a cent, are dropped rather than padded out.

Beyond the ledger, the analysis reads several things the month report ignores:

- **Tool results** — how much context each tool poured in, and what carrying it cost.
- **Injected attachments** — memory files, skill listings, hook output, deferred tool schemas.
  Not conversation, and all controllable from outside the session.
- **Skill attribution** — cost split by the skill that was driving, where the transcript says.
- **Cache expiry** — turns billed a cache write far larger than the context grew, meaning the
  prompt cache had expired and the whole prefix was written again. A per-turn ledger cannot
  show this at all: the charge looks like an ordinary cache write. Since a write costs
  12.5–20× a read, an idle gap can be the single largest line in a session. One 380-turn
  session in testing spent **$34.35 of $148 (23%)** re-writing context across five idle gaps
  of 1–11 hours.
- **Compaction** — where the history was summarised away. Carry cost is computed within these
  spans, never across them, because nothing added before a boundary is re-read after it.

Sizing caveats, all stated in the report itself:

- Tool results and attachments are recorded as text, so their token counts are estimated at
  4 chars per token and marked `~`. Ledger figures are exact.
- Context growth that matches no recorded block is reported as
  `prompt / system-prompt expansion` — your prompts, plus skills and tool schemas the harness
  expanded mid-session. It is a residual, not a measurement.
- Split savings are net of re-reading the files the later work went back to, but files are the
  only dependency a transcript records. Reasoning carried in the conversation leaves no trace,
  so a split with no reach-back is the strongest claim the transcript supports, not a guarantee.
  Where a session has no prompt boundary to split on, the report falls back to the old
  `/clear`-anywhere figure and labels it a ceiling.

The report footer states how closely the attribution reconciles against what was actually
billed for prompt tokens — across all 324 local sessions this lands within a percent or two,
with a worst case around 12%. The residual is cache-boundary rounding: prefix growth and
billed cache writes do not line up token for token.

## Splitting a session, priced

"Clearing the context here would have saved $X" is easy to compute and impossible to act on,
because the saving assumes the work afterwards needed none of the history it dropped. The report
tests that assumption instead of asserting it.

Files are the one dependency a transcript records unambiguously: if a turn opens a file an
earlier turn already opened, the work has demonstrably come back to earlier ground. From that,
two things fall out.

**A `reach_back` column on every step** — the earliest step this one re-opened a file from.
A run of steps with no reach-back is a phase that stands alone; `reach_back` jumping back 60
steps is work that still depends on history from there.

**A priced split table.** Every turn that answers a new human prompt is a place the session
could have been split (splitting anywhere else would cut a turn off from the tool output it was
reacting to). Each one is costed both ways — what dropping the history saves, less what
re-reading the files the later work went back to would cost:

```
Step |      Net |    Saves | Drops Tok | Puts Back |  Files Revisited | The Prompt It Answers
  93 |  $4.0089 |  $4.1855 |   130,859 |   $0.1766 |  12 / ~3,924 tok | /handle-pr-review-comments
 136 |  $1.9354 |  $1.9707 |   175,206 |   $0.0353 |  10 / ~1,501 tok | yes, create another branch from this..
  21 |  $0.9493 |  $0.9493 |    18,928 |   $0.0000 |       0 / ~0 tok | /create-jira-and-implement-auto-mode
```

Reaching back does not rule a split out; it just has to be paid for. Re-reading twelve files
cost $0.18 against $4.19 of carrying, which is the shape of nearly every row: **a split is
cheap even when the next phase needs some of the same ground.**

## What to change, per step

The printed shortlist tags each step with the cheapest thing that would have changed its cost,
ranked by carry cost rather than by size. The same tag is the `lever` column in the CSV:

| Lever | Meaning |
| --- | --- |
| `SPLIT` | a new phase starts here and dropping the history before it beats re-reading |
| `CACHE` | an idle gap expired the prompt cache, re-writing the whole prefix at write rates |
| `WASTE` | an errored, interrupted or rejected call, which stays in the context regardless |
| `RE-READ` | a file already in the context was opened again |
| `NARROW` | a large tool result: `offset`/`limit` on Read, a tighter Grep, `head` on Bash output |
| `INJECT` | harness-injected text — memory files, hook output, tool schemas |
| `SCHEMA` | a prompt or a mid-session skill/tool-schema expansion, which never leaves again |
| `PROSE` | a long response, re-read by every later turn |

An untagged step is one that simply did its work. Steps under 1,000 tokens of growth are left
untagged whatever caused them.

## Report files

Every run prints to the console *and* saves the identical text to its own folder under
`reports/`, named with the local date and time it started:

```
reports/
  2026-09-08_21-11-36_session-analyze/session-analyze_8e3367d8-....txt
  2026-09-08_21-11-36_session-analyze/session-analyze_8e3367d8-..._steps.csv
  2026-09-08_21-11-37_sessions-usage/sessions-usage.txt
```

The `_steps.csv` is the per-turn ledger: one row per assistant turn, 22 columns, values raw
rather than formatted so it can be sorted and filtered. `context`/`growth` are what the turn
carried and how much was new, `added`/`reread_by` what it handed forward and how many turns then
re-read it, `cost`/`carry_cost` what it was billed against what its addition cost in total, and
`lever`/`reach_back` the two derived columns described above.

A run never overwrites an earlier one, so two reports can be diffed against each other. Two
runs starting inside the same second get a `-2`, `-3` suffix. The console output ends with a
`Report saved to:` line that is not part of the saved file.

Set `CLAUDE_USAGE_REPORT_DIR` to save somewhere other than `reports/`:

```bash
CLAUDE_USAGE_REPORT_DIR=/tmp/claude-reports python claude-sessions-usage.py
```

Saving is best-effort: if the folder cannot be created the run says so on stderr and still
prints the full report. A run that produces no output (an unknown session UUID, say) leaves no
empty folder behind. `reports/` is gitignored.

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
- Findings are derived from one session in isolation. There is no cross-session trend, and no
  comparison against what a similar session usually costs.
- Token counts for tool results and injected attachments are estimated from text length, not
  tokenized. Treat the findings as proportions rather than cents.
- Compaction boundaries are detected from a fall in context size, not from a marker in the
  transcript, so a genuine 10,000-token drop from some other cause would read as one.
- Context growth that matches no recorded block is lumped together as prompt and
  system-prompt expansion. The transcript does not size those separately, so the report cannot
  tell a long prompt apart from a skill that loaded mid-session.
