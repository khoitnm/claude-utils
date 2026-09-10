# pr-review-inline

Reviews a GitHub pull request as a principal engineer for its stack and posts the
findings back to the PR as line-anchored inline comments plus one summary
verdict. It detects the stack from the repo's own manifests and loads only the
checklists the diff actually needs, deferring to the reviewed repo's `CLAUDE.md`
and `.claude/rules` wherever they disagree. It recommends changes; it never makes
them.

## Link it into your user skills

The skill lives in this repo but has to sit in `~/.claude/skills` to be available
in every project. Link it rather than copying, so edits here take effect
everywhere immediately.

Windows (PowerShell, no admin needed — a junction, not a symlink):

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\pr-review-inline" -Target "<this-repo>\.claude\skills\pr-review-inline"
```

macOS / Linux:

```bash
mkdir -p ~/.claude/skills
ln -s "<this-repo>/.claude/skills/pr-review-inline" ~/.claude/skills/pr-review-inline
```

Restart the Claude Code session afterwards to pick it up.

The link breaks if this repo moves. To remove a stale one, delete the link and
not the files behind it — on Windows
`[System.IO.Directory]::Delete("$env:USERPROFILE\.claude\skills\pr-review-inline")`,
elsewhere `rm ~/.claude/skills/pr-review-inline`. Then re-run the command above.

## Use it

From the repo whose PR you are reviewing:

```
/pr-review-inline 548
/pr-review-inline https://github.com/<owner>/<repo>/pull/548
/pr-review-inline 548 --dry-run                      # print the review, post nothing
/pr-review-inline 548 focus on the caching layer     # extra emphasis
```

With no argument it reviews the PR for the current branch. It submits as a
`COMMENT` review, never `APPROVE` or `REQUEST_CHANGES`.

Checking out the PR first is optional — the skill runs
`scripts/prepare-local-checkout.py` to read changed files from disk when it can,
and falls back to the GitHub MCP server when it cannot. That script never
disturbs a checkout with work in progress. See
[`scripts/README.md`](scripts/README.md) for it and the other scripts.
