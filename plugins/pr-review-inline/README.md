# pr-review-inline

Reviews a GitHub pull request as a principal engineer for its stack and posts the
findings back to the PR as line-anchored inline comments plus one summary
verdict. It detects the stack from the repo's own manifests and loads only the
checklists the diff actually needs, deferring to the reviewed repo's `CLAUDE.md`
and `.claude/rules` wherever they disagree. It recommends changes; it never makes
them.

## Install

This repo doubles as a single-plugin marketplace, so there is nothing to copy or
link. Add the marketplace once, then install from it, from a shell at this
repo's root:

```bash
claude plugin marketplace add ./
claude plugin install pr-review-inline@claude-utils
```

Or from inside a session, with `/plugin marketplace add ./` and
`/plugin install pr-review-inline@claude-utils`. The source must be a path the
resolver accepts — `./` or `./some/dir`, not a bare `C:\...`.

The marketplace source is this working copy on disk, so edits to the checklists
here reach every project — restart the session to pick them up. Moving the repo
breaks the marketplace path; re-run `/plugin marketplace add` from the new
location if that happens.

## Use it

From the repo whose PR you are reviewing:

```
/pr-review-inline:review 548
/pr-review-inline:review https://github.com/<owner>/<repo>/pull/548
/pr-review-inline:review 548 --dry-run                   # print the review, post nothing
/pr-review-inline:review 548 focus on the caching layer  # extra emphasis
```

With no argument it reviews the PR for the current branch. It submits as a
`COMMENT` review, never `APPROVE` or `REQUEST_CHANGES`. Asking for a PR review in
plain language works too — the skill description carries its own triggers.

Checking out the PR first is optional — the skill runs
`scripts/prepare-local-checkout.py` to read changed files from disk when it can,
and falls back to the GitHub MCP server when it cannot. That script never
disturbs a checkout with work in progress.

## Layout

| Path | What it is |
| --- | --- |
| `.claude-plugin/plugin.json` | Plugin manifest. The marketplace entry lives in this repo's root `.claude-plugin/marketplace.json`. |
| `skills/review/SKILL.md` | Entry point — the six-step review workflow. |
| `skills/review/pr-review-java/` | Java/Spring checklists, dispatched by their `INDEX.md`. |
| `skills/review/pr-review-react/` | React/TypeScript checklists, same shape. |
| `skills/review/pr-review-shared/` | Stack-agnostic pieces: workflow, stack detection, severity, GitHub posting. |
| `skills/review/scripts/` | The mechanical scanner, the checklist linter, and the local-checkout helper. See [`scripts/README.md`](skills/review/scripts/README.md). |

The checklist linter runs automatically on every edit under this plugin, via the
`PostToolUse` hook in this repo's `.claude/settings.json`. It is an authoring
guard for working *on* the checklists, so it stays project-local rather than
shipping in the plugin — installing the plugin elsewhere should not lint that
project's files.
