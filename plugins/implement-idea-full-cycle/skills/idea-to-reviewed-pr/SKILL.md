---
name: idea-to-reviewed-pr
description: Take an idea — a sentence, a paragraph, or a bug report with its error text — to a reviewed pull request with no questions asked. Files the tracker ticket, or reuses the one the input already names, implements it, opens the PR, waits for the bot reviewers, then has a clean-context reviewer post inline findings and a second clean-context agent fix and reply to them. One review round, then it stops. Use when the developer explicitly asks for the full unattended ticket-to-reviewed-PR cycle.
disable-model-invocation: true
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, ToolSearch, Skill, Agent
---

# idea-to-reviewed-pr

Input is **an idea**: a sentence, a paragraph, or a bug report with the error text and the full
stack trace pasted in. Output is **a PR that has already been reviewed and had the review acted
on**.

There is no length limit, and more detail is better rather than worse — every gap becomes an
assumption this run records in the PR body instead of asking about. What the input should *not*
be is the implementation plan: name the problem or the behaviour you want, and let Step 1 read the
codebase to work out where it lives.

The idea may already be filed — a ticket key, a tracker URL, or prose saying so. Then **this run
files nothing**: see [When the idea already has a ticket](#when-the-idea-already-has-a-ticket).

This skill is an orchestrator and almost nothing else. Three other skills hold all the judgement;
this one runs them in order, isolates two of them in fresh contexts, verifies what they claim, and
reports what happened. **Do not restate what those skills say and do not second-guess them** — a
copy of their rules here would rot the first time one of them changes.

| Step | Runs | Where |
| --- | --- | --- |
| 0 | `<skill-dir>/scripts/pr_state.py` | this context |
| 1 | the project's ticket-to-PR skill | this context |
| 2 | `<skill-dir>/scripts/wait_for_reviewers.py` | this context |
| 3 | `pr-review-inline:review` | fresh subagent |
| 3b, 4b | `<skill-dir>/scripts/pr_state.py` | this context |
| 4 | `implement-idea-full-cycle:handle-review-comments` | fresh subagent |
| 5 | the report | this context |

## What this needs from the host project

Two dependencies, and the run stops immediately if either is missing rather than improvising:

- **`pr-review-inline:review`** — the sibling plugin that posts Step 3's inline review. Install it
  from the same marketplace.
- **A ticket-to-PR skill in the project being worked on.** Step 1 files a ticket in *your*
  tracker, branches off *your* base branch, and runs *your* test command — none of which a
  general-purpose plugin can know. So it delegates.

Name that skill in the invocation with `--implement-with <skill-name>`. With nothing given,
look for a project skill whose description covers taking an idea to an open PR; if there is more
than one candidate, or none, **stop and say so** rather than guessing which one files tickets in
a real tracker.

## The three rules that shape everything

**Nobody is at the keyboard.** No `AskUserQuestion`, no "shall I proceed?", no ending a turn to
wait for an answer — in this context or in either subagent. A question asked here isn't answered;
it hangs until the developer comes back and finds nothing done. Ambiguity becomes a written
assumption, not a stop.

**Nothing here merges, and nothing here resolves a thread.** The cycle ends at a reviewed PR
sitting open against the base branch. Merging is the developer's call and resolving is the
reviewer's.

**A subagent's report is a claim, not evidence.** It says what the agent believes it did. Steps 3b
and 4b check what is actually on the PR and in git before any of it reaches the report, because
"the reviewer posted 6 findings" and "the fixer committed 4 fixes" are the two sentences in the
final summary the developer will act on without re-checking. `pr_state.py` answers both from a
`git log` and a comment count — no diff is read, so the check costs the same whether the change
was three lines or three hundred.

Steps 3 and 4 use the `Agent` tool. Some repos' `CLAUDE.md` bars it unless a skill asks for it —
this skill asks for it, and only for these two steps.

**Permission prompts are the developer's setup, not this skill's.** Subagents inherit this
session's permission mode, and a subagent that hits a prompt blocks with no prompt visible
anywhere — the run just stops looking busy. If Claude Code is prompting for edits or Bash calls,
say so once, up front (`/permissions` → *Accept edits*, or launch with
`--dangerously-skip-permissions`), then carry on.

## When the idea already has a ticket

Often the idea is already filed and the developer just wants the rest of the cycle run. **Then
this run files nothing** — no new ticket, and no ticket-creation skill invoked at all. Reuse the
key that was given; Step 1 still does everything else.

**Only the ticket is reused. The branch, the commits and the PR are all new**, cut off the base
branch exactly as on a fresh run — a supplied key shortens Step 1 by one step and changes nothing
else about it. The branch is still named from the key plus a fresh short suffix, so the commits and
the PR link back to the ticket the normal way.

Take the key from the first of these the input offers:

- `--ticket <key>` in the invocation.
- A tracker URL — the key is its last path segment (`…/browse/PROJ-1234` → `PROJ-1234`).
- A bare key in the prose, in whatever shape this project's tickets take (`PROJ-1234`).

A key mentioned as background — *"same class `PROJ-1120` touched last sprint"* — is not the ticket
for this idea. What makes it the ticket is the input saying so: *filed as*, *the ticket for this
is*, *implement `PROJ-1234`*. When both readings are plausible, treat the ticket as existing: that
wrong guess costs a reused ticket the developer can retitle, and the opposite one costs a duplicate
someone has to hunt down and close.

**If the input says a ticket exists but names no key, stop** — [stop
conditions](#stop-conditions). Filing one contradicts the input, and no key means nothing to name
the branch, the commits or the PR title after.

### A reused ticket may already have a branch

Step 0 asks about the branch you are standing on, not about the ticket — so it reports `FRESH_RUN`
from the base branch even when the supplied ticket was worked on before and already has a branch
and an open PR. A ticket old enough to be handed back to you is exactly the ticket that might.

That gap is covered where it shows up: a ticket-to-PR skill worth delegating to refuses to branch
when the name it wants already exists locally or on origin, so Step 1 stops there instead of
silently building on someone's work. **Let it stop, and do not retry with a different suffix.** Two
things produce that collision and the developer picks between them, not this run:

- **An earlier attempt at this same work.** Resuming is one command — check out that branch,
  re-run this skill, and Step 0 reports `RESUME` and skips Step 1 altogether.
- **Someone else already working the ticket.** A second branch and a second PR against one ticket
  is the duplicate-work version of the duplicate ticket this whole section avoids.

Report which branch name collided, since that is what the developer needs in order to choose.

## Step 0 — Is this a fresh run or a resumed one?

```bash
python <skill-dir>/scripts/pr_state.py "$(git branch --show-current)"
```

Step 1 is **not idempotent**: it files a tracker ticket. Re-running a run that died after Step 1
files a second ticket for the same idea and then fails to branch, so the cost of not asking is a
duplicate ticket someone has to close by hand. One cheap call rules it out.

Run this even when the ticket was supplied. The duplicate-ticket risk is gone in that case, but
the branch and the PR are still there from the first attempt, and Step 1 would trip over both.

The base branch is read from GitHub's own default branch for the repo. Pass `--base <ref>` when
the project merges somewhere else — a repo whose PRs target `develop` while its default branch is
`main`, for instance.

Act on the verdict:

| Verdict | Do this |
| --- | --- |
| `FRESH_RUN` | Step 1. This is the normal case. |
| `RESUME` | **Skip Step 1 entirely.** Take the PR URL, number and branch from the output, then go to Step 2. Do not file a ticket and do not branch. |
| `ALREADY_ANSWERED` | Skip Steps 1 and 4 — every comment already has a reply. Go to Step 5 and report the existing state. |
| `CAP_REACHED` | Stop. See [Stop conditions](#stop-conditions). |
| `CAP_UNCHECKED` / `TOOLING_MISSING` | Report the verdict and stop. Running Step 4 without a working round cap is how a branch collects three rounds of unattended commits. |

On a resumed run you will not have the ticket key, because it was never in this context. Read it
off the branch name or the PR title rather than re-deriving it from anything.

## Step 1 — Idea to open PR

Invoke the project's ticket-to-PR skill with the idea, unchanged. It owns the ticket, the branch,
the implementation, the tests and the PR.

**With a key from [the section above](#when-the-idea-already-has-a-ticket), invoke it with the
idea plus one override:**

```
The ticket for this already exists: <ticket-key>. Skip your ticket-filing step entirely —
file nothing, update nothing, and invoke no ticket-creation skill. Use that key for the
branch name, the commits and the PR title.

Only the ticket is reused: cut a new branch off the base branch and open a new PR, just as
you would on a fresh run. If your branch step refuses because a branch for that key already
exists, stop and report the name it collided with — do not retry with a different suffix.

Read the ticket first if your tracker tooling gives you a way to; it may carry detail the
idea text leaves out. If it does not, work from the idea text as given — do not add tooling
to go and fetch it, and do not stop over it.

Everything else in your skill stands unchanged: branch, explore, implement, test, push,
open the PR, and record your assumptions in the PR body as usual.
```

Two reasons that override lives here and not in the project's skill. "The ticket already exists"
is a property of this invocation rather than of the project — the project skill keeps filing
tickets for every other caller. And the read is written as optional on purpose: a ticket-filing
skill can usually create and update by key without having any command that hands back a ticket's
text, and a required read would turn an unattended run into a stop over something the input
already told you.

Follow it to its end, including its own stop conditions: if it stops, this skill stops too, at
the same place and for the same reason. Report what it reported and do not start Step 2.

Carry forward exactly four things: **the PR URL, the PR number, the ticket key, the branch name.**
Nothing else from this step crosses into Step 3 — see [Why the subagents start
clean](#why-the-subagents-start-clean).

On a supplied-ticket run the key is the one you passed in. If the skill reports a *different* key,
it filed one anyway despite the override: keep using your own key and name the stray ticket in
Step 5 so the developer can close it.

The URL and the number are both kept because they are used differently. Step 2 runs here, inside
the checkout, where `gh` reads the owner and repo off `origin` — a bare number is all it needs and
naming the repo would add nothing. Steps 3 and 4 pass the URL instead, because a PR number only
means something relative to a repo, and the URL says which one without this skill hardcoding it.

## Step 2 — Let the automated reviewers catch up

```bash
python <skill-dir>/scripts/wait_for_reviewers.py <pr-number>
```

Sonar, dependency-review and the CI checks post minutes after the PR opens, and Step 4 is worth
much more if their findings are already on the PR when it runs.

The script polls for up to nine minutes and **always exits 0** — settled, timed out, or gh
unusable. Do not treat any of those as a failure and do not re-run it; a timeout means the bots
are slow or broken, which is normal. Keep its verdict line for the Step 5 report and move on.

## Step 3 — Review it, clean room

One `Agent` call. `subagent_type: "general-purpose"` — **not `fork`**, which would hand it this
entire transcript and defeat the point.

Send it nothing but the coordinates. No diff summary, no list of files changed, no "I implemented
X by doing Y", no assumptions from Step 1:

```
Invoke the `pr-review-inline:review` skill on <pr-url>.

You have no prior knowledge of this PR. Read it from GitHub and judge it on its own
merits. Follow the skill exactly, including posting the inline comments and the summary
verdict to the PR.

Nobody is at the keyboard: ask no questions, and do not stop to confirm anything.

Report back: the number of inline comments you posted, and one line per finding naming
the file and what it says. Recommend changes; do not make them.
```

### Step 3b — Check it actually posted

```bash
python <skill-dir>/scripts/pr_state.py <branch-name>
```

**Decide what happens next from these numbers, not from the agent's report.** Two of them, read
in this order:

| Output | Meaning | Do this |
| --- | --- | --- |
| `review_comments: 0` while the agent claimed findings | the review never reached GitHub | Stop. Step 4 has nothing to act on, and a re-review would be round two. |
| `unanswered_comments: 0`, `review_comments` above 0 | every thread already has a reply | Skip Step 4, go to Step 5. |
| `unanswered_comments` above 0 | there is work | Step 4. |

If the agent's claimed count and `unanswered_comments` disagree but both are non-zero, carry on
with the verified number and note the discrepancy in Step 5.

Before dispatching Step 4, record `git rev-parse HEAD` — Step 4b needs it.

## Step 4 — Act on the review, clean room

A second `Agent` call, again `general-purpose`, again given only the coordinates plus the
overrides that `handle-review-comments` needs in order to run unattended:

```
Invoke the `implement-idea-full-cycle:handle-review-comments` skill on <pr-url>, on branch
<branch-name>.

You have no prior knowledge of this PR or of who wrote the review.

Three overrides to that skill, because nobody is at the keyboard:
- Ask no questions. Its "show the developer any reply that disagrees" gate cannot be
  met, so post every reply yourself — to human reviewers as well as to bots.
- Resolve no threads and merge nothing.
- Before your first commit, confirm `git branch --show-current` is <branch-name>. If it
  is not, change nothing and report that instead.
- Keep that skill's `Review catch (<reviewer>). <what was wrong>` line in every commit
  body. A later run counts those to know a fix round already happened, so a commit
  without the marker is a commit the round cap cannot see.

Everything else stands, above all its first job: verify each comment is actually right
before you touch anything. A confidently worded wrong suggestion breaking working code
is the main risk in this run, and every reply goes out under the developer's own
account — so a verdict you cannot evidence is a verdict you should not post.

You are reading this PR cold, which is deliberate, but it cuts both ways: a comment can
rest on something that was never in the repo — a team decision, another ticket's
direction, a conversation nobody wrote down. When that is what a comment turns on, say
so in the reply and leave the code alone. Do not fill the gap with a guess stated as
fact.
```

**This is the riskiest step in the skill** and the reason it is capped at one round. It pushes
commits to the PR branch on the strength of a review no human has read, and posts replies under
the developer's account. That skill's own verification job — check the comment is right before
touching anything — is what keeps it safe, so the override block above must never drop it.

### Step 4b — Check what it actually changed

```bash
python <skill-dir>/scripts/pr_state.py <branch-name> --since <sha-from-3b>
```

This is the answer to "the fix agent changed code in a context I cannot see". It prints the
commit subjects and a `--stat`, never a diff, so it costs the same few hundred tokens whether the
agent touched three lines or three hundred.

Three things to reconcile against the agent's report, and the report loses every time:

- **`commits_since`** — zero commits with a report full of fixes means nothing was committed.
- **`files_touched`** — files outside what the review commented on are scope creep, and the
  developer needs to hear about them by name in Step 5.
- **`unanswered_comments`** — should be at or near zero. Whatever is left is a thread the agent
  did not reply to, which reads as ignored.
- **`unpushed_commits`** — must be `0`. Anything else means the fixes are sitting in the local
  clone: the PR still shows the code the reviewer objected to, and every "Fixed in `abc1234`"
  reply points at a sha GitHub has never seen. This is the one item here you should repair
  rather than report — `git push` and re-run this check.

Then run the project's tests yourself, over whatever `files_touched` names. Use the same command
the Step 1 skill used — it already knows this project's runner, and a resumed run can read it out
of that skill. Prefer a digest (pass/fail counts) over a full log.

An agent saying "tests pass" is the one claim in this run that costs the most to be wrong about,
and re-running makes it cheap to confirm. **If the fix round broke a test, do not fix it here.**
Say so in Step 5 with the failing test named: a broken test on an open PR is visible and
recoverable, whereas an unattended agent patching its own breakage is the loop this skill is
capped to prevent.

## Step 5 — Hand it back

**One round only. Do not re-review after Step 4's commits.** A second pass invites the two agents
to re-litigate the same lines, and the developer reading the PR is the real next reviewer.

Print, in this order. **Every count comes from Step 3b/4b, not from what a subagent said** — if
the two disagreed, give the verified number and note the discrepancy:

1. The PR URL.
2. The ticket URL, and the branch name — say whether this run filed the ticket or reused one the
   input named.
3. Step 4b's test result, and Step 2's verdict line verbatim.
4. **Review outcome** — findings raised, fixed, rejected as wrong, noted as opinion. One line
   each, naming the file. Commit shas from `commits_since`.
5. **Posted under your name** — every reply Step 4 sent to a *human* reviewer, quoted, so the
   developer can see what went out on their behalf. `None` if the review was all bots.
6. **Left for the developer** — findings Step 4 judged wrong, comments it answered without
   changing code, checks still running when Step 2 gave up. `None` if there is nothing.

Then stop. Say that Step 1's assumptions are in the PR body rather than pasting them again, and
let the PR link be the thing the developer acts on.

## Why the subagents start clean

A reviewer that already knows why the code was written the way it was will agree with it. Passing
the diff, the design or the assumptions into Step 3 quietly converts the review into a
confirmation, and the whole cycle into theatre.

So only the PR number, URL, branch and ticket key cross the boundary. Everything else the
subagents need, they read from GitHub and the repo themselves.

Worth knowing what this does and does not buy: a clean context removes the author's bias, not the
model's blind spots. What makes Step 3 genuinely independent is that `pr-review-inline` brings its
own stack-gated checklists and a regex scan of the added lines. Expect it to catch checklist
violations and mechanical slips; do not expect it to catch the design mistake. Say so plainly in
Step 5 if the review came back thin.

It also gives up something real. A reviewer holding the ticket could check the code against what
was actually asked for; this one cannot, so **plan alignment is the developer's job at review
time**. Do not imply the review covered it.

## Stop conditions

Stop, say plainly what happened and what you'd need, and leave the repo where it is:

- **Either dependency is missing** — `pr-review-inline` is not installed, or no ticket-to-PR
  skill could be identified. Name what is missing and stop before filing anything.
- **The input says the idea is already filed but names no ticket key.** Say that the key is what
  is missing and that a re-run with it pasted in is all it takes. Nothing has been filed, branched
  or pushed at this point.
- **Step 0 says `CAP_REACHED`.** This branch has already had its one fix round. Report the PR
  URL, the response commits and any unanswered comments, and change nothing.
- **Step 0 says `CAP_UNCHECKED` or `TOOLING_MISSING`.** The round cap can't be enforced, and an
  unenforced cap is how a branch collects three rounds of unattended commits.
- **Step 1 hits any of its own stop conditions.** Its reasons are the right ones; don't work
  around them. If the ticket already exists, give its key — the ticket stays, it isn't wasted.
  A branch for a supplied ticket's key already existing is one of these: name the branch and let
  the developer choose between [resuming it and leaving it
  alone](#a-reused-ticket-may-already-have-a-branch).
- **Step 3b finds no comments on the PR** but Step 3 reported findings. The review didn't land.
- **Step 4 reports the wrong branch checked out.** Something moved the working tree mid-run.
  Nothing is committed; the review comments are already on the PR for the developer.

Everything else continues: a timed-out wait, a red CI check, a review that found nothing, a
finding Step 4 judged wrong, a test the fix round broke. Each of those is a line in the Step 5
report, not a reason to stop.

### Write the stop down before you stop

Whenever this skill stops early — any bullet above — write `.runs/<branch-name>.md` in the
*project* being worked on (not in the plugin) first:

```markdown
# <branch-name>
- stopped at: Step <n>
- reason: <the verdict line or stop condition, verbatim>
- pr: <url or "none">
- ticket: <key or "none">
- state: <what exists: ticket filed? branch pushed? comments posted? commits made?>
- next: <the one thing a human should do>
```

The report printed in chat is the first thing lost when the session ends, and an unattended run
stops precisely when nobody is watching. A developer returning hours later needs to know whether
a ticket was filed and whether anything was pushed — questions that are tedious to reconstruct
from git and the tracker, and free to answer from a file. Add `.runs/` to the project's
`.gitignore` if it isn't already; one file per branch, overwritten on a resumed run.
