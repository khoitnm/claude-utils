# pr-review-inline scripts

Python 3, standard library only. Two are used during a review, one when editing
the skill, one as an edit-time hook.

## prepare-local-checkout.py — used *before* a review

Puts the PR head on disk so changed files can be read locally instead of one
MCP call per file, and so `grep` works for finding the sibling change that was
missed.

```bash
python scripts/prepare-local-checkout.py --pr 548 --repo-dir ../some-clone
python scripts/prepare-local-checkout.py https://github.com/o/r/pull/548
python scripts/prepare-local-checkout.py --pr 548 --check      # report only
python scripts/prepare-local-checkout.py --pr 548 --in-place   # move this checkout
python scripts/prepare-local-checkout.py --pr 548 --cleanup
```

It reports `status ready` with a `path` only when the tree there is verified to
be `refs/pull/<n>/head`. Anything else is `not-ready` with a reason and exit 3 —
the review then reads files through the GitHub MCP server instead. A **dirty
tree is never ready**, even at the right SHA: uncommitted edits mean the files
are not the PR's.

By default it adds a detached worktree in `../.pr-review/<repo>-pr-<n>` rather
than touching the clone, because a reviewer's main checkout usually has work in
it. Outside the repo, so the second copy stays out of its status and its IDE
indexing. Re-running updates the worktree when new commits land, which is what a
re-review needs. It refuses to move or delete a tree with uncommitted changes,
and `--in-place` refuses on a dirty clone rather than stashing behind your back.

## scan-mechanical-rules.py — used *during* a review

Regex-scans a PR diff for the rules a script can decide, so the model does not
carry them in context or spend attention on them.

```bash
python scripts/scan-mechanical-rules.py --pr 548
gh pr diff 548 | python scripts/scan-mechanical-rules.py --json
python scripts/scan-mechanical-rules.py --list        # the rule table
```

**Added lines only.** It never reads the working tree, so pre-existing code
cannot produce a hit — a PR is only ever flagged for what it introduces. That is
the point: these rules would be intolerable as a build gate over a codebase that
predates them.

Output is **candidates, not findings**. The scan has no context: it cannot see
that the concatenated SQL takes a constant, that the repo permits `var`, or that
the credential is a test fixture. Verify each hit before it reaches a PR.

Adding a rule: append to `RULES` as
`(lang, id, severity, pattern, message)`. The message must say what breaks, not
just what the pattern is. Use `PATH_GATE` when a pattern is only meaningful in
certain files. If a rule needs to understand scope, types, or control flow, it
does not belong here — leave it in the checklist prose for the model.

## lint-skill-docs.py — used when *editing* the skill

Enforces the structure that keeps the checklists cheap to load and worth
following.

```bash
python scripts/lint-skill-docs.py           # from the skill root
python scripts/lint-skill-docs.py --stats   # the token budget table
python scripts/lint-skill-docs.py --strict  # warnings fail too
```

Checks:

| Check | Why | Level |
| --- | --- | --- |
| Token budget per file (2500, 1800 for an INDEX, 1600 for SKILL.md) and 50k total | A 12k-token aspect file crowds out every other checklist on any PR that touches its subject | error |
| Links resolve | A dispatch index that points at a moved file silently stops dispatching | error |
| No project-specific identifiers (repo names, module names, ticket keys) | The checklists have to work on a repo nobody here has seen | error |
| Every file is referenced by its INDEX.md or SKILL.md | A file nothing dispatches to is never read | warning |
| No near-duplicate bullets across files | Two copies of a rule drift apart, and the reviewer raises it twice | warning |
| No preference-only bullets ("Never X." with no consequence) | The review bar requires naming a concrete failure; a bare preference cannot meet it | warning |

## hook-lint-on-edit.py — runs the linter automatically

A `PostToolUse` hook (wired in this repo's `.claude/settings.json`, matcher
`Write|Edit`) that runs the linter whenever a file inside this skill is edited:

- edited file is outside the skill → exits 0 without a word
- linter clean → silent
- warnings → fed back as context, non-blocking
- errors → exit 2, so the failure surfaces in the same turn that caused it

This is deliberately an edit-time hook rather than a git `pre-commit` one. The
mistake gets reported to whoever is editing, while they are still editing,
instead of at commit time where `--no-verify` walks past it and the context is
already gone.

It resolves its own path, so it works whether the hook runs with
`CLAUDE_PROJECT_DIR` set or with the repo root as the working directory, and
exits silently if it can find neither.
