# implement-idea-full-cycle

Takes an idea — a sentence, a paragraph, or a bug report with the stack trace
pasted in — to a pull request that has already been reviewed and had the review
acted on, with nobody at the keyboard. It files the ticket and implements
the change by delegating to a skill in the project being worked on, then runs the
review and the fix pass as two **fresh-context subagents** — so the reviewer never
sees the author's reasoning and cannot rubber-stamp it.

It stops at an open PR. It never merges and never resolves a thread.

## Install

This repo doubles as a marketplace, so there is nothing to copy or link. From a
shell at the repo root:

```bash
claude plugin marketplace add ./
claude plugin install implement-idea-full-cycle@claude-utils
claude plugin install pr-review-inline@claude-utils
```

Or from inside a session, with `/plugin marketplace add ./` and
`/plugin install implement-idea-full-cycle@claude-utils`. The source must be a path the
resolver accepts — `./` or `./some/dir`, not a bare `C:\...`.

`pr-review-inline` is not optional: it is what posts the review in Step 3.

## What it needs from your project

**A skill that takes an idea to an open PR.** Filing a ticket in your tracker,
branching off your base branch and running your test command are all things a
general-purpose plugin cannot know, so this one delegates them — it names no
tracker, no branch and no test runner anywhere:

```
/implement-idea-full-cycle:idea-to-reviewed-pr --implement-with create-ticket-and-implement
   Make the nightly cleanup job log one summary per run instead of a line per row
```

Here `create-ticket-and-implement` is a skill in the project being worked on, and
it is the only thing that knows the tracker is JIRA, that tickets are `PROJ-…`,
that PRs target `dev` and that tests run with `mvn test`. The plugin just carries
the ticket key through to the report.

With no `--implement-with`, it looks for a project skill whose description covers
the ticket-to-PR round trip, and **stops rather than guessing** if there is more
than one candidate or none. Guessing wrong means filing a ticket in a real tracker.

## Already have a ticket?

Say so and it files nothing — it reuses the key for the branch, the commits and the
PR, and tells the project skill to skip its ticket step:

```
/implement-idea-full-cycle:idea-to-reviewed-pr --ticket PROJ-1234
   Make the nightly cleanup job log one summary per run instead of a line per row
```

A key or a tracker URL in the idea text works the same way, as does prose like
"this is filed as PROJ-1234". If the input says a ticket exists but never names
one, it stops and asks for the key rather than filing a duplicate.

**Only the ticket is reused** — the branch, the commits and the PR are new, off
your base branch, same as any other run. If the ticket already has a branch from
earlier work, your project skill's branch step refuses and the run stops with the
colliding name: resume that branch by checking it out and re-running, or leave it
alone. It will not quietly open a second PR against one ticket.

`gh` must be authenticated (`gh auth status`), and `git` on `PATH`.

## The two skills

| Skill | Use |
| --- | --- |
| `implement-idea-full-cycle:idea-to-reviewed-pr` | the whole unattended cycle |
| `implement-idea-full-cycle:handle-review-comments` | just the fix pass, interactively, on any PR |

`handle-review-comments` is worth invoking on its own. It verifies each comment is
actually right before touching anything — bot reviewers state wrong things with
total confidence — and replies to every thread, including the ones it disagrees
with.

## How a run goes

| Step | What happens |
| --- | --- |
| 0 | `pr_state.py` — is this a fresh run or a resume? |
| 1 | your project skill: ticket (unless one was supplied), branch, implementation, tests, PR |
| 2 | `wait_for_reviewers.py` — up to 9 min for Sonar/CI/Dependabot to post |
| 3 | fresh subagent runs `pr-review-inline:review`, posts inline findings |
| 3b | `pr_state.py` — did the review actually land? |
| 4 | fresh subagent runs `handle-review-comments`: verify, fix, reply |
| 4b | `pr_state.py --since <sha>` + a test re-run — what actually changed? |
| 5 | the report, built from verified numbers |

## Three things worth knowing before you run it

**It is capped at one review round, mechanically.** `pr_state.py` counts commits
carrying the `Review catch` marker and refuses to run the fix pass again on a
branch that already had one. If it cannot count them, it stops rather than
proceeding on faith.

**A subagent's report is treated as a claim, not evidence.** Steps 3b and 4b read
what is on the PR and in `git log`, and the report loses whenever the two disagree.
`--since` prints commit subjects and a `--stat`, never a diff, so verifying the fix
pass costs a few hundred tokens whether it changed three lines or three hundred.

**The clean-context reviewer gives something up.** It removes the author's bias,
but a reviewer who does not hold the ticket cannot check the code against what was
actually asked for. **Plan alignment stays your job at review time.**

## Resuming a died run

Re-run the same command. Step 0 finds the open PR on the branch and skips straight
to Step 2 — it will not file a second ticket.

If it stopped early, it wrote `.runs/<branch>.md` in the project, saying what
exists and what a human should do next. Add `.runs/` to that project's
`.gitignore`.
