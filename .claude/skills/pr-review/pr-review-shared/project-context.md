# Shared: pulling in the reviewed repo's own context

Read these **only when the diff makes them relevant**. Loading every doc in the
repo before reviewing a 40-line change wastes context and buries the actual review.

## Always cheap, always worth it

| Source | Why |
| --- | --- |
| Root `CLAUDE.md` / `AGENTS.md` | The project's own conventions. A finding that contradicts CLAUDE.md is wrong; a violation of CLAUDE.md is a legitimate finding, and citing the rule makes it uncontestable. |
| Nested `CLAUDE.md` in a changed directory | Module-specific rules override root ones. |
| `README.md` of the changed module | Tells you what the module is for, which is what "correct" means here. |

## Read when the diff meets the condition

| Condition in the diff | Also read |
| --- | --- |
| A new public API, endpoint, or event is added | The repo's API/contract docs, OpenAPI spec, or `docs/api/**` — check the code matches the published contract. |
| The change alters a module boundary, adds a dependency between layers, or introduces a new service call | Architecture docs (`docs/architecture/**`, ADRs in `docs/adr/**`, `*.arch.md`). A layering violation is a blocker only if an ADR says so; otherwise it is a discussion. |
| The PR body links a ticket (Jira, Aha, GitHub issue) | Fetch it. The single most valuable check in review is *does this actually do what was asked* — you cannot answer that without the requirement. Use the issue tools for GitHub issues; ask the user for anything behind a system you cannot reach. |
| The PR touches auth, permissions, PHI/PII, audit, or tenancy | The repo's security or data-handling docs. In a healthcare codebase, mishandled PHI is a blocker, not a nitpick. |
| The repo has `.claude/skills/**` covering the changed area | Read the relevant skill. It encodes how this team wants that area written, and it is the cheapest source of house style. |
| The change modifies a shared library consumed by other repos | Check for a consumer list or a compatibility policy before calling a breaking change acceptable. |

## Do not read

- The whole `docs/` tree "for context".
- Architecture docs for a bug fix inside one method.
- Requirements for a dependency bump or a typo fix.

## Precedence when sources conflict

1. An explicit instruction in the PR description or from the user for this review.
2. The repo's `CLAUDE.md` / skills / ADRs.
3. The surrounding code's established pattern.
4. General best practice from these checklists.

If a checklist item here conflicts with the repo's own documented convention, the
repo wins — and say so rather than silently dropping the item, because a convention
that produces bad code is itself worth one comment (once, in the summary, not on
every occurrence).
